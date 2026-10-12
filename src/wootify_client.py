"""Wootify backend client - READ-ONLY (only POST is /auth/login)."""
import logging, time
import httpx
from . import config

log = logging.getLogger("wootify.client")

class WootifyClient:
    def __init__(self):
        self.c = httpx.Client(timeout=30)
        self.token = None

    def _req(self, method, url, **kw):
        config.assert_readonly(method, url)
        for attempt in range(3):
            try:
                r = self.c.request(method, url, **kw)
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    continue
                return r
            except httpx.HTTPError as e:
                log.warning(f"retry {attempt+1} {method} failed: {type(e).__name__}")
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Failed {method} {url[:100]} after retries")

    def login(self):
        # only allowed POST
        url = f"{config.API_BASE}/api/auth/login"
        r = self._req("POST", url, json={"email": config.USERNAME, "password": config.PASSWORD})
        r.raise_for_status()
        self.token = r.json()["access_token"]
        log.info("login ok (token redacted)")
        return self.token

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def list_conversations(self, status="open", page=1):
        url = f"{config.API_BASE}/api/{config.ORG_ID}/chatwoot-configs/{config.CONFIG_ID}/conversations"
        r = self._req("GET", url, params={"status": status, "page": page}, headers=self.headers)
        r.raise_for_status()
        return r.json()

    def get_messages(self, conv_id: int):
        url = f"{config.API_BASE}/api/{config.ORG_ID}/chatwoot-configs/{config.CONFIG_ID}/conversations/{conv_id}/messages"
        r = self._req("GET", url, headers=self.headers)
        r.raise_for_status()
        j = r.json()
        return j.get("payload", []) if isinstance(j, dict) else j
