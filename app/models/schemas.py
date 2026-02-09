from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

# From main.py
class FAQItem(BaseModel):
    id: Any
    question: str = Field(..., max_length=50)
    answer: str = Field(..., max_length=200)

class FormData(BaseModel):
    brandDescription: str = Field(..., max_length=200)
    websiteUrl: Optional[str] = Field("", max_length=100)
    tone: str
    toneAvoid: Optional[str] = Field("", max_length=50)
    faqs: List[FAQItem]
    handoffTriggers: List[str]
    handoffCustomTrigger: Optional[str] = Field("", max_length=50)
    handoffContactValue: Optional[str] = None
    handoffMethod: Optional[str] = None
    line_user_id: Optional[str] = None
    agent_id: Optional[str] = None

class ChatRequest(BaseModel):
    message: str = Field(..., max_length=100)
    history: List[dict] 
    line_user_id: str
    user_name: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None

class DeployLineRequest(BaseModel):
    agent_id: str
    access_token: str
    channel_secret: str

# From agent_runtime.py
class FAQItemStructured(BaseModel):
    id: Any
    Q: str
    A: Any

class HandoffResultStructured(BaseModel):
    hand_off: bool
    reason: str

class ChatStructuredOutput(BaseModel):
    response_text: str
    related_faq_list: List[FAQItemStructured]
    handoff_result: HandoffResultStructured

# From prompt_generator.py
class MerchantExtraction(BaseModel):
    merchant_name: str = Field(..., max_length=20, description="從商家介紹中提取出的「商家名稱」")
    services: str = Field(..., max_length=200, description="從商家介紹中提取出的「提供的服務或商品內容」")
    handoff_preview: str = Field(..., description="一段給客人的「轉接真人對話預覽」範例語句")
    handoff_logic_summary: str = Field(..., description="具體總結轉接真人的觸發邏輯，僅描述規則，不含指令標籤")

class LoginData(BaseModel):
    userId: str
    name: Optional[str] = None

class Subagent(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    title: str
    name: str
    description: str
    enabled: bool
    created_at: Optional[Any] = None

class GenerateFAQRequest(BaseModel):
    brandDescription: str = Field(..., max_length=200)
    websiteUrl: Optional[str] = Field("", max_length=100)
    line_user_id: Optional[str] = None

class FAQPair(BaseModel):
    q: str
    a: str

class GeneratedFAQs(BaseModel):
    faqs: List[FAQPair]

class OptimizeFAQRequest(BaseModel):
    question: str = Field(..., max_length=50)
    answer: str = Field(..., max_length=200)
    line_user_id: Optional[str] = None
class FAQAnalysisSuggestion(BaseModel):
    id: str
    suggestion: str
    optimized_q: str
    optimized_a: str

class FAQAnalysisReport(BaseModel):
    score: int
    report: str
    suggestions: List[FAQAnalysisSuggestion]

class AnalyzeFAQsRequest(BaseModel):
    faqs: List[FAQItem]
    brandDescription: str = Field(..., max_length=200)
    line_user_id: Optional[str] = None
