from typing import Dict, Any
from app.models.schemas import FormData
from app.services import prompt_service, agent_service

async def generate_prompt(data: FormData):
    # 手動驗證長度 (雙重保障)
    if len(data.brandDescription) > 200:
        return {"error": "品牌描述超過 200 字"}
    if data.websiteUrl and len(data.websiteUrl) > 100:
        return {"error": "網站連結超過 100 字"}
    if data.toneAvoid and len(data.toneAvoid) > 50:
        return {"error": "避免語氣超過 50 字"}
    if data.handoffCustomTrigger and len(data.handoffCustomTrigger) > 50:
        return {"error": "自訂轉接觸發詞超過 50 字"}

    # 將 Pydantic 模型轉換為字典，以便 prompt_service 使用 .get()
    dict_data = data.model_dump()
    return await prompt_service.generate_structure_data(dict_data)

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
            # 加入後端驗證
            if not edited_faqs:
                return {"status": "error", "message": "請至少提供一組 FAQ"}
            if len(edited_faqs) > 20:
                return {"status": "error", "message": "FAQ 組數上限為 20 組"}
            for faq in edited_faqs:
                q = faq.get("question", "").strip()
                a = faq.get("answer", "").strip()
                if not q or not a:
                    return {"status": "error", "message": "所有 FAQ 的問題與回答皆為必填"}
                if len(q) > 50 or len(a) > 200:
                    return {"status": "error", "message": "內容超過字數限制 (問題 50 字，回答 200 字)"}
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

async def generate_faqs(data: Any):
    brand_description = data.brandDescription
    website_url = data.websiteUrl
    line_user_id = data.line_user_id

    if len(brand_description) > 200:
        return {"error": "品牌描述超過 200 字"}
    if website_url and len(website_url) > 100:
        return {"error": "網站連結超過 100 字"}

    return await prompt_service.generate_faqs(brand_description, website_url, line_user_id)

async def optimize_faq(data: Any):
    question = data.question
    answer = data.answer
    if not question or not question.strip() or not answer or not answer.strip():
        return {"error": "問題與回答均為必填，才能進行優化"}
    if len(question.strip()) > 50 or len(answer.strip()) > 200:
        return {"error": "內容超過字數限制 (問題 50 字，回答 200 字)"}
    
    line_user_id = data.line_user_id
    return await prompt_service.optimize_faq(question, answer, line_user_id)

async def analyze_faqs(data: Any):
    brand_description = data.brandDescription
    faqs = [f.model_dump() for f in data.faqs]
    
    if len(brand_description) > 200:
        return {"error": "品牌描述超過 200 字"}
    
    if not faqs:
        return {"error": "請至少提供一組 FAQ"}
    
    if len(faqs) > 20:
        return {"error": "FAQ 組數上限為 20 組"}
    
    for faq in faqs:
        q = faq.get("question", "").strip()
        a = faq.get("answer", "").strip()
        if not q or not a:
            return {"error": "所有 FAQ 的問題與回答皆為必填，請檢查是否有未填寫完整的組別"}
        if len(q) > 50 or len(a) > 200:
            return {"error": "部分內容超過字數限制 (問題 50 字，回答 200 字)"}

    line_user_id = data.line_user_id
    return await prompt_service.analyze_faqs(brand_description, faqs, line_user_id)
