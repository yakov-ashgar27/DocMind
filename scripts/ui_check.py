"""Drive the real UI end-to-end in headless Chromium and take screenshots (mobile viewport)."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/shots")
FIX = Path(__file__).resolve().parents[1] / "backend/tests/fixtures"
OUT.mkdir(exist_ok=True)
errors = []

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 400, "height": 860}, device_scale_factor=2, locale="he-IL", accept_downloads=True, bypass_csp=True)
    page = ctx.new_page()
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE)
    page.wait_for_selector(".auth-card")
    page.screenshot(path=OUT / "01_login.png")
    page.click("text=אין לי חשבון עדיין")
    page.fill("input[name=display_name]", "יוסי")
    page.fill("input[name=email]", "yossi@example.com")
    page.fill("input[name=password]", "Sup3rSecretPw")
    page.click("button[type=submit]")
    page.wait_for_selector(".hero")
    page.screenshot(path=OUT / "02_home_empty.png")
    page.goto(BASE + "/#/library")
    page.wait_for_selector(".page-head")
    files = [str(FIX / n) for n in ["IMG_20261115_132411.jpg", "scan_0012.pdf", "document_7.pdf", "file_2026_10.pdf",
                                     "download (3).pdf", "Scan_20261109.pdf", "p_2025_06.pdf", "IMG-20261102-WA0007.jpg"]]
    page.set_input_files("input[type=file][multiple]", files)
    page.wait_for_function("document.querySelectorAll('.doc-card').length >= 8 && !document.querySelector('.doc-card .spinner')", timeout=90000)
    page.wait_for_timeout(800)
    page.screenshot(path=OUT / "03_library.png", full_page=True)
    page.goto(BASE + "/#/home")
    page.wait_for_selector(".stats")
    page.wait_for_timeout(500)
    page.screenshot(path=OUT / "04_home.png", full_page=True)
    # Assistant — first interaction
    page.goto(BASE + "/#/assistant?new=1")
    page.wait_for_selector(".welcome")
    page.screenshot(path=OUT / "05_assistant_welcome.png")
    page.fill(".composer-input", "אני צריך מסמכים למלגת מילואים")
    page.keyboard.press("Enter")
    page.wait_for_selector(".suggest")
    page.fill(".composer-input", "תעודת זהות וספח, צו מילואים, אישור לימודים ואישור ניהול חשבון")
    page.keyboard.press("Enter")
    page.wait_for_selector(".proposal button")
    page.wait_for_timeout(600)
    page.screenshot(path=OUT / "06_assistant_results.png", full_page=True)
    page.click(".proposal .btn.primary")
    page.wait_for_function("document.querySelectorAll('.bubble.assistant').length >= 3")
    # Second interaction uses memory
    page.fill(".composer-input", "צריך להגיש שוב מלגת מילואים")
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelectorAll('.req-card').length >= 2")
    page.wait_for_timeout(600)
    last = page.locator(".bubble.assistant").last
    last.scroll_into_view_if_needed()
    page.screenshot(path=OUT / "07_assistant_memory.png", full_page=True)
    # Not-found with official source
    page.fill(".composer-input", "תמצא לי את הדרכון וגיליון הציונים")
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelectorAll('.acq').length >= 2")
    page.wait_for_timeout(500)
    page.locator(".bubble.assistant").last.screenshot(path=OUT / "08_not_found.png")
    # Create bundle from the memory-based answer
    page.locator(".bubble.assistant").nth(-2).locator("text=יצירת תיק מסמכים").click()
    page.wait_for_selector(".bundle-items")
    page.wait_for_timeout(700)
    page.screenshot(path=OUT / "09_bundle.png", full_page=True)
    with page.expect_download() as dl:
        page.locator(".bundle-item .icon-btn[aria-label='הורדה']").first.click()
    print("single download:", dl.value.suggested_filename)
    downloads = []
    page.on("download", lambda d: downloads.append(d.suggested_filename))
    page.click(".download-bar .btn.primary")
    page.wait_for_timeout(5000)
    print("bundle downloads:", downloads)
    # Document detail
    page.goto(BASE + "/#/library")
    page.wait_for_selector(".doc-card")
    page.locator(".doc-card").filter(has_text="תעודת זהות").first.click()
    page.wait_for_selector(".doc-hero")
    page.wait_for_timeout(600)
    page.screenshot(path=OUT / "10_document.png", full_page=True)
    for route, name in [("/memory", "11_memory"), ("/accounts", "12_accounts"), ("/settings", "13_settings"), ("/categories", "14_categories")]:
        page.goto(BASE + "/#" + route)
        page.wait_for_selector(".page-head")
        page.wait_for_timeout(500)
        page.screenshot(path=OUT / f"{name}.png", full_page=True)
    # English + desktop
    page.goto(BASE + "/#/settings")
    page.wait_for_selector(".seg")
    page.click(".seg button:has-text('English')")
    page.wait_for_timeout(800)
    page.set_viewport_size({"width": 1366, "height": 900})
    page.goto(BASE + "/#/assistant?new=1")
    page.wait_for_selector(".welcome")
    page.fill(".composer-input", "Find my identity card and proof of enrollment")
    page.keyboard.press("Enter")
    page.wait_for_selector(".req-card")
    page.wait_for_timeout(700)
    page.screenshot(path=OUT / "15_desktop_en.png")
    b.close()
print("console errors:", errors)
