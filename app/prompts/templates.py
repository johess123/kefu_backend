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

FAQ_GENERATION_PROMPT = """ # Instruction
- 你是一位專業的行銷與客服顧問。
- 你會拿到商家提供的資訊（名稱、服務、網站內容）
- 你的任務是依此資訊擬定 5 組高品質的常見問題（FAQ）。

# Constraint
- 問題(Q)必須是顧客真的會問的。
- 回答(A)必須語氣親切、資訊正確，且符合商家提供的服務範圍。
- 輸出格式必須是 JSON 格式，包含一個 list，每個項目有 q 和 a 兩個欄位。

# Input
- 商家名稱與服務：{merchant_info}
- 網站內容：{website_text}
"""

FAQ_OPTIMIZE_PROMPT = """# Instruction
- 你是一位專業的客服顧問。
- 你會拿到一個常見問題（Q）與其回覆內容（A）。
- 你的任務是優化這組 Q&A，讓問題更清晰、描述更精準，且回覆更具專業感與親和力。
- 請直接回覆優化後的 JSON 結果。

# Input
- Q: {question}
- A: {answer}
"""

FAQ_ANALYSIS_PROMPT = """# Instruction
- 你是一位專業的 AI 客服健檢顧問。
- 你會拿到商家的品牌描述以及他們目前擬定的 FAQ 清單。
- 你的任務是針對這份 FAQ 清單進行「智慧健檢」：
  1. 給出整體的健檢得分 (0-100)。
  2. 撰寫一段整體的建議報告 (report)。
  3. 針對每一組 FAQ，如果可以更好，請提供具體的建議 (suggestion) 以及優化後的版本 (optimized_q, optimized_a)。

# 評分標準：
- 專業度：回答是否口語化、是否能代表品牌形象。
- 資訊量：回答是否解決了潛在顧客的疑慮。
- 關鍵字精確度：問題是否容易被搜尋到。
- 完整性：是否涵蓋了品牌描述中的核心服務。

# Output Format (JSON):
{{
  "score": 85,
  "report": "整體內容完整且服務導向清晰，但在標題專業度、配送關鍵字精確度以及內文繁簡體一致性上仍有改進空間。建議將口語化的問題調整為標準化的知識庫標題，以提升檢索效率。",
  "suggestions": [
    {{
      "id": "faq_id_1",
      "suggestion": "建議將口語化的詢問改為結構化的功能性標題，方便用戶快速辨識內容主題。",
      "optimized_q": "如何辦理退貨與鑑賞期規範說明",
      "optimized_a": "沒問題！我們提供 30 天鑑賞期。只要商品保持全新未拆封，皆可申請退貨。請聯繫客服為您安排。"
    }}
  ]
}}

# Input:
- 品牌描述: {brand_description}
- FAQ 清單: {faqs_json}
"""
