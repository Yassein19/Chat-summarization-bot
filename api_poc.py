"""Read-only API PoC: login via Wootify backend, list conversations, fetch 1 thread."""
import os, json, logging
from pathlib import Path
import httpx
from dotenv import load_dotenv
load_dotenv()
BASE_API="https://chatwoot-sending-templates-production.up.railway.app"
USER=os.getenv("WOOTIFY_USERNAME",""); PWD=os.getenv("WOOTIFY_PASSWORD","")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("api-poc")
ORG=8; CFG=7
def main():
    data=Path("data"); data.mkdir(exist_ok=True)
    with httpx.Client(timeout=30) as c:
        r=c.post(f"{BASE_API}/api/auth/login", json={"email":USER,"password":PWD})
        log.info(f"login {r.status_code}")
        r.raise_for_status()
        j=r.json()
        # do not log tokens
        token=j.get("token") or j.get("accessToken") or j.get("access_token") or (j.get("data") or {}).get("token")
        log.info(f"login keys={list(j.keys())} has_token={bool(token)}")
        if not token:
            (data/"login_response_keys.txt").write_text(json.dumps(j)[:2000])
            log.error("no token found, inspect keys")
            return
        H={"Authorization":f"Bearer {token}"}
        # list conversations
        rc=c.get(f"{BASE_API}/api/{ORG}/chatwoot-configs/{CFG}/conversations", params={"status":"open","page":1}, headers=H)
        log.info(f"conversations {rc.status_code} len={len(rc.text)}")
        rc.raise_for_status()
        cj=rc.json()
        (data/"conversations_api.json").write_text(json.dumps(cj, ensure_ascii=False, indent=2), encoding="utf-8")
        # normalize list
        items = cj if isinstance(cj,list) else cj.get("data") or cj.get("conversations") or cj.get("items") or []
        log.info(f"items type={type(cj).__name__} count={len(items) if isinstance(items,list) else 'N/A'}")
        if isinstance(items,list) and items:
            log.info(f"first keys={list(items[0].keys())[:20]}")
            first_id = items[0].get("id") or items[0].get("conversation_id") or items[0].get("display_id")
            log.info(f"first conversation id={first_id}")
            # try messages endpoints (read-only GET candidates)
            for url in [
                f"{BASE_API}/api/{ORG}/chatwoot-configs/{CFG}/conversations/{first_id}/messages",
                f"{BASE_API}/api/{ORG}/chatwoot-configs/{CFG}/conversations/{first_id}",
            ]:
                try:
                    rm=c.get(url, headers=H)
                    log.info(f"GET {url.split(BASE_API)[1]} -> {rm.status_code} len={len(rm.text)}")
                    if rm.status_code==200:
                        (data/f"thread_{first_id}.json").write_text(json.dumps(rm.json(), ensure_ascii=False, indent=2)[:20000], encoding="utf-8")
                        break
                except Exception as e:
                    log.warning(f"{url} err {e}")
        log.info("DONE readonly API PoC - no writes performed")
if __name__=="__main__":
    main()
