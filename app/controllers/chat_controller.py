import uuid
from app.models.schemas import ChatRequest
from app.services import agent_service

async def init_session():
    return {"session_id": str(uuid.uuid4())}

async def chat(data: ChatRequest):
    result = await agent_service.run_chat(data.message, data.session_id)
    return result
