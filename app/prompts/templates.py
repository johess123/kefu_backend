EXTRACTION_PROMPT = """# Instruction
- 你是一位專業的資料提取專家。
- 請從下方的「商家資料」中提取出結構化資訊。

- 提取要求
1. "merchant_name": 商家名稱，字數必須 **20 個字以內**。
2. "services": 詳細列出提供的服務或商品內容，字數需 **100 到 150 個字**。
3. "handoff_preview": 根據商家的語氣，撰寫一段觸發轉接真人時的回覆範例。如果輸入的轉接規則為空，則回傳 "本店不提供轉接真人客服服務"。
4. "handoff_logic_summary": 根據輸入的轉接規則，總結成一段清晰的邏輯描述，供後續 AI 判斷使用。如果輸入的轉接規則為空，則回傳空字串。

# 注意事項
- 嚴格控制字數，不可超出或低於規定範圍。
- 請使用「正體中文 (繁體中文)」回傳。
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
4. Each Question (Q) must be between 20 and 40 Chinese characters.
5. Each Answer (A) must be between 100 and 150 Chinese characters.
6. Strictly control character count; do not exceed or fall below the specified ranges.
7. RETURN STRICTLY JSON in the specified array format.
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
6. Each Question (Q) must be between 20 and 40 Chinese characters.
7. Each Answer (A) must be between 100 and 150 Chinese characters.
8. Strictly control character count; do not exceed or fall below the specified ranges.
9. RETURN STRICTLY JSON in the specified array format.
"""

FAQ_OPTIMIZE_PROMPT = """# Instruction
- You are a professional customer service copywriter (Traditional Chinese, Taiwan).
- Please rewrite the following FAQ pair to make it clearer, more polite, and professional.

# Input
- Q: {question}
- A: {answer}

# Requirements
1. Ensure the Question sounds like a natural customer query, with 20 to 40 Chinese characters.
2. Ensure the Answer addresses the question directly, politely, and helpfully, with 100 to 150 Chinese characters.
3. Maintain the original meaning.
4. The output must be in Traditional Chinese (Taiwan).
5. Strictly control character count; do not exceed or fall below the specified ranges.
6. Return strictly JSON.
"""

FAQ_ANALYSIS_PROMPT = """# Instruction
- 你是一位專業的客服知識庫內容審核專家。
- 分析使用者提供的 FAQ 列表。
- FAQs: {faqs_json}
- 你的任務是針對每個欄位 (Question 或 Answer) 提出具體改進建議。

# Criteria
- DUPLICATE (重複): 如果兩個問題太相似，建議重新改寫其中一個，使其與眾不同，或標註重複。
- UNCLEAR (不清楚): 如果問題過於模糊（例如「多少？」），請改寫成具體問題（例如「基本方案費用是多少？」）。
- IMPROVEMENT (改進): 如果文字過長、語氣不禮貌或語法錯誤，提供已優化的版本。
- CHARACTER LIMIT (字數限制): 每個 Question 必須為 20 到 40 個中文字；每個 Answer 必須為 100 到 150 個中文字。

# Constraint
- 每個問題或答案的改進，都必須提供建議內容作為可直接使用的替代文字。
- 明確標註需修改的欄位 ('question' 或 'answer')。
- 嚴格控制字數範圍，不可超出或低於規定。
- 嚴格以符合 schema 的 JSON 格式輸出。

# Language
- 以繁體中文產生回覆
"""
