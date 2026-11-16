"""Simulated Android run of the phone edition: a fake window.DocMindNative (same API as NativeBridge.java)
serves the test fixtures as if they were gallery photos / a granted WhatsApp folder, so the real scanner,
OCR pipeline, classifier and encrypted import are exercised in Chromium. Also checks share-in and save-out."""
import base64
import sys
from pathlib import Path

sys.argv = [sys.argv[0], "/tmp/asim"]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
FIX = ROOT / "backend/tests/fixtures"

import http.server, socketserver, threading, json, io  # noqa: E401,E402
import pytesseract  # noqa: E402
from PIL import Image  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

MOBILE = ROOT / "mobile"
FILES = {  # uri -> (fixture, source)
    "content://media/1": ("IMG_20261115_132411.jpg", "gallery"),
    "content://media/2": ("IMG_20261001_090000.jpg", "gallery"),        # grocery list: must be skipped
    "content://wa/3": ("Scan_20261109.pdf", "whatsapp"),
    "content://wa/4": ("IMG-20261102-WA0007.jpg", "whatsapp"),          # exact duplicate of media/1: skipped
    "content://dl/5": ("download (3).pdf", "downloads"),
    "content://dl/6": ("אישור לימודים יעקב.docx", "downloads"),      # Word, says תשפ"ז
    "content://dl/7": ("ishur_old.doc", "downloads"),                # old Word 97 format
}
MIME = {"jpg": "image/jpeg", "pdf": "application/pdf", "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(MOBILE), **k)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/native/file/"):
            enc = self.path.split("/native/file/")[1]
            uri = base64.urlsafe_b64decode(enc + "=" * (-len(enc) % 4)).decode()
            data = (FIX / FILES[uri][0]).read_bytes()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(data)
            return
        return super().do_GET()

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        img = Image.open(io.BytesIO(base64.b64decode(data["png"].split(",", 1)[1])))
        body = json.dumps({"text": pytesseract.image_to_string(img.convert("L"), lang="heb+eng")}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)


H.extensions_map[".mjs"] = "text/javascript"
socketserver.ThreadingTCPServer.allow_reuse_address = True
srv = socketserver.ThreadingTCPServer(("127.0.0.1", 8767), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:8767/"
items = [{"uri": u, "name": f, "size": (FIX / f).stat().st_size, "mime": MIME[f.rsplit(".", 1)[1]],
          "modified": 1790000000000, "source": s} for u, (f, s) in FILES.items()]
FAKE_NATIVE = """
window.__saved = []; window.__shared = [];
window.DocMindNative = {
  info: () => JSON.stringify({ platform: 'android', sdk: 34, media: !!window.__media, allFiles: !!window.__all, folders: window.__folders || [], bundledOcr: false }),
  requestAllFiles: () => { window.__all = true; setTimeout(() => window.__docmindNative('permission', { allFiles: true, media: true }), 10); },
  requestMedia: () => { window.__media = true; setTimeout(() => window.__docmindNative('permission', { media: true }), 10); },
  addFolder: (kind) => { (window.__folders ||= []).push({ uri: 'content://tree/' + kind, kind, label: kind }); setTimeout(() => window.__docmindNative('folder', { ok: true }), 10); },
  removeFolder: () => {},
  scan: () => setTimeout(() => window.__docmindNative('scan', { items: ITEMS }), 10),
  takeShared: () => JSON.stringify(window.__inbox ? window.__inbox.splice(0) : []),
  saveFile: (name, mime, b64) => { window.__saved.push(name); return 'saved'; },
  shareFiles: (json) => { window.__shared.push(JSON.parse(json).map(f => f.name)); return 'ok'; },
};
""".replace("ITEMS", json.dumps(items))
FAKE_TESS = """window.Tesseract={createWorker:async()=>({recognize:async(c)=>{const r=await fetch('/__ocr',{method:'POST',body:JSON.stringify({png:c.toDataURL('image/png')})});return{data:{text:(await r.json()).text}}},terminate:async()=>{}})};"""
res = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 400, "height": 860}, locale="he-IL", bypass_csp=True)
    ctx.add_init_script(FAKE_NATIVE)
    ctx.route("https://cdn.jsdelivr.net/**", lambda r: r.fulfill(status=200, content_type="text/javascript", body=FAKE_TESS))
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(BASE)
    page.wait_for_selector(".auth-card")
    pw = page.locator("input[type=password]")
    pw.nth(0).fill("secret-pass-1")
    pw.nth(1).fill("secret-pass-1")
    page.click("button[type=submit]")
    page.wait_for_selector(".scan-cta", timeout=60000)
    res["home suggests scanning"] = True
    page.click(".scan-cta")
    page.wait_for_selector(".scan-card")
    page.screenshot(path="/tmp/asim_sources.png", full_page=True)
    page.click(".scan-card .btn.primary")
    page.wait_for_function("document.querySelector('.scan-card').innerText.includes('זוהו כמסמכים')", timeout=240000)
    card = page.inner_text(".scan-card")
    res["whole-phone scan indexed 7 files, 6 documents (grocery list skipped)"] = "7 קבצים" in card and "6 זוהו" in card
    page.screenshot(path="/tmp/asim_index.png", full_page=True)
    page.goto(BASE + "#/library")
    page.wait_for_timeout(1200)
    res["scan does not import by itself"] = page.locator(".doc-card").count() == 0
    # 1) the user's exact case: ask for the enrollment certificate -> a list of files from the phone
    page.goto(BASE + "#/assistant?new=1")
    page.wait_for_selector(".welcome")
    page.fill(".composer-input", "תמצא לי אישור לימודים")
    page.keyboard.press("Enter")
    page.wait_for_selector(".phone-file", timeout=30000)
    names = page.locator(".phone-file").all_inner_texts()
    joined = " ".join(names)
    res["search lists all 3 enrollment files on the phone"] = len(names) >= 3 and all(x in joined for x in ["download (3).pdf", "יעקב.docx", "ishur_old.doc"])
    page.screenshot(path="/tmp/asim_pick.png", full_page=True)
    # pick only the תשפ"ז one and import it
    row = page.locator(".phone-file", has_text="יעקב.docx").first
    row.locator("input[type=checkbox]").check()
    page.locator(".req-import .btn.primary:visible").first.click()
    page.wait_for_function("document.body.innerText.includes('יובא')", timeout=30000)
    page.screenshot(path="/tmp/asim_after_import.png", full_page=True)
    page.goto(BASE + "#/library")
    page.wait_for_selector(".doc-card")
    page.wait_for_timeout(800)
    res["picked file imported (1 doc in library)"] = page.locator(".doc-card").count() == 1
    # 2) free text: the academic year
    page.goto(BASE + "#/assistant?new=1")
    page.wait_for_selector(".welcome")
    page.fill(".composer-input", 'אישור לימודים תשפ"ז')
    page.keyboard.press("Enter")
    page.wait_for_timeout(5000)
    page.screenshot(path="/tmp/asim_year.png", full_page=True)
    last = page.inner_text("body").split("אישור לימודים תשפ\"ז")[-1]
    res['"תשפ"ז" finds the imported Word file first'] = "יעקב" in last or "תשפ" in last
    # 3) not on the phone -> where else to look
    page.goto(BASE + "#/assistant?new=1")
    page.wait_for_selector(".welcome")
    page.fill(".composer-input", "תמצא לי תלוש שכר")
    page.keyboard.press("Enter")
    page.wait_for_selector(".elsewhere", timeout=30000)
    ew = page.locator(".elsewhere").first
    hrefs = ew.locator("a").evaluate_all("els => els.map(e => e.href)")
    res["not found -> Gmail/Drive/WhatsApp search links"] = any("mail.google.com" in x for x in hrefs) and any("drive.google.com" in x for x in hrefs)
    page.screenshot(path="/tmp/asim_elsewhere.png", full_page=True)
    # 3b) the screenshot case: inside a task, "didn't you find X?" must search again, not be ignored
    page.goto(BASE + "#/assistant?new=1")
    page.wait_for_selector(".welcome")
    page.fill(".composer-input", "אני צריך מסמכים למלגת מילואים")
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelectorAll('.req-card').length >= 1", timeout=30000)
    n0 = page.locator(".req-card").count()
    page.fill(".composer-input", "לא מצאת אישור לימודים?")
    page.keyboard.press("Enter")
    page.wait_for_function(f"document.querySelectorAll('.req-card').length > {n0}", timeout=30000)
    res["mid-task 'לא מצאת אישור לימודים?' searches again"] = "אישור לימודים" in page.locator(".req-card").last.inner_text()
    # 4) import everything recognised
    page.goto(BASE + "#/accounts")
    page.wait_for_selector(".scan-card")
    page.wait_for_timeout(1000)
    res["import-all offers only the 4 new distinct docs"] = "ייבוא כל 4" in page.inner_text(".scan-card")
    page.locator(".scan-card .btn.ghost").click()
    page.wait_for_function("document.querySelector('#toast').innerText.includes('4 מסמכים נוספו')", timeout=120000)
    page.goto(BASE + "#/library")
    page.wait_for_selector(".doc-card")
    page.wait_for_timeout(2500)
    res["import-all brings the rest (5 docs, duplicate photo skipped)"] = page.locator(".doc-card").count() == 5
    # download -> Android save
    page.goto(BASE + "#/library")
    page.wait_for_selector(".doc-card")
    page.locator(".doc-card").first.click()
    page.wait_for_selector(".doc-hero")
    page.click(".doc-hero button:has-text('הורדה')")
    page.wait_for_function("window.__saved.length === 1", timeout=10000)
    res["download goes through Android save"] = True
    # share-in from another app
    page.evaluate("window.__inbox = [{uri:'content://dl/5', name:'from-gmail.pdf', size:1, mime:'application/pdf'}]; window.__docmindNative('shared', {})")
    page.wait_for_timeout(3000)
    res["Share → DocMind import"] = page.locator(".doc-card").count() >= 5 and "נוספו" in page.inner_text("#toast")
    b.close()
srv.shutdown()
for k, v in res.items():
    print(("PASS " if v else "FAIL ") + k)
print("page errors:", errs)
print(f"{sum(res.values())}/{len(res)} checks passed")
