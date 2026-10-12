"""Read-only stage 2: login then inspect Conversations hub. No writes."""
import os, asyncio, logging, json, re
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()
BASE = os.getenv("WOOTIFY_BASE_URL", "https://www.wootify.online")
USER = os.getenv("WOOTIFY_USERNAME", "")
PWD = os.getenv("WOOTIFY_PASSWORD", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wootify-conv")

ALLOW = ("/login", "/auth", "/session", "token")
def blocked(m, u):
    if m in ("GET","HEAD","OPTIONS"): return False
    return not any(s in u.lower() for s in ALLOW)

async def login(page):
    await page.goto(BASE.rstrip()+"/login", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)
    await page.locator("input[type=email]").first.fill(USER)
    await page.locator("input[type=password]").first.fill(PWD)
    await page.locator("button:has-text('Sign in')").first.click()
    await page.wait_for_timeout(5000)
    log.info(f"logged in -> {page.url}")

async def main():
    out = Path("playwright-screenshots"); out.mkdir(exist_ok=True)
    data = Path("data"); data.mkdir(exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context()
        page = await ctx.new_page()
        async def guard(r):
            if blocked(r.request.method, r.request.url):
                log.warning(f"BLOCKED {r.request.method} {r.request.url}")
                await r.abort(); return
            await r.continue_()
        await page.route("**/*", guard)

        await login(page)
        # go to conversations via sidebar or direct URL
        await page.goto(BASE.rstrip()+"/conversations", wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(4000)
        await page.screenshot(path=str(out/"10-conversations.png"), full_page=True)
        log.info(f"conv url={page.url} title={await page.title()!r}")

        text = await page.inner_text("body")
        (data/"conversations_text.txt").write_text(text, encoding="utf-8")
        log.info(f"body chars={len(text)} snippet={text[:800]!r}")

        # generic structure: links, buttons, list items
        html = await page.content()
        (data/"conversations.html").write_text(html, encoding="utf-8")
        # find conversation ids in html / urls
        ids = sorted(set(re.findall(r"conversations?/(\d+)", html)))
        log.info(f"found conversation id links: {ids[:20]} total={len(ids)}")
        # count message-like nodes
        for sel in ["a", "[role=row]", "li", "tr", "div[class*=conversation]", "div[class*=message]"]:
            try:
                n = await page.locator(sel).count()
                log.info(f"selector {sel!r} count={n}")
            except Exception as e:
                log.info(f"sel {sel} err {e}")
        # capture API calls to chatwoot backend (read-only observation)
        # list requests seen
        await b.close()
        log.info("DONE readonly stage2")

if __name__ == "__main__":
    asyncio.run(main())
