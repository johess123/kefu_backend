from fastapi import APIRouter, Request, Header
from app.models.schemas import FormData, ChatRequest, DeployLineRequest
from app.controllers import merchant_controller, chat_controller, line_controller
from typing import Dict, Any

api_router = APIRouter()

@api_router.get("/init_session")
async def init_session():
    return await chat_controller.init_session()

@api_router.post("/generate_prompt")
async def generate_prompt(data: FormData):
    return await merchant_controller.generate_prompt(data)

@api_router.post("/confirm_setup")
async def confirm_setup(data: Dict[str, Any]):
    return await merchant_controller.confirm_setup(data)

@api_router.post("/chat")
async def chat(data: ChatRequest):
    return await chat_controller.chat(data)

@api_router.post("/deploy_line")
async def deploy_line(data: DeployLineRequest):
    return await line_controller.deploy_line(data)

@api_router.post("/line-webhook/{channel_id}")
async def line_webhook(channel_id: str, request: Request, x_line_signature: str = Header(None)):
    return await line_controller.line_webhook(channel_id, request, x_line_signature)
