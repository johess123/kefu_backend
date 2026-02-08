import uuid
from typing import Dict, Any, Optional
from google import genai
from google.genai import types
from app.core.config import settings
from app.models.schemas import MerchantExtraction, GeneratedFAQs, FAQPair, FAQAnalysisReport
from app.prompts.templates import EXTRACTION_PROMPT, FAQ_GENERATION_PROMPT, FAQ_GENERATION_WITH_URL_PROMPT, FAQ_OPTIMIZE_PROMPT, FAQ_ANALYSIS_PROMPT
from app.core.database import used_token_collection
from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI_TZ = ZoneInfo("Asia/Taipei")

# 使用 settings.GOOGLE_API_KEY
client = genai.Client(api_key=settings.GOOGLE_API_KEY)

# 暫存原始資料與提取結果
PENDING_CONFIG_CACHE = {}

def build_user_summary(form_data: dict) -> str:
    return f"""
    商家介紹原始文字: {form_data.get('brandDescription')}
    網站連結: {form_data.get('websiteUrl', '未提供')}
    轉真人規則:
    預設觸發: {form_data.get('handoffTriggers')}
    自定義觸發: {form_data.get('handoffCustomTrigger')}
    聯絡方式: {form_data.get('handoffContactValue')} (方式: {form_data.get('handoffMethod')})
    """

async def generate_structure_data(form_data: dict) -> dict:
    user_summary = build_user_summary(form_data)
    
    try:
        response = await client.aio.models.generate_content(
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
            "website_url": form_data.get("websiteUrl", ""),
            "handoff_logic": extraction.handoff_logic_summary,
            "faqs": form_data.get("faqs", []),
            "tone": form_data.get("tone", "親切"),
            "tone_avoid": form_data.get("toneAvoid", ""),
        }

        usage = response.usage_metadata
        input_token=usage.prompt_token_count
        output_token=usage.candidates_token_count
        thought_token=usage.thoughts_token_count or 0
        tool_token=usage.tool_use_prompt_token_count or 0
        
        await used_token_collection.insert_one({
            "chat_id": None,
            "admin_id": form_data.get("line_user_id"),
            "agent_id": form_data.get("agent_id"),
            "subagent_id": None,
            "session_id": None,
            "model": settings.GENERAL_MODEL,
            "usage_type": "解析表單",
            "usage": {
                "input_token": input_token,
                "output_token": output_token,
                "tool_token": tool_token,
                "thought_token": thought_token,
                "total_token": input_token + output_token + thought_token
            },
            "created_at": datetime.now(TAIPEI_TZ),
            "input": user_summary,
            "output": response.text
        })
        return {
            "config_id": config_id,
            "merchant_name": extraction.merchant_name,
            "services": extraction.services,
            "website_url": form_data.get("websiteUrl", ""),
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

async def generate_faqs(brand_description: str, website_url: str, line_user_id: Optional[str] = None) -> dict:
    try:
        website_text = "未提供"
        if website_url:
            print("website_url", website_url)
            website_response = await client.aio.models.generate_content(
                model=settings.GENERAL_MODEL,
                contents=[types.Part(text=f"完整提取並回傳這個 url 的所有原始內容文字: {website_url}")],
                config=types.GenerateContentConfig(
                    tools=[types.Tool(url_context={})],
                    temperature=0.1,
                )
            )
            website_text = website_response.text
            print("website_text", website_text)

            # 記錄爬取網頁的 Token 消耗
            w_usage = website_response.usage_metadata
            w_input = w_usage.prompt_token_count
            w_output = w_usage.candidates_token_count
            w_thought = w_usage.thoughts_token_count or 0
            w_tool = w_usage.tool_use_prompt_token_count or 0
            
            await used_token_collection.insert_one({
                "chat_id": None,
                "admin_id": line_user_id,
                "agent_id": None,
                "subagent_id": None,
                "session_id": None,
                "model": settings.GENERAL_MODEL,
                "usage_type": "爬取商家網站",
                "usage": {
                    "input_token": w_input,
                    "output_token": w_output,
                    "tool_token": w_tool,
                    "thought_token": w_thought,
                    "total_token": w_input + w_output + w_tool + w_thought
                },
                "created_at": datetime.now(TAIPEI_TZ),
                "input": f"完整提取並回傳這個 url 的所有原始內容文字: URL: {website_url}",
                "output": website_response.text
            })

            prompt = FAQ_GENERATION_WITH_URL_PROMPT.format(
                merchant_info=brand_description,
                website_text=website_text
            )
        else:
            prompt = FAQ_GENERATION_PROMPT.format(
                merchant_info=brand_description
            )
        
        response = await client.aio.models.generate_content(
            model=settings.GENERAL_MODEL,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeneratedFAQs
            ),
            contents=[types.Part.from_text(text=prompt)]
        )
        
        # 記錄生成 FAQ 的 Token 消耗
        f_usage = response.usage_metadata
        f_input = f_usage.prompt_token_count
        f_output = f_usage.candidates_token_count
        f_thought = f_usage.thoughts_token_count or 0
        f_tool = f_usage.tool_use_prompt_token_count or 0
        
        await used_token_collection.insert_one({
            "chat_id": None,
            "admin_id": line_user_id,
            "agent_id": None,
            "subagent_id": None,
            "session_id": None,
            "model": settings.GENERAL_MODEL,
            "usage_type": "生成 FAQ",
            "usage": {
                "input_token": f_input,
                "output_token": f_output,
                "tool_token": f_tool,
                "thought_token": f_thought,
                "total_token": f_input + f_output + f_tool + f_thought
            },
            "created_at": datetime.now(TAIPEI_TZ),
            "input": prompt,
            "output": response.text
        })

        return GeneratedFAQs.model_validate_json(response.text).model_dump()
    except Exception as e:
        print(f"FAQ 生成失敗: {e}")
        return {"error": str(e)}

async def optimize_faq(question: str, answer: str, line_user_id: Optional[str] = None) -> dict:
    try:
        prompt = FAQ_OPTIMIZE_PROMPT.format(
            question=question,
            answer=answer
        )
        
        response = await client.aio.models.generate_content(
            model=settings.GENERAL_MODEL,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=FAQPair
            ),
            contents=[types.Part.from_text(text=prompt)]
        )
        
        # 記錄優化 FAQ 的 Token 消耗
        usage = response.usage_metadata
        u_input = usage.prompt_token_count
        u_output = usage.candidates_token_count
        u_thought = usage.thoughts_token_count or 0
        u_tool = usage.tool_use_prompt_token_count or 0
        
        await used_token_collection.insert_one({
            "chat_id": None,
            "admin_id": line_user_id,
            "agent_id": None,
            "subagent_id": None,
            "session_id": None,
            "model": settings.GENERAL_MODEL,
            "usage_type": "優化 FAQ",
            "usage": {
                "input_token": u_input,
                "output_token": u_output,
                "tool_token": u_tool,
                "thought_token": u_thought,
                "total_token": u_input + u_output + u_tool + u_thought
            },
            "created_at": datetime.now(TAIPEI_TZ),
            "input": prompt,
            "output": response.text
        })

        return FAQPair.model_validate_json(response.text).model_dump()
    except Exception as e:
        print(f"FAQ 優化失敗: {e}")
        return {"error": str(e)}

async def analyze_faqs(brand_description: str, faqs: list, line_user_id: Optional[str] = None) -> dict:
    try:
        import json
        faqs_json = json.dumps([{"id": f["id"], "q": f["question"], "a": f["answer"]} for f in faqs], ensure_ascii=False)
        
        prompt = FAQ_ANALYSIS_PROMPT.format(
            brand_description=brand_description,
            faqs_json=faqs_json
        )
        
        response = await client.aio.models.generate_content(
            model=settings.GENERAL_MODEL,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=FAQAnalysisReport
            ),
            contents=[types.Part.from_text(text=prompt)]
        )
        
        # 記錄健檢 FAQ 的 Token 消耗
        usage = response.usage_metadata
        a_input = usage.prompt_token_count
        a_output = usage.candidates_token_count
        a_thought = usage.thoughts_token_count or 0
        a_tool = usage.tool_use_prompt_token_count or 0
        
        await used_token_collection.insert_one({
            "chat_id": None,
            "admin_id": line_user_id,
            "agent_id": None,
            "subagent_id": None,
            "session_id": None,
            "model": settings.GENERAL_MODEL,
            "usage_type": "AI 健檢 FAQ",
            "usage": {
                "input_token": a_input,
                "output_token": a_output,
                "tool_token": a_tool,
                "thought_token": a_thought,
                "total_token": a_input + a_output + a_tool + a_thought
            },
            "created_at": datetime.now(TAIPEI_TZ),
            "input": prompt,
            "output": response.text
        })
        
        return FAQAnalysisReport.model_validate_json(response.text).model_dump()
    except Exception as e:
        print(f"FAQ 健檢失敗: {e}")
        return {"error": str(e)}
