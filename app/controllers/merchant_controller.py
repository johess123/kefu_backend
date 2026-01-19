from typing import Dict, Any
from app.models.schemas import FormData
from app.services import prompt_service, agent_service

async def generate_prompt(data: FormData):
    return prompt_service.generate_structure_data(data.dict())

async def confirm_setup(data: Dict[str, Any]):
    config_id = data.get("config_id")
    session_id = data.get("session_id")
    edited_faqs = data.get("faqs")
    edited_triggers = data.get("handoff_triggers")
    
    if not session_id:
        return {"status": "error", "message": "session_id is required."}
        
    cached_config = prompt_service.get_cached_logic(config_id)
    line_user_id = data.get("line_user_id")
    agent_id = data.get("agent_id") # Get agent_id if exists
    
    if not line_user_id:
        return {"status": "error", "message": "line_user_id is required."}
        
    if cached_config:
        if edited_faqs is not None:
            cached_config["faqs"] = edited_faqs
            
        if edited_triggers is not None:
            if edited_triggers:
                cached_config["handoff_logic"] = f"當使用者提到以下任何一項時轉接：{', '.join(edited_triggers)}"
            else:
                cached_config["handoff_logic"] = ""

        new_agent_id = await agent_service.initialize_agent_system(cached_config, line_user_id, agent_id)
        return {"status": "ok", "agent_id": new_agent_id}
    else:
        return {"status": "error", "message": "Configuration cache not found or expired."}
