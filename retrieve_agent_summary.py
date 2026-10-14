"""Retrieve agent name + customer mobile/name + chat summary (READ-ONLY).

Usage:
    python retrieve_agent_summary.py [limit] [status]
    python retrieve_agent_summary.py all [start_page] [limit_per_status]  # master open+pending+resolved

Output (always both):
    data/agent_summary.xlsx  (sheet Agent_Summary)
    data/agent_summary.json  (list of dicts)

Columns:
    conversation_id, customer_name, mobile_number, agent_name,
    conversation_date, english_summary, customer_problem, main_intent,
    customer_message_count, bot_response_count

Read-only: only POST is /api/auth/login, rest GET. No send/reply/delete.
"""
import json
import logging
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

from src import config
from src.wootify_client import WootifyClient
from src.analyzer import analyze

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agent-summary")

SUMMARY_COLS = [
    "conversation_id",
    "customer_name",
    "mobile_number",
    "agent_name",
    "conversation_date",
    "english_summary",
    "customer_problem",
    "main_intent",
    "customer_message_count",
    "bot_response_count",
    # bot-evaluation columns (for assessing how the bot handled the customer)
    "chatbot_understanding",
    "response_quality",
    "customer_sentiment",
    "resolution_status",
    "main_failure",
    "evidence",
    "recommended_improvement",
]

HEADER_MAP = {
    "conversation_id": "Conversation ID",
    "customer_name": "Customer Name",
    "mobile_number": "Mobile Number",
    "agent_name": "Agent Name",
    "conversation_date": "Conversation Date",
    "english_summary": "Chat Summary (English, customer-centric)",
    "customer_problem": "Customer Problem",
    "main_intent": "Main Intent",
    "customer_message_count": "Customer Msg Count",
    "bot_response_count": "Bot Msg Count",
    "chatbot_understanding": "Chatbot Understanding",
    "response_quality": "Response Quality",
    "customer_sentiment": "Customer Sentiment",
    "resolution_status": "Resolution Status",
    "main_failure": "Main Bot Failure",
    "evidence": "Evidence",
    "recommended_improvement": "Recommended Improvement",
}


def run(limit: int = 20, status: str = "open"):
    assert config.READONLY_MODE, "READONLY_MODE must be 1"
    assert config.USERNAME and config.PASSWORD, "Missing credentials in .env"

    client = WootifyClient()
    client.login()

    rows: list[dict] = []
    page = 1
    errors = 0
    while len(rows) < limit:
        data = client.list_conversations(status=status, page=page)
        items = data.get("payload", []) if isinstance(data, dict) else data
        if not items:
            break
        for conv in items:
            if len(rows) >= limit:
                break
            cid = conv.get("id")
            if cid is None:
                continue
            try:
                msgs = client.get_messages(cid)
                if not msgs:
                    continue
                a = analyze(cid, msgs, conv_meta=conv)
                d = a.model_dump()
                rows.append({k: d.get(k, "") for k in SUMMARY_COLS})
                if config.llm_provider() in ("groq", "openrouter"):
                    time.sleep(5)  # stay under free-tier rate limits (backfill-tuned)
            except Exception as e:
                log.error(f"conv {cid} error: {type(e).__name__}: {str(e)[:200]}")
                errors += 1
        page += 1
        if page > 5:  # safety cap, same as src/main.py
            break

    out_xlsx = Path("data/agent_summary.xlsx")
    out_json = Path("data/agent_summary.json")
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(rows, columns=SUMMARY_COLS).rename(columns=HEADER_MAP)
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Agent_Summary", index=False)
        ws = w.sheets["Agent_Summary"]
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    out_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"DONE rows={len(rows)} errors={errors} -> {out_xlsx} + {out_json}")
    return {"rows": len(rows), "errors": errors,
            "xlsx": str(out_xlsx), "json": str(out_json)}


def run_master(statuses=("open", "pending", "resolved"), limit_per_status: int = 25,
               start_page: int = 1, max_pages: int = 20):
    """Master export across statuses into data/agent_summary_all.* (merge by conversation_id,
    incremental saves every 5 rows so timeouts never lose progress).
    Paging: starts at start_page per status, walks up to max_pages (for 1667 pending backfill)."""
    assert config.READONLY_MODE, "READONLY_MODE must be 1"
    client = WootifyClient()
    client.login()
    out_xlsx = Path("data/agent_summary_all.xlsx")
    out_json = Path("data/agent_summary_all.json")
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    merged: dict[int, dict] = {}
    if out_json.exists():
        try:
            for r in json.loads(out_json.read_text(encoding="utf-8")):
                if isinstance(r, dict) and r.get("conversation_id") is not None:
                    merged[r["conversation_id"]] = r
        except Exception:
            pass
    errors = 0

    def _save():
        rows = [merged[k] for k in sorted(merged)]
        # JSON first (never blocked by Excel locks) so progress is never lost.
        # ONE master xlsx only: if locked open in Excel, retry then warn (no copy files).
        out_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        df = pd.DataFrame(rows, columns=SUMMARY_COLS).rename(columns=HEADER_MAP)
        for attempt in range(3):
            try:
                with pd.ExcelWriter(out_xlsx, engine="openpyxl") as w:
                    df.to_excel(w, sheet_name="Agent_Summary_All", index=False)
                    ws = w.sheets["Agent_Summary_All"]
                    ws.freeze_panes = "A2"
                    ws.auto_filter.ref = ws.dimensions
                break
            except PermissionError:
                if attempt < 2:
                    time.sleep(5)
                else:
                    log.warning("master xlsx locked open in Excel - JSON saved, xlsx will rebuild on next run after closing it")

    for status in statuses:
        new_this_status = 0
        page = start_page
        pages_walked = 0
        while new_this_status < limit_per_status and pages_walked < max_pages:
            data = client.list_conversations(status=status, page=page)
            items = data.get("payload", []) if isinstance(data, dict) else data
            if not items:
                break
            for conv in items:
                if new_this_status >= limit_per_status:
                    break
                cid = conv.get("id")
                if cid is None:
                    continue
                if cid in merged:
                    prev = merged[cid]
                    # If already analyzed with LLM, skip
                    if prev.get("main_intent") != "(heuristic - needs LLM review)" and prev.get("chatbot_understanding") not in ("Unclear", ""):
                        continue
                try:
                    msgs = client.get_messages(cid)
                    if not msgs:
                        continue
                    a = analyze(cid, msgs, conv_meta=conv)
                    merged[cid] = {k: a.model_dump().get(k, "") for k in SUMMARY_COLS}
                    new_this_status += 1
                    if len(merged) % 5 == 0:
                        _save()
                        log.info(f"checkpoint saved: {len(merged)} rows")
                    if config.llm_provider() == "groq":
                        time.sleep(5)
                    elif config.llm_provider() == "openrouter":
                        time.sleep(1)
                except Exception as e:
                    log.error(f"conv {cid} error: {type(e).__name__}: {str(e)[:200]}")
                    errors += 1
            page += 1
            pages_walked += 1
            if page > 100:
                break
    _save()
    log.info(f"MASTER DONE rows={len(merged)} errors={errors} -> {out_xlsx} + {out_json}")
    return {"rows": len(merged), "errors": errors,
            "xlsx": str(out_xlsx), "json": str(out_json)}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "all":
        # usage: python retrieve_agent_summary.py all [start_page] [limit_per_status] [statuses csv] [max_pages]
        # e.g. all 1 2000 "open,pending,resolved" 80
        sp = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        lim = int(sys.argv[3]) if len(sys.argv) > 3 else 2000
        sts = tuple(s.strip() for s in sys.argv[4].split(",")) if len(sys.argv) > 4 else ("open", "pending", "resolved")
        mp = int(sys.argv[5]) if len(sys.argv) > 5 else 80
        print(run_master(statuses=sts, start_page=sp, limit_per_status=lim, max_pages=mp))
    else:
        lim = int(sys.argv[1]) if len(sys.argv) > 1 else 20
        st = sys.argv[2] if len(sys.argv) > 2 else "open"
        print(run(limit=lim, status=st))
