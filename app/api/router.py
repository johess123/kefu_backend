from fastapi import APIRouter, Request, Header
from app.models.schemas import FormData, ChatRequest, DeployLineRequest, LoginData, GenerateFAQRequest, OptimizeFAQRequest, AnalyzeFAQsRequest
from app.controllers import merchant_controller, chat_controller, line_controller
from typing import Dict, Any
from app.core.database import admin_collection
from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
from app.services import agent_service

api_router = APIRouter()

@api_router.get("/init_session")
async def init_session():
    return await chat_controller.init_session()

@api_router.post("/admin/login")
async def login_api(data: LoginData):
    print(f"Login API Request received for userId: {data.userId}")
    
    # 檢查 admin_collection 中是否有 name = data.userId 的
    admin = await admin_collection.find_one({"name": data.name})
    
    if not admin:
        print(f"Login failed: user {data.name} is not an admin")
        return {"isAdmin": False}

    try:
        ## 記錄或
        # 更新管理者資訊
        result = await admin_collection.update_one(
            {"name": data.name},
            {
                "$set": {
                    "line_id": data.userId,
                    "login_at": datetime.now(TAIPEI_TZ)
                # },
                # "$setOnInsert": {
                #     "created_at": datetime.now(TAIPEI_TZ)
                }
            }
            # },
            # upsert=True
        )
        print(f"Admin DB update result: matched={result.matched_count}")
    except Exception as e:
        print(f"Admin DB login error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    return {"isAdmin": True, "isMonitor": bool(admin.get("is_monitor", False))}

@api_router.post("/generate_faqs")
async def generate_faqs(data: GenerateFAQRequest):
    print(f"Generate FAQs Request: {data.brandDescription}")
    return await merchant_controller.generate_faqs(data)

@api_router.post("/optimize_faq")
async def optimize_faq(data: OptimizeFAQRequest):
    print(f"Optimize FAQ Request: {data.question}")
    return await merchant_controller.optimize_faq(data)

@api_router.post("/analyze_faqs")
async def analyze_faqs(data: AnalyzeFAQsRequest):
    print(f"Analyze FAQs Request for user: {data.line_user_id}")
    return await merchant_controller.analyze_faqs(data)

@api_router.post("/generate_prompt")
async def generate_prompt(data: FormData):
    return await merchant_controller.generate_prompt(data)

@api_router.get("/admin/agents")
async def get_agents(userId: str):
    return await agent_service.get_agents_by_admin(userId)

@api_router.get("/admin/agent/{agent_id}")
async def get_agent(agent_id: str, userId: str):
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

@api_router.get("/admin/agent/{agent_id}/available_subagents")
async def get_available_subagents(agent_id: str):
    return await agent_service.get_available_subagents(agent_id)

@api_router.post("/admin/agent/{agent_id}/add_subagent")
async def add_subagent(agent_id: str, data: Dict[str, str]):
    subagent_id = data.get("subagent_id")
    if not subagent_id:
        return {"error": "subagent_id is required"}
    success = await agent_service.add_subagent_to_agent(agent_id, subagent_id)
    return {"status": "ok" if success else "error"}

@api_router.post("/admin/agent/{agent_id}/update_faqs")
async def update_faqs(agent_id: str, data: Dict[str, Any]):
    admin_id = data.get("userId")
    faqs = data.get("faqs")
    if not admin_id or faqs is None:
        return {"error": "userId and faqs are required"}
    success = await agent_service.update_agent_faqs(agent_id, admin_id, faqs)
    return {"status": "ok" if success else "error"}

@api_router.post("/admin/agent/{agent_id}/update_handoff")
async def update_handoff(agent_id: str, data: Dict[str, Any]):
    admin_id = data.get("userId")
    triggers = data.get("handoff_triggers")
    custom = data.get("handoff_custom")
    if not admin_id or triggers is None:
        return {"error": "userId and handoff_triggers are required"}
    success = await agent_service.update_agent_handoff(agent_id, admin_id, triggers, custom or "")
    return {"status": "ok" if success else "error"}

@api_router.get("/admin/agent/{agent_id}/stats")
async def get_agent_stats(agent_id: str, userId: str):
    return await agent_service.get_agent_token_stats(agent_id, userId)

@api_router.post("/admin/agent/{agent_id}/update_config")
async def update_agent_config(agent_id: str, data: Dict[str, Any]):
    admin_id = data.get("userId")
    updates = data.get("updates")
    if not admin_id or updates is None:
        return {"error": "userId and updates are required"}
    success = await agent_service.update_agent_config(agent_id, admin_id, updates)
    return {"status": "ok" if success else "error"}

@api_router.post("/admin/agent/{agent_id}/toggle_subagent")
async def toggle_subagent(agent_id: str, data: Dict[str, Any]):
    admin_id = data.get("userId")
    subagent_id = data.get("subagent_id")
    enable = data.get("enable")
    if not admin_id or not subagent_id or enable is None:
        return {"error": "userId, subagent_id and enable are required"}
    success = await agent_service.toggle_subagent_enable(agent_id, admin_id, subagent_id, enable)
    return {"status": "ok" if success else "error"}

@api_router.post("/line-webhook/{channel_id}")
async def line_webhook(channel_id: str, request: Request, x_line_signature: str = Header(None)):
    return await line_controller.line_webhook(channel_id, request, x_line_signature)
