"""End-to-end browser test of the phone edition (mobile/).

The only stand-in: tesseract.js comes from a CDN this sandbox can't reach, so the test serves a tiny fake
`Tesseract` whose recognize() sends the rendered canvas to a local endpoint running the same Tesseract
engine (heb+eng). Everything else (pdf.js, encryption, IndexedDB, classifier, assistant, vault, backup) is the
real code running in Chromium.
usage: python scripts/mobile_check.py [out_dir]
"""
import base64
import http.server
import io
import json
import socketserver
import sys
import threading
from pathlib import Path

import pytesseract
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
MOBILE, FIX = ROOT / "mobile", ROOT / "backend/tests/fixtures"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/mshots")
OUT.mkdir(exist_ok=True)
PORT = 8766


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(MOBILE), **k)

    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.path != "/__ocr":
            return self.send_error(404)
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        img = Image.open(io.BytesIO(base64.b64decode(data["png"].split(",", 1)[1])))
        text = pytesseract.image_to_string(img.convert("L"), lang="heb+eng")
        body = json.dumps({"text": text}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


Handler.extensions_map[".mjs"] = "text/javascript"
Handler.extensions_map[".webmanifest"] = "application/manifest+json"
FAKE_TESSERACT = """
window.Tesseract = { createWorker: async (langs, oem, opts) => {
  opts && opts.logger && opts.logger({ status: 'loading tesseract core', progress: 0 });
  return { recognize: async (canvas) => {
    const r = await fetch('/__ocr', { method: 'POST', body: JSON.stringify({ png: canvas.toDataURL('image/png') }) });
    return { data: { text: (await r.json()).text } };
  }, terminate: async () => {} };
} };
"""

socketserver.ThreadingTCPServer.allow_reuse_address = True
srv = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}/"
errors, results = [], {}


def ok(name, cond):
    results[name] = bool(cond)
    print(("PASS " if cond else "FAIL ") + name)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 400, "height": 860}, device_scale_factor=2, locale="he-IL", accept_downloads=True, bypass_csp=True)
    ctx.route("https://cdn.jsdelivr.net/**", lambda r: r.fulfill(status=200, content_type="text/javascript", body=FAKE_TESSERACT))
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto(BASE)
    page.wait_for_selector(".auth-card")
    page.screenshot(path=OUT / "m01_setup.png")
    # --- first run: passcode setup
    page.fill("input[autocomplete=given-name]", "יוסי")
    pw = page.locator("input[type=password]")
    pw.nth(0).fill("secret-pass-1")
    pw.nth(1).fill("secret-pass-2")
    page.click("button[type=submit]")
    page.wait_for_selector(".form-error:not(:empty)")
    pw.nth(1).fill("secret-pass-1")
    page.click("button[type=submit]")
    page.wait_for_selector(".hero", timeout=60000)
    ok("setup creates encrypted app", True)
    # --- upload
    page.goto(BASE + "#/library")
    page.wait_for_selector(".page-head")
    names = ["IMG_20261115_132411.jpg", "scan_0012.pdf", "document_7.pdf", "file_2026_10.pdf", "download (3).pdf",
             "Scan_20261109.pdf", "p_2025_06.pdf", "IMG-20261102-WA0007.jpg"]
    page.set_input_files("input[type=file][multiple]", [str(FIX / n) for n in names])
    page.wait_for_function("document.querySelectorAll('.doc-card').length >= 8 && !document.querySelector('.doc-card .spinner')", timeout=240000)
    page.wait_for_timeout(1000)
    page.screenshot(path=OUT / "m02_library.png", full_page=True)
    body = page.inner_text("body")
    ok("classified Hebrew scans + photos on device", all(x in body for x in ["תעודת זהות", "ספח תעודת זהות", "צו מילואים", "אישור לימודים", "אישור ניהול חשבון", "תלוש שכר"]))
    ok("duplicate detected", "כפילות אפשרית" in body)
    # --- assistant: learning flow
    page.goto(BASE + "#/assistant?new=1")
    page.wait_for_selector(".welcome")
    page.fill(".composer-input", "אני צריך מסמכים למלגת מילואים")
    page.keyboard.press("Enter")
    page.wait_for_selector(".suggest")
    page.fill(".composer-input", "תעודת זהות וספח, צו מילואים, אישור לימודים ואישור ניהול חשבון")
    page.keyboard.press("Enter")
    page.wait_for_selector(".proposal button")
    ok("assistant found all 5 on device", page.locator(".req-card").last.locator(".pill.ok").count() == 5)
    page.screenshot(path=OUT / "m03_assistant.png", full_page=True)
    page.click(".proposal .btn.primary")
    page.wait_for_function("document.querySelectorAll('.bubble.assistant').length >= 3")
    page.fill(".composer-input", "צריך להגיש שוב מלגת מילואים")
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelectorAll('.req-card').length >= 2")
    ok("memory reused next time", "ברשימה השמורה" in page.locator(".bubble.assistant").last.inner_text())
    page.fill(".composer-input", "תמצא לי את הדרכון")
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelectorAll('.acq').length >= 1")
    ok("not found -> official source", "רשות האוכלוסין" in page.locator(".bubble.assistant").last.inner_text())
    # --- bundle + downloads
    page.locator(".bubble.assistant").nth(-2).locator("text=יצירת תיק מסמכים").click()
    page.wait_for_selector(".bundle-items")
    page.wait_for_timeout(600)
    page.screenshot(path=OUT / "m04_bundle.png", full_page=True)
    downloads = []
    page.on("download", lambda d: downloads.append(d.suggested_filename))
    page.click(".download-bar .btn.primary")
    page.wait_for_timeout(5000)
    ok("bundle downloads separate files", len(downloads) == 5 and downloads[0] == "01_תעודת זהות.jpg")
    with page.expect_download() as dl:
        page.click("text=PDF מאוחד")
    ok("combined PDF", dl.value.suggested_filename.endswith(".pdf"))
    # --- encryption at rest
    leak = page.evaluate("""async () => {
      const db = await new Promise((res, rej) => { const r = indexedDB.open('docmind'); r.onsuccess = () => res(r.result); r.onerror = rej; });
      let raw = '';
      for (const s of ['kv', 'docs', 'blobs', 'records']) {
        const vals = await new Promise((res) => { const q = db.transaction(s).objectStore(s).getAll(); q.onsuccess = () => res(q.result); });
        for (const v of vals) raw += JSON.stringify(v, (k, x) => x instanceof Uint8Array ? Array.from(x).map(c => String.fromCharCode(c)).join('') : x);
      }
      return ['Registrar', 'registered student', 'מלגת מילואים', 'יוסי', 'IMG_20261115', '%PDF'].filter(w => raw.includes(w));
    }""")
    ok("nothing readable in IndexedDB", leak == [])
    # --- vault
    page.goto(BASE + "#/settings")
    page.wait_for_selector(".settings")
    page.click("text=הגדרת קוד כספת")
    pins = page.locator(".sheet input[inputmode=numeric]")
    pins.nth(0).fill("482915")
    pins.nth(1).fill("482915")
    page.click(".sheet button:has-text('שמירה')")
    page.wait_for_timeout(2500)
    page.goto(BASE + "#/library")
    page.wait_for_selector(".doc-card")
    page.wait_for_timeout(800)
    locked = page.locator(".doc-card.locked").count()
    page.screenshot(path=OUT / "m05_vault_locked.png", full_page=True)
    print("locked cards:", locked)
    ok("protected folders encrypted + hidden", locked == 4 and "IMG_2026" not in page.inner_text("body"))
    page.locator(".doc-card.locked").first.click()
    page.wait_for_selector(".pin-input")
    page.fill(".pin-input", "482915")
    page.click(".sheet button[type=submit]")
    page.wait_for_selector(".vault-pill")
    page.wait_for_timeout(1200)
    ok("vault unlock reveals", page.locator(".doc-card.locked").count() == 0)
    # --- lock app, wrong passcode, unlock
    page.goto(BASE + "#/more")
    page.wait_for_selector(".lock-btn")
    page.click(".lock-btn")
    page.wait_for_selector(".pass-input")
    page.fill(".pass-input", "wrong-pass")
    page.click("button[type=submit]")
    page.wait_for_selector(".form-error:not(:empty)")
    page.fill(".pass-input", "secret-pass-1")
    page.click("button[type=submit]")
    page.wait_for_selector(".tabbar")
    ok("app lock + passcode", True)
    # --- backup -> erase -> restore
    page.goto(BASE + "#/settings")
    page.wait_for_selector(".settings")
    with page.expect_download() as dl:
        page.click("text=יצירת קובץ גיבוי")
    bpath = OUT / "backup.docmind"
    dl.value.save_as(bpath)
    page.evaluate("indexedDB.deleteDatabase('docmind')")
    page.goto(BASE)
    page.reload()
    page.wait_for_selector(".auth-card")
    page.set_input_files("input[type=file][accept*='.docmind']", str(bpath))
    page.wait_for_selector(".pass-input", timeout=20000)
    page.fill(".pass-input", "secret-pass-1")
    page.click("button[type=submit]")
    page.wait_for_selector(".stats", timeout=20000)
    ok("backup restore", "8" in page.locator(".stats").inner_text())
    # --- installability
    cdp = ctx.new_cdp_session(page)
    inst = cdp.send("Page.getInstallabilityErrors")["installabilityErrors"]
    ok("installable PWA", inst == [])
    page.goto(BASE + "#/home")
    page.wait_for_selector(".hero")
    page.wait_for_timeout(500)
    page.screenshot(path=OUT / "m06_home.png", full_page=True)
    # --- the real Content-Security-Policy (no bypass): app must load and process a PDF under it
    ctx2 = b.new_context(viewport={"width": 400, "height": 860}, locale="he-IL")
    ctx2.route("https://cdn.jsdelivr.net/**", lambda r: r.fulfill(status=200, content_type="text/javascript", body=FAKE_TESSERACT))
    p2 = ctx2.new_page()
    csp = []
    p2.on("console", lambda m: "Content Security Policy" in m.text and csp.append(m.text))
    p2.on("pageerror", lambda e: errors.append("csp-ctx: " + str(e)))
    p2.goto(BASE)
    p2.wait_for_selector(".auth-card")
    pw2 = p2.locator("input[type=password]")
    pw2.nth(0).fill("another-pass")
    pw2.nth(1).fill("another-pass")
    p2.click("button[type=submit]")
    p2.wait_for_selector(".hero", timeout=60000)
    p2.goto(BASE + "#/library")
    p2.wait_for_selector(".page-head")
    p2.set_input_files("input[type=file][multiple]", [str(FIX / "download (3).pdf"), str(FIX / "Scan_20261109.pdf")])
    p2.wait_for_selector(".doc-card:has-text('אישור ניהול חשבון')", timeout=120000)
    p2.wait_for_selector(".doc-card:has-text('אישור לימודים')", timeout=60000)
    ok("works under strict CSP", not csp)
    if csp:
        print("CSP violations:", csp[:3])
    b.close()
srv.shutdown()
bad = [e for e in errors if "favicon" not in e]
print("page errors:", bad)
print(f"{sum(results.values())}/{len(results)} checks passed")
sys.exit(0 if all(results.values()) and not bad else 1)
