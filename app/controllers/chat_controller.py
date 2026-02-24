import uuid
from app.models.schemas import ChatRequest
from app.services import agent_service

async def init_session():
    return {"session_id": str(uuid.uuid4())}

async def chat(data: ChatRequest):
    result = await agent_service.run_chat(
        user_message=data.message, 
        line_user_id=data.line_user_id,
        user_name=data.user_name,
        agent_id=data.agent_id,
        session_id=data.session_id,
        source=data.source
    )
    return result
