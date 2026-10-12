# Wootify Conversation Analyzer (strict read-only)

Read-only bot for https://www.wootify.online/conversations - extracts customer chats (Arabic/Egyptian), analyzes chatbot behavior, exports Excel.

## Verified (not assumed)
- Login: `POST https://chatwoot-sending-templates-production.up.railway.app/api/auth/login` with email+password -> `access_token`
- List: `GET /api/8/chatwoot-configs/7/conversations?status=open&page=N` -> `{payload:[{id,messages,...}], meta:{all_count,unassigned_count}}`
- Thread: `GET /api/8/chatwoot-configs/7/conversations/{id}/messages` -> `{payload:[{id,content,message_type,sender,created_at}]}`
  - `message_type 0`=customer, `1`=bot/agent (`axis-bot`), `2`=activity. Inbox `112955` = AxisPay WhatsApp.
- UI has 15 Open, 4 Unassigned. No official Wootify API docs; backend above is the de-facto API.

## Read-only guarantees
- `src/config.py:assert_readonly` blocks all POST/PUT/PATCH/DELETE except `/api/auth/login`.
- `READONLY_MODE=1` in `.env`. No send/reply/delete code exists.
- Secrets in `.env` only (gitignored), tokens redacted in logs.

## Run
```
pip install -r requirements.txt
python -m src.main 20
# output: data/wootify_analysis.xlsx (Analysis + Raw_Arabic), data/wootify_state.db, logs/run.log
```
Reruns skip unchanged IDs (SQLite hash on last_message_id+content). New messages trigger re-analysis. No duplicates.

## Full LLM analysis
Heuristic baseline runs without keys. For Egyptian-Arabic -> English quality:
```
# .env
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```
Only then is transcript sent to LLM; otherwise no customer data leaves the machine.

## Schedule daily (Windows)
Task Scheduler -> Create Task -> Trigger Daily -> Action:
```
Program: python
Args: -m src.main 50
Start in: C:\Users\ykamel\wootify-analyzer
```

## Test
- `python probe_thread.py` - verifies login + list (read-only)
- `python -m src.main 5` twice - second run should show `skipped=5`
- Open `data/wootify_analysis.xlsx` in Excel/Sheets, check Raw_Arabic audit.
