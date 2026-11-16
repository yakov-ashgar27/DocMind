"""Browser check of the vault (PIN-protected folders) and two-step sign-in. Run after ui_check.py
(re-uses its account and documents)."""
import base64
import hashlib
import hmac
import struct
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/shots")
EMAIL, PW, PIN = "yossi@example.com", "Sup3rSecretPw", "482915"


def totp(secret):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    d = hmac.new(key, struct.pack(">Q", int(time.time() // 30)), hashlib.sha1).digest()
    o = d[-1] & 15
    return f"{(struct.unpack('>I', d[o:o + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"


errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 400, "height": 860}, device_scale_factor=2, locale="he-IL", bypass_csp=True)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE)
    page.wait_for_selector(".auth-card")
    page.fill("input[name=email]", EMAIL)
    page.fill("input[name=password]", PW)
    page.click("button[type=submit]")
    page.wait_for_selector(".hero")
    page.goto(BASE + "/#/settings")
    page.wait_for_selector(".settings")
    page.click(".seg button:has-text('עברית')")
    page.wait_for_timeout(600)
    # set vault PIN
    page.click("text=הגדרת קוד כספת")
    page.fill(".sheet input[autocomplete=current-password]", PW)
    pins = page.locator(".sheet input[inputmode=numeric]")
    pins.nth(0).fill(PIN)
    pins.nth(1).fill(PIN)
    page.click(".sheet button:has-text('שמירה')")
    page.wait_for_timeout(800)
    page.screenshot(path=OUT / "20_settings_security.png", full_page=True)
    # library shows protected placeholders
    page.goto(BASE + "/#/library")
    page.wait_for_selector(".doc-card")
    page.wait_for_timeout(500)
    n_locked = page.locator(".doc-card.locked").count()
    page.screenshot(path=OUT / "21_library_locked.png", full_page=True)
    body = page.inner_text("body")
    assert "IMG_20261115" not in body
    # unlock from a locked card
    page.locator(".doc-card.locked").first.click()
    page.wait_for_selector(".pin-input")
    page.fill(".pin-input", "000000")
    page.click(".sheet button[type=submit]")
    page.wait_for_selector(".form-error:not(:empty)")
    page.fill(".pin-input", PIN)
    page.click(".sheet button[type=submit]")
    page.wait_for_selector(".vault-pill")
    page.wait_for_timeout(800)
    n_after = page.locator(".doc-card.locked").count()
    page.screenshot(path=OUT / "22_library_unlocked.png")
    # folders screen with lock toggles
    page.goto(BASE + "/#/categories")
    page.wait_for_selector(".cat")
    page.wait_for_timeout(400)
    page.screenshot(path=OUT / "23_categories_locks.png", full_page=True)
    page.click(".vault-pill button")
    page.wait_for_timeout(500)
    pill_gone = page.locator(".vault-pill").count() == 0
    # enable 2FA
    page.goto(BASE + "/#/settings")
    page.wait_for_selector(".settings")
    page.locator("section:has-text('אימות דו-שלבי') button:has-text('הפעלה')").click()
    page.fill(".sheet input[type=password]", PW)
    page.click(".sheet button:has-text('הפעלה')")
    page.wait_for_selector(".secret")
    secret = page.inner_text(".secret").replace(" ", "")
    page.fill(".sheet .pin-input", totp(secret))
    page.click(".sheet button:has-text('אימות')")
    page.wait_for_selector(".recovery code")
    page.screenshot(path=OUT / "24_mfa_recovery.png")
    page.click(".sheet button:has-text('סיום')")
    # sign out and back in with 2FA
    page.goto(BASE + "/#/settings")
    page.wait_for_selector(".settings")
    page.click("button:has-text('התנתקות'):not(:has-text('מכל'))")
    page.wait_for_selector(".auth-card")
    page.fill("input[name=email]", EMAIL)
    page.fill("input[name=password]", PW)
    page.click("button[type=submit]")
    page.wait_for_selector(".pin-input")
    page.screenshot(path=OUT / "25_mfa_login.png")
    page.fill(".pin-input", totp(secret))
    page.click("button[type=submit]")
    try:
        page.wait_for_selector(".tabbar .tab", timeout=8000)
        page.wait_for_selector(".content", timeout=8000)
    except Exception:
        print("MFA LOGIN DID NOT REACH HOME:", page.inner_text("body")[:300], errors)
        raise
    print(f"locked cards: {n_locked} -> after unlock: {n_after}; lock button hides pill: {pill_gone}")
    b.close()
print("page errors:", errors)
