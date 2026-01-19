import asyncio
import threading
import aiohttp
import time
import random
import string
from bson import ObjectId
from datetime import datetime

from fastapi import Request, Header, HTTPException

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, PostbackEvent

from app.services import line_richmenu_service
from app.models.schemas import DeployLineRequest
from app.services import agent_service
from app.core.config import settings
from app.core.database import agent_collection, user_collection, session_collection

# 用於紀錄 LINE Bot 設定的對照表 (即將移除，改用 MongoDB)
_LINE_BOT_STORAGE = {}

def get_notify_code():
    # 產生唯一通知碼
    timestamp = int(time.time())  # 取得當前時間戳（秒）
    rand_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4)) # 隨機 4 碼英數組合
    return f"{timestamp}-{rand_part}"

async def show_loading(user_id: str, access_token: str):
    """顯示訊息 loading 效果"""
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "chatId": user_id,
            "loadingSeconds": 60
        }
        async with session.post("https://api.line.me/v2/bot/chat/loading/start", headers=headers, json=payload) as resp:
            return await resp.text()

async def switch_mode(sid: str, new_mode: str, source="manual"):
    """切換客服模式並記錄到 MongoDB"""
    display_mode = "【真人客服】" if new_mode == "human" else "【AI客服】"
    await session_collection.update_one(
        {"session_id": sid},
        {"$set": {"mode": new_mode, "updated_at": datetime.now()}}
    )
    return f"已手動切換為 {display_mode} 模式。"

async def deploy_line(data: DeployLineRequest):
    try:
        line_bot_api = LineBotApi(data.access_token)
        bot_info = line_bot_api.get_bot_info()
        bot_user_id = bot_info.user_id
        
        # 1. 設置 Webhook URL，帶入 agent_{agent_id}
        webhook_key = f"agent_{data.agent_id}"
        webhook_url = f"{settings.BACKEND_URL}/api/line-webhook/{webhook_key}"
        # webhook_url = f"https://56f6f1b025b5.ngrok-free.app/api/line-webhook/{webhook_key}"
        
        deploy_config = {
            "access_token": data.access_token,
            "channel_secret": data.channel_secret,
            "bot_user_id": bot_user_id,
            "display_name": bot_info.display_name,
            "basic_id": bot_info.basic_id
        }

        # 2. 儲存部署資訊到 MongoDB agent collection
        await agent_collection.update_one(
            {"_id": ObjectId(data.agent_id)},
            {
                "$set": {
                    "deploy_type": "line",
                    "deploy_config": deploy_config,
                    "updated_at": datetime.now()
                }
            }
        )
        
        line_bot_api.set_webhook_endpoint(webhook_url)

        # 3. 如果有設定轉接邏輯，上傳 Rich Menu
        agent = await agent_collection.find_one({"_id": ObjectId(data.agent_id)})
        if agent and agent.get("config", {}).get("enable_handoff"):
            line_richmenu_service.upload_and_set_default_richmenu(data.access_token)
            print(f"Agent {data.agent_id} Rich Menu 上傳完成")
        
        return {
            "status": "ok",
            "channel_id": webhook_key,
            "bot_info": {
                "displayName": bot_info.display_name,
                "basicId": bot_info.basic_id
            }
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

async def line_webhook(channel_id: str, request: Request, x_line_signature: str = Header(None)):
    # channel_id 格式為 agent_{agent_id}
    if not channel_id.startswith("agent_"):
        raise HTTPException(status_code=404, detail="Invalid Channel ID format")
    
    agent_id_str = channel_id.replace("agent_", "")
    
    # 1. 從 MongoDB 抓取部署資訊
    agent = await agent_collection.find_one({"_id": ObjectId(agent_id_str)})
    if not agent or agent.get("deploy_type") != "line":
        raise HTTPException(status_code=404, detail="Bot configuration not found")
        
    config = agent["deploy_config"]
    access_token = config["access_token"]
    channel_secret = config["channel_secret"]
    admin_id = agent.get("admin_id")
    
    body = await request.body()
    payload = body.decode('utf-8')
    
    handler = WebhookHandler(channel_secret)
    line_bot_api = LineBotApi(access_token)
    
    # 手動解析事件並使用非同步處理，避免跨 Loop 報錯
    try:
        events = handler.parser.parse(payload, x_line_signature)
        for event in events:
            line_user_id = event.source.user_id
            stable_session_id = f"line_{agent_id_str}_{line_user_id}"

            if isinstance(event, PostbackEvent):
                data = event.postback.data
                try:
                    params = dict(p.split("=") for p in data.split("&"))
                    action = params.get("action")
                    if action == "change_mode":
                        new_mode = params.get("mode")
                        reply_text = await switch_mode(stable_session_id, new_mode)
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                except Exception as e:
                    print(f"Error parsing postback: {e}")

            elif isinstance(event, MessageEvent) and isinstance(event.message, TextMessage):
                user_msg = event.message.text
                
                # 獲取使用者名稱
                try:
                    profile = line_bot_api.get_profile(line_user_id)
                    user_name = profile.display_name
                except:
                    user_name = line_user_id

                # 1. 先檢査 Session mode
                session_doc = await session_collection.find_one({"session_id": stable_session_id})
                mode = session_doc.get("mode", "ai") if session_doc else "ai"
                
                if mode == "human":
                    # 直接轉發給 Admin
                    if admin_id:
                        notify_code = get_notify_code()
                        notify_text = f"🔔 [真人客服通知]\n使用者：{user_name}\n時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n訊息代碼：{notify_code}\n使用者訊息：{user_msg}"
                        line_bot_api.push_message(admin_id, TextSendMessage(text=notify_text))
                else:
                    # 2. 顯示 Loading 效果
                    await show_loading(line_user_id, access_token)
                    
                    # 3. 呼叫 AI Agent
                    res = await agent_service.run_chat(
                        user_message=user_msg, 
                        line_user_id=line_user_id,
                        user_name=user_name,
                        agent_id=agent_id_str,
                        session_id=stable_session_id
                    )
                    
                    reply_text = res.get("response_text")
                    if reply_text:
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Webhook Error: {str(e)}")

    return "OK"
