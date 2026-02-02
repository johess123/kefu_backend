import os
import json
import asyncio
import uuid
from google.adk import Runner
from google.adk.agents.run_config import RunConfig
from adk_mongodb_session.mongodb.sessions.mongodb_session_service import MongodbSessionService
from google.genai import types
from google import genai
from typing import List, Optional, Dict, Any
import logging
from bson import ObjectId

from app.core.config import settings
from app.core.database import agent_collection, user_collection, session_collection, chat_collection, used_token_collection, subagent_collection
from app.models.schemas import ChatStructuredOutput
from app.agents.bot_agents import main_agent
from app.prompts.templates import (
    FAQ_INSTRUCTION_HEADER, 
    SUBAGENT_INSTRUCTION, 
    HANDOFF_INSTRUCTION_HEADER, 
    HANDOFF_DISABLED_INSTRUCTION
)
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import re

TAIPEI_TZ = ZoneInfo("Asia/Taipei")

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
    """取得特定 Agent，並帶入 subagent 詳情"""
    try:
        doc = await agent_collection.find_one({"_id": ObjectId(agent_id)})
        if doc:
            doc["_id"] = str(doc["_id"])
            
            # 取得使用的 subagent 詳情
            used_ids = doc.get("used_subagent", [])
            details = []
            if used_ids:
                object_ids = [ObjectId(id_str) for id_str in used_ids if id_str]
                cursor = subagent_collection.find({"_id": {"$in": object_ids}})
                async for sa in cursor:
                    sa["_id"] = str(sa["_id"])
                    details.append(sa)
            doc["used_subagent_details"] = details
            
        return doc
    except Exception as e:
        print(f"Error in get_agent_by_id: {e}")
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

    # 管理使用的 subagents (從資料庫動態獲取 ID)
    subagents_cursor = subagent_collection.find({})
    subagent_map = {}
    async for sa in subagents_cursor:
        subagent_map[sa["name"]] = str(sa["_id"])
    
    used_subagent = []
    # Knowledge Base (客服專員) 永遠啟用
    kb_id = subagent_map.get("Knowledge Base")
    if kb_id:
        used_subagent.append(kb_id)
    
    # Escalation Manager (協作專員) 根據是否有轉接人工規則啟用
    if enable_handoff:
        em_id = subagent_map.get("Escalation Manager")
        if em_id:
            used_subagent.append(em_id)

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
                    "used_subagent": used_subagent,
                    "updated_at": datetime.now(TAIPEI_TZ)
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
            "used_subagent": used_subagent,
            "created_at": datetime.now(TAIPEI_TZ),
            "updated_at": datetime.now(TAIPEI_TZ)
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
                "login_at": datetime.now(TAIPEI_TZ)
            },
            "$setOnInsert": {
                "created_at": datetime.now(TAIPEI_TZ)
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
        
        # 獲取 Subagent IDs 以便後續紀錄使用
        subagents_cursor = subagent_collection.find({"name": {"$in": ["Knowledge Base", "Escalation Manager"]}})
        subagent_id_map = {}
        async for sa in subagents_cursor:
            subagent_id_map[sa["name"]] = str(sa["_id"])
        kb_id = subagent_id_map.get("Knowledge Base")
        em_id = subagent_id_map.get("Escalation Manager")
        
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
                        "updated_at": datetime.now(TAIPEI_TZ)
                    },
                    "$setOnInsert": {
                        "created_at": datetime.now(TAIPEI_TZ)
                    }
                },
                upsert=True
            )
        else:
            # 3. 如果已存在，更新 state (確保上下文與指令是最新的)
            session.state.update(base_state)

        # 記錄使用者訊息
        user_chat_res = await chat_collection.insert_one({
            "session_id": target_session_id,
            "content": user_message,
            "sender": "user",
            "created_at": datetime.now(TAIPEI_TZ),
            "subagent_usage": []
        })
        user_chat_id = str(user_chat_res.inserted_id)

        # 3. 執行對話
        runner = get_runner(target_app_name)
        usage_list = []
        async for event in runner.run_async(
            user_id=target_user_id,
            session_id=target_session_id,
            new_message=content,
            run_config=RunConfig(
                context_window_compression=types.ContextWindowCompressionConfig(
                    trigger_tokens=90000,  # 觸發壓縮的 token 數
                    sliding_window=types.SlidingWindow(
                        target_tokens=75000,   # 壓縮後保留最近的 token 數
                    ),
                ),
            )
        ):
            if hasattr(event, 'text') and event.text:
                response_text += str(event.text)
            elif hasattr(event, 'content') and event.content:
                parts = getattr(event.content, 'parts', [])
                for p in parts:
                    if hasattr(p, 'text') and p.text:
                        response_text += str(p.text)
            
            if hasattr(event, 'usage_metadata') and event.usage_metadata:
                u = event.usage_metadata
                input_tokens = getattr(u, 'prompt_token_count', 0)
                output_tokens = getattr(u, 'candidates_token_count', 0)
                thought_token = getattr(u, 'thoughts_token_count', 0)
                tool_token = getattr(u, 'tool_use_prompt_token_count', 0)
                total_token = getattr(u, 'total_token_count', 0)
                
                usage_list.append({
                    "input_token": input_tokens,
                    "output_token": output_tokens,
                    "tool_token": tool_token,
                    "thought_token": thought_token,
                    "total_token": total_token
                })
                
        print("-"*10)
        print("模型輸出:", response_text)
        print("-"*10)
        
        # 4. 結構化輸出
        final_response_text = ""
        related_faq_list = []
        handoff_result = {"hand_off": False, "reason": "No Agent ID"}
        
        try:
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
            
            data_dict = json.loads(clean_json)
            # 確保即使欄位不存在，也會有基本的預設值，避免前端出錯
            final_response_text = data_dict.get('response_text', '')
            related_faq_list = data_dict.get('related_faq_list', [])
            handoff_result = data_dict.get('handoff_result', {"hand_off": False, "reason": "使用者問題不符合設定的轉接真人客服條件"})
        except Exception as e:
            print(f"解析輸出失敗: {e}, 原文: {response_text}")
            # 如果解析失敗，嘗試把整段文字當作回覆內容送出 (降級處理)
            final_response_text = response_text
            handoff_result = {"hand_off": False, "reason": f"格式解析失敗但已保留原文"}

        # 判斷使用的 subagent
        used_subagent_ids = []
        if related_faq_list and kb_id:
            used_subagent_ids.append(kb_id)
        if handoff_result.get("hand_off") and em_id:
            used_subagent_ids.append(em_id)

        # 記錄 AI 回覆
        ai_chat_res = await chat_collection.insert_one({
            "session_id": target_session_id,
            "content": final_response_text,
            "sender": "ai",
            "created_at": datetime.now(TAIPEI_TZ),
            "subagent_usage": used_subagent_ids
        })
        ai_chat_id = str(ai_chat_res.inserted_id)

        # 記錄 Token 消耗
        for usage in usage_list:
            await used_token_collection.insert_one({
                "chat_id": ai_chat_id,
                "admin_id": agent.get("admin_id"),
                "agent_id": agent_id,
                "subagent_id": used_subagent_ids,
                "session_id": target_session_id,
                "model": settings.AGENT_MODEL,
                "usage_type": "聊天",
                "usage": usage,
                "created_at": datetime.now(TAIPEI_TZ)
            })

        return {
            "response_text": final_response_text,
            "related_faq_list": related_faq_list,
            "handoff_result": handoff_result
        }
                        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"response_text": f"對話發生錯誤: {e}", "related_faq_list": [], "handoff_result": {"hand_off": False, "reason": "系統錯誤"}}

async def get_available_subagents(agent_id: str) -> List[Dict[str, Any]]:
    """取得該 Agent 還沒使用的官方 subagents"""
    agent = await get_agent_by_id(agent_id)
    if not agent:
        return []
    
    used_ids = agent.get("used_subagent", [])
    # 轉換 ID 格式以便查詢
    object_ids = [ObjectId(id_str) for id_str in used_ids if id_str]
    
    available = []
    cursor = subagent_collection.find({"_id": {"$nin": object_ids}})
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        available.append(doc)
    return available

async def add_subagent_to_agent(agent_id: str, subagent_id: str):
    """將 subagent 加入 Agent 的使用清單"""
    result = await agent_collection.update_one(
        {"_id": ObjectId(agent_id)},
        {"$addToSet": {"used_subagent": subagent_id}}
    )
    return result.modified_count > 0

async def update_agent_faqs(agent_id: str, admin_id: str, faqs: List[Dict[str, Any]]):
    """更新 Agent 的 FAQ 並重新初始化系統"""
    agent = await get_agent_by_id(agent_id)
    if not agent or agent.get("admin_id") != admin_id:
        return False
    
    raw_config = agent.get("config", {}).get("raw_config", {})
    raw_config["faqs"] = faqs
    
    await initialize_agent_system(raw_config, admin_id, agent_id)
    return True

async def update_agent_handoff(agent_id: str, admin_id: str, handoff_triggers: List[str], handoff_custom: str):
    """更新 Agent 的轉接人工邏輯並重新初始化系統"""
    agent = await get_agent_by_id(agent_id)
    if not agent or agent.get("admin_id") != admin_id:
        return False
    
    raw_config = agent.get("config", {}).get("raw_config", {})
    
    # 組合轉接邏輯文字
    all_triggers = []
    if handoff_triggers:
        all_triggers.extend(handoff_triggers)
    if handoff_custom:
        custom_list = [t.strip() for t in handoff_custom.replace("、", ",").split(",") if t.strip()]
        all_triggers.extend(custom_list)
        
    if all_triggers:
        raw_config["handoff_logic"] = f"當使用者提到以下任何一項時轉接：{', '.join(all_triggers)}"
    else:
        raw_config["handoff_logic"] = ""
        
    await initialize_agent_system(raw_config, admin_id, agent_id)
    return True

async def get_agent_token_stats(agent_id: str, admin_id: str):
    """取得 Agent 的 Token 使用統計、近期紀錄與營運指標"""
    now = datetime.now(TAIPEI_TZ)
    today_start = datetime.combine(now.date(), time.min)
    first_day_of_month = datetime(now.year, now.month, 1)
    
    # 統計今日對話數 (計算今日產生的聊天紀錄)
    # 透過 session_collection 找出該 agent 的 session
    session_ids = []
    async for s in session_collection.find({"agent_id": agent_id}):
        session_ids.append(s["session_id"])
    
    today_chats = 0
    if session_ids:
        today_chats = await chat_collection.count_documents({
            "session_id": {"$in": session_ids},
            "sender": "user",
            "created_at": {"$gte": today_start}
        })

    # 統計本月 Token 消耗
    input_tokens = 0
    output_tokens = 0
    total_points = 0 # 假設 1000 tokens = 1 點, 這裡先用 placeholder 或者根據需求計算
    
    pipeline = [
        {"$match": {
            "agent_id": agent_id,
            "created_at": {"$gte": first_day_of_month}
        }},
        {"$group": {
            "_id": None,
            "total_input": {"$sum": "$usage.input_token"},
            "total_output": {"$sum": "$usage.output_token"},
            "count": {"$sum": 1}
        }}
    ]
    
    stats_cursor = used_token_collection.aggregate(pipeline)
    async for result in stats_cursor:
        input_tokens = result.get("total_input", 0)
        output_tokens = result.get("total_output", 0)
    
    # 最近 10 筆紀錄
    history = []
    cursor = used_token_collection.find({"agent_id": agent_id}).sort("created_at", -1).limit(10)
    async for doc in cursor:
        history.append({
            "id": str(doc["_id"]),
            "time": doc["created_at"].strftime("%Y-%m-%d %H:%M"),
            "item": doc["usage_type"],
            "change": -(doc["usage"]["total_token"] // 100), # 假設消耗點數 = total_token / 100
            "balance": 1250 # Placeholder, 實際應從帳戶餘額扣除
        })
    
    return {
        "monthly_usage": {
            "points": abs(sum(h["change"] for h in history if h["change"] < 0)), # Placeholder
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        },
        "daily_stats": {
            "today_chats": today_chats,
            "health_score": 100 # 目前預設為 100，未來可根據錯誤率計算
        },
        "history": history
    }

async def update_agent_config(agent_id: str, admin_id: str, updates: Dict[str, Any]):
    """更新 Agent 的基本配置 (商家資訊, 語氣等)"""
    agent = await get_agent_by_id(agent_id)
    if not agent or agent.get("admin_id") != admin_id:
        return False
    
    raw_config = agent.get("config", {}).get("raw_config", {})
    
    # 更新欄位
    if "merchant_name" in updates:
        raw_config["merchant_name"] = updates["merchant_name"]
    if "services" in updates:
        raw_config["services"] = updates["services"]
    if "website_url" in updates:
        raw_config["website_url"] = updates["website_url"]
    if "tone" in updates:
        raw_config["tone"] = updates["tone"]
    if "tone_avoid" in updates:
        raw_config["tone_avoid"] = updates["tone_avoid"]
    
    # 同步更新 agent table 的 name
    if "merchant_name" in updates:
        await agent_collection.update_one(
            {"_id": ObjectId(agent_id)},
            {"$set": {"name": updates["merchant_name"]}}
        )

    await initialize_agent_system(raw_config, admin_id, agent_id)
    return True
