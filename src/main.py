"""Main - incremental, deduped, resumable, scheduled. Read-only."""
import hashlib, logging
from pathlib import Path
from . import config, storage
from .wootify_client import WootifyClient
from .analyzer import analyze
from .excel_export import export

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler("logs/run.log", encoding="utf-8")])
log = logging.getLogger("wootify.main")

def speaker_of(m):
    return "customer" if m.get("message_type")==0 else "bot" if m.get("message_type")==1 else "system"

def content_hash(msgs):
    h = hashlib.sha256()
    for m in sorted(msgs, key=lambda x: x.get("id",0)):
        h.update(f"{m.get('id')}|{m.get('content') or ''}|".encode("utf-8", "ignore"))
    return h.hexdigest()[:16]

def run(limit=10, status="open"):
    assert config.READONLY_MODE, "READONLY_MODE must be 1"
    assert config.USERNAME and config.PASSWORD, "Missing credentials in .env"
    cx = storage.connect(config.DB_PATH)
    run_id = cx.execute("INSERT INTO runs DEFAULT VALUES").lastrowid
    cx.commit()
    client = WootifyClient()
    client.login()
    processed = skipped = errors = 0
    analyses, raw_all = [], []
    page = 1
    while len(analyses) < limit:
        data = client.list_conversations(status=status, page=page)
        items = data.get("payload", []) if isinstance(data, dict) else data
        if not items: break
        for conv in items:
            cid = conv.get("id")
            if cid is None or len(analyses) >= limit: continue
            try:
                msgs = client.get_messages(cid)
                if not msgs:
                    skipped += 1; continue
                last_id = max(m.get("id",0) for m in msgs)
                h = content_hash(msgs)
                prev = storage.get_state(cx, cid)
                if prev and prev[0]==last_id and prev[2]==h:
                    skipped += 1; continue  # already processed, no new messages
                a = analyze(cid, msgs, conv_meta=conv)
                analyses.append(a)
                for m in sorted(msgs, key=lambda x: x.get("id",0)):
                    if m.get("content"):
                        raw_all.append({"conversation_id":cid,"created_at":m.get("created_at"),"speaker":speaker_of(m),"content":m.get("content")})
                storage.save_state(cx, cid, last_id, len(msgs), h)
                processed += 1
            except Exception as e:
                log.error(f"conv {cid} error: {type(e).__name__}: {str(e)[:200]}")
                errors += 1
        # pagination
        meta = data.get("meta", {}) if isinstance(data, dict) else {}
        page += 1
        if page > 5: break  # safety cap for PoC; remove for full backfill
    if analyses:
        export(analyses, raw_all, config.EXCEL_PATH)
        log.info(f"Excel -> {config.EXCEL_PATH} rows={len(analyses)}")
    cx.execute("UPDATE runs SET processed=?, skipped=?, errors=? WHERE id=?", (processed, skipped, errors, run_id))
    cx.commit()
    log.info(f"DONE processed={processed} skipped={skipped} errors={errors}")
    return {"processed":processed,"skipped":skipped,"errors":errors,"excel":config.EXCEL_PATH if analyses else None}

if __name__ == "__main__":
    import sys
    lim = int(sys.argv[1]) if len(sys.argv)>1 else 10
    print(run(limit=lim))
