"""Excel export: Analysis sheet + Raw_Arabic audit sheet."""
import pandas as pd
from pathlib import Path

COLS = ["conversation_id","conversation_date","customer_name","mobile_number","agent_name","customer_message_count","bot_response_count",
 "main_intent","customer_problem","english_summary","chatbot_understanding","response_quality",
 "repetition_detected","incorrect_irrelevant","customer_sentiment","resolution_status",
 "main_failure","evidence","recommended_improvement"]

HEADER_MAP = {"conversation_id":"Conversation ID","conversation_date":"Conversation Date",
 "customer_name":"Customer Name",
 "mobile_number":"Mobile Number","agent_name":"Agent Name",
 "customer_message_count":"Customer Message Count","bot_response_count":"Bot Response Count",
 "main_intent":"Customer's Main Intent","customer_problem":"Customer's Problem",
 "english_summary":"English Conversation Summary","chatbot_understanding":"Chatbot Understanding",
 "response_quality":"Response Quality","repetition_detected":"Repetition Detected",
 "incorrect_irrelevant":"Incorrect or Irrelevant Responses","customer_sentiment":"Customer Sentiment",
 "resolution_status":"Resolution Status","main_failure":"Main Chatbot Failure",
 "evidence":"Evidence From Conversation","recommended_improvement":"Recommended Improvement"}

def export(analyses: list, raw_messages: list, path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([a.model_dump() for a in analyses])
    for c in COLS:
        if c not in df.columns: df[c] = ""
    df = df[COLS].rename(columns=HEADER_MAP)
    raw = pd.DataFrame(raw_messages, columns=["conversation_id","created_at","speaker","content"])
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Analysis", index=False)
        raw.to_excel(w, sheet_name="Raw_Arabic", index=False)
        for ws in (w.sheets["Analysis"], w.sheets["Raw_Arabic"]):
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
    return path
