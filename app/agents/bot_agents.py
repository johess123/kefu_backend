from google.adk.agents import LlmAgent
from google.adk.tools import agent_tool, ToolContext
from app.core.config import settings

import asyncio
from bson import ObjectId
from linebot import LineBotApi
from linebot.models import TextSendMessage

from app.core.database import user_collection, agent_collection, session_collection
from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
import time
import random
import string

def get_notify_code():
    # 產生唯一通知碼
    timestamp = int(time.time())  # 取得當前時間戳（秒）
    rand_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4)) # 隨機 4 碼英數組合
    return f"{timestamp}-{rand_part}"

async def call_human_support(tool_context: ToolContext, query: str) -> dict:
    """
    轉接真人客服
    args:
        query: 使用者問題
    return:
        {"text": "已轉接真人客服"}
    """
    # 從 state 拿真正的 user id, agent id 與 session id
    user_id = tool_context.state.get("current_user_id")
    agent_id = tool_context.state.get("current_agent_id")
    session_id = tool_context.state.get("current_session_id")

    if not user_id or not agent_id or not session_id:
        print(f"Error: Missing context in tool state. user_id: {user_id}, agent_id: {agent_id}, session_id: {session_id}")
        return {"text": "轉接失敗，系統上下文缺失。"}
    
    try:
        # 1. 更新 Session Mode (改為更新 session 而非 user)
        await session_collection.update_one(
            {"session_id": session_id},
            {"$set": {"mode": "human", "updated_at": datetime.now(TAIPEI_TZ)}}
        )
        
        # 2. 獲取 Agent 與部署資訊 (為了拿 admin_id 和 access_token)
        agent = await agent_collection.find_one({"_id": ObjectId(agent_id)})
        if not agent:
            return {"text": "轉接失敗，找不到客服配置。"}
        
        admin_id = agent.get("admin_id")
        deploy_config = agent.get("deploy_config", {})
        access_token = deploy_config.get("access_token")
        
        if admin_id and access_token:
            line_api = LineBotApi(access_token)
            # 取得使用者名稱 (選用)
            user = await user_collection.find_one({"line_id": user_id})
            user_name = user.get("name", user_id) if user else user_id
            
            notify_code = get_notify_code()
            notify_text = f"🔔 [真人客服通知]\n使用者：{user_name}\n時間：{datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')}\n訊息代碼：{notify_code}\n使用者訊息：{query}"
            
            line_api.push_message(admin_id, TextSendMessage(text=notify_text))
            return {"text": "已轉接真人客服"}
        else:
            return {"text": "轉接失敗，配置不完整。"}
            
    except Exception as e:
        print(f"Handoff Error: {e}")
        import traceback
        traceback.print_exc()
        return {"text": f"轉接過程發生錯誤: {str(e)}"}

# Note: instructions are injected dynamically via session state
faq_agent = LlmAgent(
    name="faq_expert", 
    model=settings.AGENT_MODEL, 
    instruction="{faq_instruction}",
    description="FAQ 智能助手",
    output_key="faq_result"
)

handoff_agent = LlmAgent(
    name="handoff_expert", 
    model=settings.AGENT_MODEL, 
    instruction="{handoff_instruction}",
    description="轉接真人客服智能助手",
    tools=[call_human_support],
    output_key="handoff_result"
)

faq_tool = agent_tool.AgentTool(agent=faq_agent)
handoff_tool = agent_tool.AgentTool(agent=handoff_agent)

main_agent = LlmAgent(
    name="main_router",
    model=settings.AGENT_MODEL,
    instruction="{router_instruction}",
    description="負責協調所有客服流程、決定要呼叫哪些 tool，並彙整各個 tool 的回傳結果後產出統一的回覆",
    tools=[faq_tool, handoff_tool, call_human_support]
)
