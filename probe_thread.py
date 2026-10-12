import os, asyncio, logging, re
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright
load_dotenv()
BASE=os.getenv("WOOTIFY_BASE_URL","https://www.wootify.online")
USER=os.getenv("WOOTIFY_USERNAME",""); PWD=os.getenv("WOOTIFY_PASSWORD","")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("probe")
async def main():
    out=Path("playwright-screenshots"); data=Path("data")
    apilog=[]
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True)
        ctx=await b.new_context()
        pg=await ctx.new_page()
        async def guard(r):
            if r.request.method not in ("GET","HEAD","OPTIONS") and not any(s in r.request.url.lower() for s in ("/login","/auth","/session","token")):
                log.warning(f"BLOCKED {r.request.method} {r.request.url[:150]}"); await r.abort(); return
            await r.continue_()
        await pg.route("**/*", guard)
        async def on_resp(resp):
            u=resp.url
            if any(k in u.lower() for k in ("/api/","chatwoot","conversation","message","inbox")):
                apilog.append(f"{resp.status} {resp.request.method} {u[:400]}")
        pg.on("response", on_resp)
        await pg.goto(BASE.rstrip()+"/login", wait_until="domcontentloaded", timeout=30000)
        await pg.wait_for_timeout(2000)
        await pg.locator("input[type=email]").first.fill(USER)
        await pg.locator("input[type=password]").first.fill(PWD)
        await pg.locator("button:has-text('Sign in')").first.click()
        await pg.wait_for_timeout(5000)
        await pg.goto(BASE.rstrip()+"/conversations", wait_until="domcontentloaded", timeout=60000)
        await pg.wait_for_timeout(7000)
        # rendered html size
        html=await pg.content()
        (data/"conv_rendered.html").write_text(html, encoding="utf-8")
        log.info(f"rendered len={len(html)}")
        # find open badges
        opens=pg.locator("text=OPEN")
        log.info(f"OPEN count={await opens.count()}")
        # visible rows: divs containing a phone-like number
        phones = await pg.eval_on_selector_all("div", "els => els.map(e=>e.innerText).filter(t=>t && /201\\d{8,}/.test(t)).slice(0,5).map(t=>t.slice(0,200))")
        log.info(f"phone divs sample={phones}")
        # clickable candidates: elements with cursor pointer containing OPEN
        info = await pg.evaluate("""() => {
          const els=[...document.querySelectorAll('div')].filter(d=>d.innerText && d.innerText.includes('OPEN') && d.innerText.match(/201\\d+/)).slice(0,3).map(d=>({tag:d.tagName, cls:d.className.slice(0,200), txt:d.innerText.slice(0,300), html:d.outerHTML.slice(0,800)}));
          return els;
        }""")
        for i,x in enumerate(info):
            log.info(f"row{i} cls={x['cls']!r} txt={x['txt']!r}")
            (data/f"row{i}.html").write_text(x['html'], encoding="utf-8")
        # try click first row via JS click on div containing first phone
        clicked=False
        try:
            await pg.evaluate("""() => {
              const d=[...document.querySelectorAll('div')].find(d=>d.innerText && /201034999035/.test(d.innerText) && d.innerText.includes('OPEN'));
              if(d){ d.scrollIntoView(); d.click(); return true;} return false;
            }""")
            await pg.wait_for_timeout(5000)
            await pg.screenshot(path=str(out/"11-thread-open.png"), full_page=True)
            body=await pg.inner_text("body")
            (data/"thread_text.txt").write_text(body, encoding="utf-8")
            log.info(f"after click chars={len(body)} snippet={body[:3000]!r}")
            clicked=True
        except Exception as e:
            log.warning(f"click err {e}")
        log.info("APIs:")
        for l in apilog[:50]:
            log.info(f"  {re.sub(r'(token=)[^&\\s]+', r'\\1***', l)}")
        (data/"apilog.txt").write_text("\n".join(apilog), encoding="utf-8")
        await b.close()
import asyncio; asyncio.run(main())
