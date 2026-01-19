from fastapi import APIRouter, Request, Header
from app.models.schemas import FormData, ChatRequest, DeployLineRequest, LoginData
from app.controllers import merchant_controller, chat_controller, line_controller
from typing import Dict, Any

api_router = APIRouter()

@api_router.get("/init_session")
async def init_session():
    return await chat_controller.init_session()

from app.core.database import admin_collection
from datetime import datetime

@api_router.post("/admin/login")
async def login_api(data: LoginData):
    print(f"Login API Request received for userId: {data.userId}")
    
    try:
        # 記錄或更新管理者資訊
        result = await admin_collection.update_one(
            {"line_id": data.userId},
            {
                "$set": {
                    "name": data.name or data.userId,
                    "login_at": datetime.now()
                },
                "$setOnInsert": {
                    "created_at": datetime.now()
                }
            },
            upsert=True
        )
        print(f"Admin DB update result: matched={result.matched_count}, upserted_id={result.upserted_id}")
    except Exception as e:
        print(f"Admin DB login error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    return {"isAdmin": True}

@api_router.post("/generate_prompt")
async def generate_prompt(data: FormData):
    print(f"Generate Prompt Request: {data}")
    return await merchant_controller.generate_prompt(data)

@api_router.get("/admin/agents")
async def get_agents(userId: str):
    from app.services import agent_service
    return await agent_service.get_agents_by_admin(userId)

@api_router.get("/admin/agent/{agent_id}")
async def get_agent(agent_id: str, userId: str):
    from app.services import agent_service
    agent = await agent_service.get_agent_by_id(agent_id)
    if agent and agent.get("admin_id") == userId:
        return agent
    return {"error": "Not found or unauthorized"}

@api_router.post("/confirm_setup")
async def confirm_setup(data: Dict[str, Any]):
    print(f"Confirm Setup Request: {data}")
    return await merchant_controller.confirm_setup(data)

@api_router.post("/chat")
async def chat(data: ChatRequest):
    print(f"Chat Request: {data}")
    return await chat_controller.chat(data)

@api_router.post("/deploy_line")
async def deploy_line(data: DeployLineRequest):
    print(f"Deploy Line Request: {data}")
    return await line_controller.deploy_line(data)

@api_router.post("/line-webhook/{channel_id}")
async def line_webhook(channel_id: str, request: Request, x_line_signature: str = Header(None)):
    return await line_controller.line_webhook(channel_id, request, x_line_signature)
