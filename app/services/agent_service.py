import os
import json
import asyncio
import uuid
from google.adk import Runner
from adk_mongodb_session.mongodb.sessions.mongodb_session_service import MongodbSessionService
from google.genai import types
from google import genai
from typing import List, Optional, Dict, Any
import logging
from bson import ObjectId

from app.core.config import settings
from app.models.schemas import ChatStructuredOutput
from app.agents.bot_agents import main_agent
from app.prompts.templates import (
    FAQ_INSTRUCTION_HEADER, 
    SUBAGENT_INSTRUCTION, 
    HANDOFF_INSTRUCTION_HEADER, 
    HANDOFF_DISABLED_INSTRUCTION
)
from datetime import datetime
from app.core.database import agent_collection, user_collection, session_collection

# 1. 初始化全域服務 (使用 MongoDB)
session_service = MongodbSessionService(
    db_url=settings.MONGO_DB_URL,
    database=settings.MONGO_DB_NAME,
    collection_prefix=settings.MONGO_COLLECTION_PREFIX
)

# 3. 初始化 Runner
def get_runner(app_name: str):
    return Runner(
        agent=main_agent,
        app_name=app_name,
        session_service=session_service
    )
async def get_agents_by_admin(admin_id: str) -> List[Dict[str, Any]]:
    """取得該管理者的所有 Agent"""
    agents = []
    cursor = agent_collection.find({"admin_id": admin_id}).sort("updated_at", -1)
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        agents.append(doc)
    return agents

async def get_agent_by_id(agent_id: str) -> Optional[Dict[str, Any]]:
    """取得特定 Agent"""
    try:
        doc = await agent_collection.find_one({"_id": ObjectId(agent_id)})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc
    except:
        return None




async def clear_all_agent_sessions(agent_id: str):
    """刪除該 Agent 的所有使用者對話紀錄，強迫下次對話時重新讀取最新設定"""
    app_name = f"agent_{agent_id}"
    
    # 從我們管理的 session_collection 找出所有使用該 agent_id 的 session
    cursor = session_collection.find({"agent_id": agent_id})
    async for s in cursor:
        try:
            await session_service.delete_session(
                app_name=app_name,
                user_id=s["user_id"],
                session_id=s["session_id"]
            )
        except Exception as e:
            print(f"刪除 ADK Session 失敗 (可能已不存在): {e}")
            
    # 清除我們自己的紀錄
    await session_collection.delete_many({"agent_id": agent_id})
    print(f"已清理 Agent {agent_id} 的所有舊 Session。")

async def initialize_agent_system(config: dict, admin_line_user_id: str, agent_id: Optional[str] = None):
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
{{"response_text": "你的回覆", "related_faq_list": [{{"id": "faq1", "Q": "問題1", "A": "回覆1"}}, ...], "handoff_result": {{"hand_off": false, "reason": "使用者問題不符合設定的轉接真人客服條件"}}}}
```
"""

    user_config_data = {
        "router_instruction": router_prompt.strip(),
        "faq_instruction": faq_text.strip() + SUBAGENT_INSTRUCTION,
        "handoff_instruction": handoff_text+"\n-"+handoff_logic+SUBAGENT_INSTRUCTION if handoff_logic else handoff_text,
        "enable_handoff": enable_handoff,
        "raw_config": config
    }
    
    # 儲存或更新 Agent 設定到 MongoDB
    if agent_id:
        await agent_collection.update_one(
            {"_id": ObjectId(agent_id), "admin_id": admin_line_user_id},
            {
                "$set": {
                    "config": user_config_data,
                    "updated_at": datetime.now()
                }
            }
        )
        # 商家更新設定時，清除所有舊的對話紀錄以確保同步
        await clear_all_agent_sessions(agent_id)
    else:
        # 新增
        result = await agent_collection.insert_one({
            "admin_id": admin_line_user_id,
            "name": config.get('merchant_name', '未命名 Agent'),
            "config": user_config_data,
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        })
        agent_id = str(result.inserted_id)
    
    print(f"Agent {agent_id} 系統已更新，已清除所有關聯 Session。")
    return agent_id


async def run_chat(
    user_message: str, 
    line_user_id: str,
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_name: Optional[str] = None, # 新增
) -> dict:
    """
    執行對話
    :param user_message: 使用者訊息
    :param line_user_id: 使用者的 LINE User ID
    :param agent_id: MongoDB 中的 Agent ID (用於找出 config)
    :param session_id: 這次對話的 Session ID (UUID)
    :param user_name: 使用者名稱 (用於記錄 user collection)
    """
    if not agent_id:
        return {"response_text": "尚未指定 Agent ID，請由商家完成設定。", "related_faq_list": [], "handoff_result": {"hand_off": False, "reason": "No Agent ID"}}

    target_app_name = f"agent_{agent_id}"
    target_user_id = line_user_id
    target_session_id = session_id or str(uuid.uuid4())
    
    # 記錄或更新使用者資訊
    await user_collection.update_one(
        {"line_id": target_user_id},
        {
            "$set": {
                "name": user_name or target_user_id,
                "login_at": datetime.now()
            },
            "$setOnInsert": {
                "created_at": datetime.now()
            }
        },
        upsert=True
    )

    # 1. 檢查 Session Mode
    session_doc = await session_collection.find_one({"session_id": target_session_id})
    if session_doc and session_doc.get("mode") == "human":
        return {
            "response_text": "現在由專員為您服務中。", 
            "related_faq_list": [], 
            "handoff_result": {"hand_off": True, "reason": "Already in human mode"}
        }

    response_text = ""
    try:
        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_message)]
        )
        
        # 1. 檢查 Session 是否存在
        session = await session_service.get_session(
            app_name=target_app_name, 
            user_id=target_user_id, 
            session_id=target_session_id
        )
        
        # 獲取 Agent 配置
        agent = await agent_collection.find_one({"_id": ObjectId(agent_id)})
        if not agent or "config" not in agent:
            return {"response_text": "找不到對應的 Agent 設定，請商家確認設定流程。", "related_faq_list": [], "handoff_result": {"hand_off": False, "reason": "Agent Config not found"}}
        
        base_state = agent["config"].copy()
        # 注入當前上下文到 state，供工具或指令引用
        base_state["current_user_id"] = target_user_id
        base_state["current_agent_id"] = agent_id
        base_state["current_session_id"] = target_session_id
        
        if not session:
            # 2. 如果不存在，建立新的
            await session_service.create_session(
                app_name=target_app_name, 
                user_id=target_user_id, 
                session_id=target_session_id,
                state=base_state
            )
            
            # 記錄到我們管理的 session_collection
            await session_collection.update_one(
                {"session_id": target_session_id},
                {
                    "$set": {
                        "user_id": target_user_id,
                        "agent_id": agent_id,
                        "mode": "ai",
                        "updated_at": datetime.now()
                    },
                    "$setOnInsert": {
                        "created_at": datetime.now()
                    }
                },
                upsert=True
            )
        else:
            # 3. 如果已存在，更新 state (確保上下文與指令是最新的)
            session.state.update(base_state)

        # 3. 執行對話
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
        print("-"*10)
        print("模型輸出:", response_text)
        print("-"*10)
        
        # 4. 結構化輸出 (更強健的提取邏輯)
        try:
            import re
            # 尋找內容中的 JSON 區塊
            # 優先找 ```json ... ```，其次找第一個 { 到最後一個 }
            json_match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
            if not json_match:
                json_match = re.search(r"(\{.*\})", response_text, re.DOTALL)
            
            if json_match:
                clean_json = json_match.group(1).strip()
            else:
                clean_json = response_text.strip()
            
            # 處理 Python 布林值首字母大寫的問題 (常見的模型錯誤)
            clean_json = clean_json.replace(": True", ": true").replace(": False", ": false").replace(": None", ": null")
            clean_json = clean_json.replace(":True", ":true").replace(":False", ":false").replace(":None", ":null")
            
            structured_data = ChatStructuredOutput.model_validate_json(clean_json)
            
            return {
                "response_text": structured_data.response_text,
                "related_faq_list": [faq.model_dump() for faq in structured_data.related_faq_list],
                "handoff_result": structured_data.handoff_result.model_dump()
            }
        except Exception as e:
            print(f"解析輸出失敗: {e}, 原文: {response_text}")
            # 如果解析失敗，嘗試把整段文字當作回覆內容送出 (降級處理)
            return {
                "response_text": response_text,
                "related_faq_list": [],
                "handoff_result": {"hand_off": False, "reason": f"格式解析失敗但已保留原文"}
            }
                        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"response_text": f"對話發生錯誤: {e}", "related_faq_list": [], "handoff_result": {"hand_off": False, "reason": "系統錯誤"}}
