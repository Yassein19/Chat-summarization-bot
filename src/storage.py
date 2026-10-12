"""SQLite state - dedup + incremental + resume."""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed (
  conversation_id INTEGER PRIMARY KEY,
  last_message_id INTEGER,
  message_count INTEGER,
  content_hash TEXT,
  status TEXT DEFAULT 'done',
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT DEFAULT (datetime('now')),
  processed INTEGER DEFAULT 0,
  skipped INTEGER DEFAULT 0,
  errors INTEGER DEFAULT 0
);
"""

def connect(path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(path)
    cx.executescript(SCHEMA)
    return cx

def get_state(cx, conv_id: int):
    row = cx.execute("SELECT last_message_id, message_count, content_hash FROM processed WHERE conversation_id=?", (conv_id,)).fetchone()
    return row

def save_state(cx, conv_id: int, last_id: int, count: int, h: str):
    cx.execute("INSERT INTO processed(conversation_id,last_message_id,message_count,content_hash) VALUES(?,?,?,?) "
               "ON CONFLICT(conversation_id) DO UPDATE SET last_message_id=excluded.last_message_id, message_count=excluded.message_count, content_hash=excluded.content_hash, updated_at=datetime('now')",
               (conv_id, last_id, count, h))
    cx.commit()
