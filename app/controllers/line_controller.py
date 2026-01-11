import asyncio
import threading
import aiohttp
from fastapi import Request, Header, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from app.models.schemas import DeployLineRequest
from app.services import agent_service
from app.core.config import settings

# 用於紀錄 LINE Bot 設定的對照表
_LINE_BOT_STORAGE = {}

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

async def deploy_line(data: DeployLineRequest):
    try:
        line_bot_api = LineBotApi(data.access_token)
        bot_info = line_bot_api.get_bot_info()
        bot_user_id = bot_info.user_id
        
        # 1. 設置 Webhook URL，帶入 agent_{session_id}
        webhook_key = f"agent_{data.session_id}"
        webhook_url = f"{settings.BACKEND_URL}/api/line-webhook/{webhook_key}"
        
        _LINE_BOT_STORAGE[webhook_key] = {
            "access_token": data.access_token,
            "channel_secret": data.channel_secret,
            "session_id": data.session_id,  # 原始的 AI session_id (即 merchant config id)
            "bot_user_id": bot_user_id,     # LINE Bot 自己的 ID
            "bot_info": {
                "displayName": bot_info.display_name,
                "basicId": bot_info.basic_id
            }
        }
        
        line_bot_api.set_webhook_endpoint(webhook_url)
        
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
    if channel_id not in _LINE_BOT_STORAGE:
        raise HTTPException(status_code=404, detail="Unknown Channel ID")
        
    config = _LINE_BOT_STORAGE[channel_id]
    original_session_id = config["session_id"]
    access_token = config["access_token"]
    
    body = await request.body()
    payload = body.decode('utf-8')
    
    handler = WebhookHandler(config["channel_secret"])
    line_bot_api = LineBotApi(config["access_token"])
    
    @handler.add(MessageEvent, message=TextMessage)
    def handle_text_message(event):
        user_msg = event.message.text
        line_user_id = event.source.user_id
        line_bot_id = config["bot_user_id"]
        
        # 維持原本複雜的 threading + asyncio 邏輯以獲取結果
        result_container = []
        def run_async_logic():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            
            # 1. 顯示 Loading 效果
            new_loop.run_until_complete(show_loading(line_user_id, access_token))
            
            # 2. 呼叫 AI Agent
            res = new_loop.run_until_complete(agent_service.run_chat(
                user_message=user_msg, 
                config_session_id=original_session_id,
                app_name=f"agent_{original_session_id}",
                user_id=line_user_id,
                session_id=line_bot_id
            ))
            result_container.append(res)
            new_loop.close()
        
        t = threading.Thread(target=run_async_logic)
        t.start()
        t.join()
        result = result_container[0]
        
        reply_text = result.get("response_text", "抱歉，我現在無法回答。")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

    try:
        handler.handle(payload, x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    return "OK"
