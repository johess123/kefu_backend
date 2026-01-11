import uuid
from typing import Dict, Any
from google import genai
from google.genai import types
from app.core.config import settings
from app.models.schemas import MerchantExtraction
from app.prompts.templates import EXTRACTION_PROMPT

# 使用 settings.GOOGLE_API_KEY
client = genai.Client(api_key=settings.GOOGLE_API_KEY)

# 暫存原始資料與提取結果
PENDING_CONFIG_CACHE = {}

def build_user_summary(form_data: dict) -> str:
    return f"""
    商家介紹原始文字: {form_data.get('brandDescription')}
    轉真人規則:
    預設觸發: {form_data.get('handoffTriggers')}
    自定義觸發: {form_data.get('handoffCustomTrigger')}
    聯絡方式: {form_data.get('handoffContactValue')} (方式: {form_data.get('handoffMethod')})
    """

def generate_structure_data(form_data: dict) -> dict:
    user_summary = build_user_summary(form_data)
    
    try:
        response = client.models.generate_content(
            model=settings.GENERAL_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=EXTRACTION_PROMPT,
                response_mime_type="application/json",
                response_schema=MerchantExtraction
            ),
            contents=[
                types.Part.from_text(text="這裡是商家的原始資料：\n" + user_summary)
            ]
        )
        
        extraction = MerchantExtraction.model_validate_json(response.text)
        config_id = str(uuid.uuid4())
        
        PENDING_CONFIG_CACHE[config_id] = {
            "merchant_name": extraction.merchant_name,
            "services": extraction.services,
            "handoff_logic": extraction.handoff_logic_summary,
            "faqs": form_data.get("faqs", []),
            "tone": form_data.get("tone", "親切"),
            "tone_avoid": form_data.get("toneAvoid", ""),
        }
        
        return {
            "config_id": config_id,
            "merchant_name": extraction.merchant_name,
            "services": extraction.services,
            "tone": form_data.get("tone"),
            "tone_avoid": form_data.get("toneAvoid", ""),
            "handoff_triggers": list(dict.fromkeys(form_data.get('handoffTriggers', []) + ([form_data.get('handoffCustomTrigger')] if form_data.get('handoffCustomTrigger') else []))),
            "handoff_preview": extraction.handoff_preview,
            "faqs": form_data.get("faqs", [])
        }
        
    except Exception as e:
        print(f"提取失敗: {e}")
        return {"error": str(e)}

def get_cached_logic(config_id: str) -> dict:
    return PENDING_CONFIG_CACHE.get(config_id)
