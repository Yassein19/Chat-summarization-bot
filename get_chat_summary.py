"""Get one-chat summary by ID (READ-ONLY): customer name + mobile + agent + one-sentence whole-chat summary.

Usage:
    python get_chat_summary.py 1179
    python get_chat_summary.py 1179 pending   # status hint for meta lookup (optional)

Output:
    - prints single row to console (ascii-safe)
    - appends/updates data/chat_summaries.json + data/chat_summaries.xlsx (one row per chat ID)

Read-only: only POST is /api/auth/login, rest GET.
"""
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from src import config
from src.wootify_client import WootifyClient
from src.analyzer import analyze

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("chat-summary")

COLS = ["conversation_id", "customer_name", "mobile_number", "agent_name",
        "conversation_date", "english_summary"]
HEADERS = {"conversation_id": "ID", "customer_name": "Customer Name",
           "mobile_number": "Mobile Number", "agent_name": "Agent Name",
           "conversation_date": "Date", "english_summary": "Summary (one sentence, whole chat)"}


def get_one(conv_id: int, status_hint: str = "all"):
    assert config.READONLY_MODE, "READONLY_MODE must be 1"
    client = WootifyClient()
    client.login()
    # conv_meta lookup (for phone/name fallback) - try hint then open/pending
    conv_meta = None
    for st in [status_hint, "all", "pending", "open", "resolved"]:
        try:
            d = client.list_conversations(status=st, page=1)
            items = d.get("payload", []) if isinstance(d, dict) else d
            for c in items:
                if c.get("id") == conv_id:
                    conv_meta = c
                    break
            if conv_meta:
                break
        except Exception:
            continue
    msgs = client.get_messages(conv_id)
    a = analyze(conv_id, msgs, conv_meta=conv_meta)
    d = a.model_dump()
    return {k: d.get(k, "") for k in COLS}


def save_row(row: dict):
    import time
    jpath = Path("data/chat_summaries.json")
    xpath = Path("data/chat_summaries.xlsx")
    rows: list[dict] = []
    if jpath.exists():
        try:
            rows = json.loads(jpath.read_text(encoding="utf-8"))
        except Exception:
            rows = []
    rows = [r for r in rows if r.get("conversation_id") != row["conversation_id"]]
    rows.append(row)
    jpath.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    df = pd.DataFrame(rows, columns=COLS).rename(columns=HEADERS)
    for attempt in range(3):
        try:
            with pd.ExcelWriter(xpath, engine="openpyxl") as w:
                df.to_excel(w, sheet_name="Summaries", index=False)
                ws = w.sheets["Summaries"]
                ws.freeze_panes = "A2"
                ws.auto_filter.ref = ws.dimensions
            break
        except PermissionError:
            if attempt < 2:
                time.sleep(5)
            else:
                log.warning("chat_summaries.xlsx locked open in Excel - JSON saved, close Excel to rebuild xlsx")
    return jpath, xpath


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python get_chat_summary.py <conversation_id> [status_hint]")
        sys.exit(2)
    cid = int(sys.argv[1])
    hint = sys.argv[2] if len(sys.argv) > 2 else "all"
    row = get_one(cid, hint)
    jp, xp = save_row(row)
    # ascii-safe console output (Arabic goes to files, not console)
    print(f"ID=#{row['conversation_id']} mobile={row['mobile_number']} agent={row['agent_name']} date={row['conversation_date']}")
    print(f"SUMMARY: {row['english_summary']}")
    print(f"Saved -> {xp} + {jp} (customer name inside files, console cannot show Arabic)")
