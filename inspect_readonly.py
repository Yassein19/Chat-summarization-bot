"""Read-only Wootify inspector. No send/modify/delete actions allowed."""
import os, sys, asyncio, logging
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()
BASE = os.getenv("WOOTIFY_BASE_URL", "https://www.wootify.online")
USER = os.getenv("WOOTIFY_USERNAME", "")
PWD = os.getenv("WOOTIFY_PASSWORD", "")
READONLY = os.getenv("READONLY_MODE", "1") == "1"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wootify-readonly")

BLOCKED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ALLOW_POST_SUBSTR = ("/login", "/auth", "/session", "token", "/api/auth")

def is_write_blocked(method: str, url: str) -> bool:
    if not READONLY:
        return False
    if method.upper() in ("GET", "HEAD", "OPTIONS"):
        return False
    low = url.lower()
    if any(s in low for s in ALLOW_POST_SUBSTR):
        return False  # allow login only
    return True

async def main():
    if not USER or not PWD:
        log.error("Missing credentials in .env")
        sys.exit(2)
    outdir = Path("playwright-screenshots")
    outdir.mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        # Network guard: abort disallowed writes
        async def route_guard(route):
            req = route.request
            if is_write_blocked(req.method, req.url):
                log.warning(f"BLOCKED write {req.method} {req.url} (readonly)")
                await route.abort()
                return
            await route.continue_()
        await page.route("**/*", route_guard)

        log.info(f"Opening {BASE} (readonly={READONLY})")
        await page.goto(BASE, wait_until="networkidle", timeout=60000)
        await page.screenshot(path=str(outdir / "01-home.png"))
        log.info(f"home title: {await page.title()!r} url: {page.url}")

        # Try known auth routes
        for path in ["/login", "/conversations", "/app", "/dashboard"]:
            try:
                await page.goto(BASE.rstrip("/") + path, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2500)
                await page.screenshot(path=str(outdir / f"02-{path.strip('/').replace('/','_')}.png"))
                inputs = await page.eval_on_selector_all(
                    "input", "els => els.map(e => ({type: e.type, name: e.name, id: e.id, placeholder: e.placeholder, aria: e.getAttribute('aria-label')}))"
                )
                buttons = await page.eval_on_selector_all(
                    "button", "els => els.slice(0,20).map(e => e.innerText.slice(0,80))"
                )
                log.info(f"ROUTE {path} -> url={page.url} title={await page.title()!r}")
                log.info(f"  inputs={inputs}")
                log.info(f"  buttons={buttons}")
            except Exception as e:
                log.warning(f"route {path} failed: {e}")

        # Attempt login ONLY on /login if form exists - never send messages
        try:
            await page.goto(BASE.rstrip("/") + "/login", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2500)
            email_selectors = ["input[type=email]", "input[name=email]", "input[name=username]", "input[type=text]"]
            pwd_selector = "input[type=password]"
            email_loc = None
            for sel in email_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        email_loc = loc
                        log.info(f"login user field: {sel}")
                        break
                except Exception:
                    continue
            pwd_loc = page.locator(pwd_selector).first
            has_pwd = await pwd_loc.count() > 0
            log.info(f"has_password_field={has_pwd}")
            if email_loc and has_pwd:
                await email_loc.fill(USER)
                await pwd_loc.fill(PWD)
                await page.screenshot(path=str(outdir / "03-login-filled.png"))
                # click login button (heuristic) - allowed POST to /login|/auth
                btn = page.locator("button:has-text('Login'), button:has-text('Log in'), button:has-text('Sign in'), button[type=submit]").first
                if await btn.count() > 0:
                    await btn.click()
                    await page.wait_for_timeout(5000)
                    await page.screenshot(path=str(outdir / "04-after-login.png"))
                    log.info(f"after-login url={page.url}")
                    # Check for conversations link
                    conv = await page.content()
                    log.info(f"after-login page_len={len(conv)} has_conversation={'conversation' in conv.lower()}")
                else:
                    log.warning("login button not found - manual selector needed")
            else:
                log.warning("login form not detected - need manual inspection of screenshots")
        except Exception as e:
            log.error(f"login attempt failed (safe): {e}")

        await browser.close()
        log.info("DONE - readonly, no messages sent/modified.")

if __name__ == "__main__":
    asyncio.run(main())
