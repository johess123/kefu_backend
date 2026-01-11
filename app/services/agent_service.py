import os
import json
import asyncio
from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from google import genai
from typing import List, Optional, Dict, Any
import logging

from app.core.config import settings
from app.models.schemas import ChatStructuredOutput
from app.agents.bot_agents import main_agent
from app.prompts.templates import (
    FAQ_INSTRUCTION_HEADER, 
    SUBAGENT_INSTRUCTION, 
    HANDOFF_INSTRUCTION_HEADER, 
    HANDOFF_DISABLED_INSTRUCTION
)

# 1. 初始化全域服務
session_service = InMemorySessionService()

# 管理所有 Agent Sessions 的註冊表 (app_name -> {users: {user_id: session_id}})
_AGENT_SESSIONS_REGISTRY = {}

# 3. 初始化靜態 Runner (此處 Runner 為靜態，呼叫時再動態決定 app_name)
def get_runner(app_name: str):
    return Runner(
        agent=main_agent,
        app_name=app_name,
        session_service=session_service
    )

# 用於儲存使用者的設定狀態 (維持原本邏輯)
_CONFIG_CACHE = {}

async def initialize_agent_system(config: dict, session_id: str):
    global _CONFIG_CACHE
    
    # 準備 FAQ 指令
    faqs = config.get("faqs", [])
    faq_text = FAQ_INSTRUCTION_HEADER
    index = 1
    for item in faqs:
        faq_text += f"\nid: {item.get('id')}\nQ{index}: {item.get('question')}\nA{index}: {item.get('answer')}\n\n"
        index += 1

    # 準備路由指令
    handoff_logic = str(config.get("handoff_logic", "")).strip()
    
    if handoff_logic:
        handoff_section = f"""- 如果問題涉及"{handoff_logic}"，呼叫 handoff_expert 工具處理。"""
        enable_handoff = True
        handoff_text = HANDOFF_INSTRUCTION_HEADER
    else:
        handoff_section = """- 不提供轉接真人客服服務"""
        enable_handoff = False
        handoff_text = HANDOFF_DISABLED_INSTRUCTION

    # 檢查避免用語
    tone_avoid_section = ""
    tone_avoid = str(config.get("tone_avoid", "")).strip()
    if tone_avoid:
        tone_avoid_section = f"""- 避免使用以下語氣或用詞: {tone_avoid}"""

    router_prompt = f"""Instruction
- 你是一個智慧客服，你的任務是使用商家資訊與各種工具來回答使用者問題。
- 以{config.get('tone', '親切自然')}的語氣回覆。
{tone_avoid_section}
- 你要參考商家資訊與 tool 回傳的結果，產出統一的回覆。

# Input
商家資訊：
- 名稱：{config.get('merchant_name', '未命名')}
- 服務：{config.get('services', '一般諮詢')}
    
# Constraint
- 必須使用 faq_expert 工具判斷使用者問題是否涉及常見問題，並取得回覆。
{handoff_section}
- 無論是否呼叫了任何工具，都必須產出回應，不能只呼叫工具而不生成回覆。

# Language
- 使用繁體中文回答

# Output
- 以 JSON 格式回覆

# Example
```json
{{"response_text": "你的回覆", "related_faq_list": [{{"id": "faq1", "Q": "問題1", "A": "回覆1"}}, ...], "handoff_result": {{"hand_off": False, "reason": "使用者問題不符合設定的轉接真人客服條件"}}}}
```
"""

    user_config_data = {
        "router_instruction": router_prompt.strip(),
        "faq_instruction": faq_text.strip() + SUBAGENT_INSTRUCTION,
        "handoff_instruction": handoff_text+"\n-"+handoff_logic+SUBAGENT_INSTRUCTION if handoff_logic else handoff_text,
        "enable_handoff": enable_handoff
    }
    
    app_name = f"agent_{session_id}"
    user_id = f"user_{session_id}"
    
    # 儲存指令設定到快取，供後續 Get-or-Create 使用
    _CONFIG_CACHE[session_id] = user_config_data
    
    # 6. 管理註冊表 並 批次更新所有相關 Session
    if app_name not in _AGENT_SESSIONS_REGISTRY:
        _AGENT_SESSIONS_REGISTRY[app_name] = {"users": {}}
    
    # 確保當前這個 session_id 也在註冊表中
    _AGENT_SESSIONS_REGISTRY[app_name]["users"][user_id] = session_id

    # 找出所有屬於此 app_name 的使用者，並更新他們的 Session 到最新指令
    for u_id, s_id in list(_AGENT_SESSIONS_REGISTRY[app_name]["users"].items()):
        # 檢查並清理舊 Session
        old_session = await session_service.get_session(
            app_name=app_name, 
            user_id=u_id, 
            session_id=s_id
        )
        if old_session:
            await session_service.delete_session(
                app_name=app_name, 
                user_id=u_id, 
                session_id=s_id
            )
        
        # 使用最新的 user_config_data 重建 Session
        await session_service.create_session(
            app_name=app_name, 
            user_id=u_id, 
            session_id=s_id,
            state=user_config_data
        )
    
    print(f"Agent 系統已更新，已批次同步 {len(_AGENT_SESSIONS_REGISTRY[app_name]['users'])} 個 Session。")

async def run_chat(
    user_message: str, 
    session_id: str, 
    app_name: Optional[str] = None, 
    user_id: Optional[str] = None,
    config_session_id: Optional[str] = None
) -> dict:
    """
    執行對話
    :param config_session_id: 用於查詢指令設定的 ID (原始的 session_id)
    :param session_id: 實際在 Session Service 中的 ID (預設為 config_session_id，但在 LINE 中為 linebot_id)
    """
    lookup_id = config_session_id or session_id
    target_app_name = app_name or f"agent_{lookup_id}"
    target_user_id = user_id or f"user_{lookup_id}"
    target_session_id = session_id
    
    response_text = ""
    try:
        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_message)]
        )
        
        # 6. 管理註冊表
        if target_app_name not in _AGENT_SESSIONS_REGISTRY:
             _AGENT_SESSIONS_REGISTRY[target_app_name] = {"users": {}}
        _AGENT_SESSIONS_REGISTRY[target_app_name]["users"][target_user_id] = target_session_id

        # 3. Get or Create Session
        session = await session_service.get_session(
            app_name=target_app_name, 
            user_id=target_user_id, 
            session_id=target_session_id
        )
        
        if not session:
            # 如果 session 不存在，則使用 lookup_id 找 config
            config = _CONFIG_CACHE.get(lookup_id)
            if config:
                await session_service.create_session(
                    app_name=target_app_name, 
                    user_id=target_user_id, 
                    session_id=target_session_id,
                    state=config
                )
            else:
                return {"response_text": "系統會話不存在，且找不到對應的設定檔，請重新完成初始化設定。", "related_faq_list": [], "handoff_result": {"hand_off": False, "reason": "Session and Config not found"}}

        runner = get_runner(target_app_name)
        async for event in runner.run_async(
            user_id=target_user_id,
            session_id=target_session_id,
            new_message=content
        ):
            if hasattr(event, 'text') and event.text:
                response_text += str(event.text)
            elif hasattr(event, 'content') and event.content:
                parts = getattr(event.content, 'parts', [])
                for p in parts:
                    if hasattr(p, 'text') and p.text:
                        response_text += str(p.text)

        try:
            clean_json = response_text.strip()
            if clean_json.startswith("```"):
                lines = clean_json.split('\n')
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_json = '\n'.join(lines).strip()
            
            structured_data = ChatStructuredOutput.model_validate_json(clean_json)
            
            return {
                "response_text": structured_data.response_text,
                "related_faq_list": [faq.model_dump() for faq in structured_data.related_faq_list],
                "handoff_result": structured_data.handoff_result.model_dump()
            }
        except Exception as e:
            print(f"解析輸出失敗: {e}")
            return {
                "response_text": response_text,
                "related_faq_list": [],
                "handoff_result": {"hand_off": False, "reason": f"解析錯誤: {str(e)}"}
            }
                        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"response_text": f"對話發生錯誤: {e}", "related_faq_list": [], "handoff_result": {"hand_off": False, "reason": "系統錯誤"}}
