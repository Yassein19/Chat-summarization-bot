"""Read-only stage 3: open one thread, capture messages + backend APIs. No send."""
import os, asyncio, logging, json, re
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()
BASE=os.getenv("WOOTIFY_BASE_URL","https://www.wootify.online")
USER=os.getenv("WOOTIFY_USERNAME",""); PWD=os.getenv("WOOTIFY_PASSWORD","")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("wootify-thread")

async def main():
    out=Path("playwright-screenshots"); data=Path("data")
    apilog=[]
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True)
        pg=await (await b.new_context()).new_page()
        async def guard(r):
            m=r.request.method; u=r.request.url
            if m not in ("GET","HEAD","OPTIONS") and not any(s in u.lower() for s in ("/login","/auth","/session","token")):
                log.warning(f"BLOCKED {m} {u[:120]}"); await r.abort(); return
            await r.continue_()
        await pg.route("**/*", guard)
        # log api-ish responses (url only, no tokens)
        async def on_resp(resp):
            u=resp.url
            if any(k in u.lower() for k in ("/api/","chatwoot","conversation","message","inbox","account")):
                try:
                    apilog.append(f"{resp.status} {resp.request.method} {u[:300]}")
                except Exception: pass
        pg.on("response", on_resp)

        await pg.goto(BASE.rstrip()+"/login", wait_until="domcontentloaded", timeout=30000)
        await pg.wait_for_timeout(2000)
        await pg.locator("input[type=email]").first.fill(USER)
        await pg.locator("input[type=password]").first.fill(PWD)
        await pg.locator("button:has-text('Sign in')").first.click()
        await pg.wait_for_timeout(5000)
        await pg.goto(BASE.rstrip()+"/conversations", wait_until="networkidle", timeout=60000)
        await pg.wait_for_timeout(4000)
        # click first conversation row: heuristic - first div with OPEN badge
        # try clicking by text of first phone
        rows = pg.locator("text=AxisPay WhatsApp")
        n = await rows.count()
        log.info(f"thread rows found={n}")
        if n>0:
            await rows.first.click()
            await pg.wait_for_timeout(4000)
            await pg.screenshot(path=str(out/"11-thread-open.png"), full_page=True)
            body = await pg.inner_text("body")
            (data/"thread_text.txt").write_text(body, encoding="utf-8")
            log.info(f"thread body chars={len(body)} snippet={body[:2000]!r}")
            html = await pg.content()
            (data/"thread.html").write_text(html, encoding="utf-8")
        # also visit chatwoot setup (read-only GET) to discover backend
        for path in ["/settings/chatwoot", "/settings/api-keys"]:
            try:
                await pg.goto(BASE.rstrip()+path, wait_until="networkidle", timeout=30000)
                await pg.wait_for_timeout(3000)
                await pg.screenshot(path=str(out/f"12-{path.strip('/').replace('/','_')}.png"), full_page=True)
                t = await pg.inner_text("body")
                (data/f"{path.strip('/').replace('/','_')}.txt").write_text(t, encoding="utf-8")
                log.info(f"{path} chars={len(t)} snippet={t[:1000]!r}")
            except Exception as e:
                log.warning(f"{path} err {e}")
        log.info("API calls observed:")
        for l in apilog[:40]:
            # redact token-ish query
            red = re.sub(r"(token=|api_[a-z_]*key=)[^&\s]+", r"\1***", l, flags=re.I)
            log.info(f"  {red}")
        (data/"apilog.txt").write_text("\n".join(apilog), encoding="utf-8")
        await b.close()

if __name__=="__main__":
    import asyncio; asyncio.run(main())
