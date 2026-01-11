from google.adk.agents import LlmAgent
from google.adk.tools import agent_tool
from app.core.config import settings

def call_human_support(query: str) -> dict:
    """
    轉接真人客服
    args:
        query: 使用者問題
    return:
        {"text": "已轉接真人客服"}
    """
    print("已轉接真人客服")
    return {"text": "已轉接真人客服"}

# Note: instructions are injected dynamically via session state
faq_agent = LlmAgent(
    name="faq_expert", 
    model=settings.AGENT_MODEL, 
    instruction="{faq_instruction}",
    description="FAQ 智能助手"
)

handoff_agent = LlmAgent(
    name="handoff_expert", 
    model=settings.AGENT_MODEL, 
    instruction="{handoff_instruction}",
    description="轉接真人客服智能助手",
    tools=[call_human_support]
)

faq_tool = agent_tool.AgentTool(agent=faq_agent)
handoff_tool = agent_tool.AgentTool(agent=handoff_agent)

main_agent = LlmAgent(
    name="main_router",
    model=settings.AGENT_MODEL,
    instruction="{router_instruction}",
    description="負責協調所有客服流程、決定要呼叫哪些 tool，並彙整各個 tool 的回傳結果後產出統一的回覆",
    tools=[faq_tool, handoff_tool]
)
