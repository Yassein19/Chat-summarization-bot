"""Config - strict readonly. Secrets from .env only, never logged."""
import os
from dotenv import load_dotenv
load_dotenv()

BASE_URL = os.getenv("WOOTIFY_BASE_URL", "https://www.wootify.online")
API_BASE = "https://chatwoot-sending-templates-production.up.railway.app"
USERNAME = os.getenv("WOOTIFY_USERNAME", "")
PASSWORD = os.getenv("WOOTIFY_PASSWORD", "")
READONLY_MODE = os.getenv("READONLY_MODE", "1") == "1"
ORG_ID = int(os.getenv("WOOTIFY_ORG_ID", "8"))
CONFIG_ID = int(os.getenv("WOOTIFY_CONFIG_ID", "7"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
# Groq (OpenAI-compatible, https://api.groq.com/openai/v1). Preferred for Arabic chats.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
# Fallback chain: tried in order when the primary hits limits/errors (each model has its own quota).
GROQ_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "GROQ_FALLBACK_MODELS", "openai/gpt-oss-20b,qwen/qwen3.8-27b,allam-2-7b").split(",") if m.strip()]

def groq_model_chain() -> list[str]:
    seen: list[str] = []
    for m in [GROQ_MODEL, *GROQ_FALLBACK_MODELS]:
        if m and m not in seen:
            seen.append(m)
    return seen

def llm_provider() -> str:
    """openrouter > groq > openai > none. OpenRouter preferred when its key is set."""
    if OPENROUTER_API_KEY:
        return "openrouter"
    if GROQ_API_KEY:
        return "groq"
    if OPENAI_API_KEY:
        return "openai"
    return "none"

# OpenRouter multi-agent (https://openrouter.ai): agent1 retrieves customer facts,
# agent2 summarizes (customer-centric) + evaluates the bot. OpenAI-compatible API.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPEN_ROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_RETRIEVER_MODEL = os.getenv("OPENROUTER_RETRIEVER_MODEL", "meta-llama/llama-3.1-8b-instruct")
OPENROUTER_SUMMARIZER_MODEL = os.getenv("OPENROUTER_SUMMARIZER_MODEL", "openai/gpt-oss-120b")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://www.wootify.online")
OPENROUTER_APP_TITLE = os.getenv("OPENROUTER_APP_TITLE", "wootify-analyzer")

DB_PATH = os.getenv("DB_PATH", "data/wootify_state.db")
EXCEL_PATH = os.getenv("EXCEL_PATH", "data/wootify_analysis.xlsx")

ALLOWED_POST_SUBSTR = ("/api/auth/login", "/api/auth/refresh")

def assert_readonly(method: str, url: str):
    if not READONLY_MODE:
        return
    m = method.upper()
    if m in ("GET", "HEAD", "OPTIONS"):
        return
    if any(s in url for s in ALLOWED_POST_SUBSTR):
        return
    raise PermissionError(f"Readonly blocked: {m} {url[:120]}")
