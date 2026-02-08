EXTRACTION_PROMPT = """
你是一位專業的資料提取專家。
請從下方的「商家資料」中提取出結構化資訊。

提取要求：
1. "merchant_name": 商家名稱。
2. "services": 詳細列出提供的服務或商品內容。
3. "handoff_preview": 根據商家的語氣，撰寫一段觸發轉接真人時的回覆範例。如果輸入的轉接規則為空，則回傳 "本店不提供轉接真人客服服務"。
4. "handoff_logic_summary": 根據輸入的轉接規則，總結成一段清晰的邏輯描述，供後續 AI 判斷使用。如果輸入的轉接規則為空，則回傳空字串。

請使用「正體中文 (繁體中文)」回傳。
"""

FAQ_INSTRUCTION_HEADER = """# Instruction
- 你是一個專業的 FAQ 智能助手。
- 你會拿到使用者的問題與 FAQ 列表。
- 你的任務是以 list[dict] 格式回傳所有與使用者問題相關的 FAQ 項目。
- 若沒有與使用者問題相關的 FAQ，則回傳空的 list[]。

# Example
相關的 FAQ 項目: [{"id": abc123, "Q": ..., "A": ...}, ...]

# FAQ"""

SUBAGENT_INSTRUCTION = """\n\n- 若問題超出能力範圍時回答"此 tool 無法回答該問題，改用別種 tool"。\n"""

HANDOFF_INSTRUCTION_HEADER = """# Instruction
- 你是一個專業的轉接真人客服 agent。
- 你會拿到使用者的問題與轉接規則。
- 你的任務是判斷使用者問題是否需轉接真人客服，並用 dict 格式回傳判斷結果與原因。
- 若判斷需轉接真人客服，就呼叫 call_human_support tool 執行轉接作業。

# Output
{"hand_off": False, "reason": "使用者問題不符合設定的轉接真人客服條件"}

# 轉接規則"""

HANDOFF_DISABLED_INSTRUCTION = """# Instruction
- 你不提供轉接真人客服服務
- 你也不能使用 call_human_support tool
- 當你收到使用者問題，直接回覆以下 dict:
{"hand_off": False, "reason": "不提供轉接真人客服服務"}"""

FAQ_GENERATION_PROMPT = """ # Task
- Generate 5 to 7 common customer service Q&A pairs (FAQs) for a business described as: {merchant_info}.

Instructions:
1. Infer potential customer questions based solely on the brand description.
2. The tone should be polite and helpful.
3. The output must be in Traditional Chinese (Taiwan).
4. RETURN STRICTLY JSON in the specified array format.
"""

FAQ_GENERATION_WITH_URL_PROMPT = """# Task
- Create a list of 5 to 7 customer service FAQs.
# Input
- Target Website: {website_text}
- Business Description: {merchant_info}

# Instructions
1. Look for specific details in the Target Website like shipping policies, pricing, business hours, return policies, or service menus.
2. Generate Q&A pairs based on the ACTUAL information found on the website. 
3. If the website information is insufficient, use the **Business Description** to infer reasonable questions.
4. The tone should be polite and helpful.
5. The output must be in Traditional Chinese (Taiwan).
6. RETURN STRICTLY JSON in the specified array format.
"""

FAQ_OPTIMIZE_PROMPT = """# Instruction
- You are a professional customer service copywriter (Traditional Chinese, Taiwan).
- Please rewrite the following FAQ pair to make it clearer, more polite, and professional.

# Input
- Q: {question}
- A: {answer}

# Requirements
1. Ensure the Question sounds like a natural customer query.
2. Ensure the Answer addresses the question directly, politely, and helpfully.
3. Maintain the original meaning.
4. The output must be in Traditional Chinese (Taiwan).
5. Return strictly JSON.
"""

FAQ_ANALYSIS_PROMPT = """# Instruction
- You are an expert content auditor for customer service knowledge bases (Traditional Chinese).
- Analyze the following list of FAQs provided by a user.
- FAQs: {faqs_json}
- Your task is to identify specific improvements for individual fields (Question or Answer).

# Criteria:
- DUPLICATE: If two questions are too similar, suggest rephrasing one to be distinct, or mark it.
- UNCLEAR: If a question is vague (e.g., "How much?"), rewrite it to be specific (e.g., "How much does the basic plan cost?").
- IMPROVEMENT: If text is too long, rude, or grammatically incorrect, provide a polished version.

# IMPORTANT: 
- For every issue found, you MUST provide 'suggestedText' which is the ready-to-use replacement.
- Specify exactly which 'field' ('question' or 'answer') needs the change.

# Language
- Traditional Chinese (Taiwan)

Return JSON strictly matching the schema.
"""
