"""Generate clearly-fictional SAMPLE documents (Hebrew + English) for tests and demos.

Every document is stamped “SAMPLE / דוגמה”, uses invented names, invented institutions and test ID
numbers. They exist to exercise OCR + classification with realistic layouts and unhelpful filenames.

usage: python scripts/make_sample_docs.py <out_dir>
"""
from __future__ import annotations

import io
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def page(lines, size=(1240, 1754), rtl=True, photo=False, seed=1):
    """Render lines [(text, pt, bold)] onto a page. RTL lines are right-aligned with proper bidi (raqm)."""
    rnd = random.Random(seed)
    img = Image.new("RGB", size, (252, 251, 248))
    d = ImageDraw.Draw(img)
    y = 110
    for text, pt, bold in lines:
        if not text:
            y += pt
            continue
        font = ImageFont.truetype(BOLD if bold else FONT, pt)
        is_rtl = rtl and any("֐" <= ch <= "׿" for ch in text)
        kw = {"direction": "rtl", "language": "he"} if is_rtl else {}
        w = d.textlength(text, font=font, **kw)
        x = size[0] - 110 - w if is_rtl else 110
        d.text((x, y), text, font=font, fill=(25, 25, 30), **kw)
        y += int(pt * 1.7)
    stamp = ImageFont.truetype(BOLD, 34)
    d.text((size[0] - 330, size[1] - 120), "SAMPLE / דוגמה", font=stamp, fill=(200, 40, 40),
           direction="rtl", language="he")
    if photo:  # simulate a phone photo: slight rotation, blur, uneven background
        img = img.rotate(rnd.uniform(-1.5, 1.5), expand=True, fillcolor=(90, 90, 95))
        img = img.filter(ImageFilter.GaussianBlur(0.6))
    return img


def to_pdf(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=150)
    return buf.getvalue()


def text_pdf(lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 780
    for ln in lines:
        c.setFont("Helvetica-Bold" if ln.isupper() else "Helvetica", 12)
        c.drawString(60, y, ln)
        y -= 22
    c.drawString(420, 60, "SAMPLE")
    c.save()
    return buf.getvalue()


def build(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    # 1. ID card photographed — meaningless filename
    card = page([("מדינת ישראל", 44, True), ("תעודת זהות", 56, True), ("", 20, False),
                 ("מספר זהות: 123456782", 38, False), ("שם משפחה: לדוגמה", 38, False), ("שם פרטי: ישראל", 38, False),
                 ("שם האב: אברהם", 34, False), ("תאריך לידה: 14/03/1998", 34, False), ("מקום לידה: ישראל", 34, False),
                 ("תאריך הנפקה: 02/05/2022", 34, False), ("בתוקף עד: 01/05/2032", 34, False)],
                size=(1300, 900), photo=True, seed=3)
    buf = io.BytesIO()
    card.save(buf, "JPEG", quality=88)
    (out / "IMG_20261115_132411.jpg").write_bytes(buf.getvalue())
    # 1b. exact duplicate (same bytes, different name) — e.g. received again on WhatsApp
    (out / "IMG-20261102-WA0007.jpg").write_bytes(buf.getvalue())
    # 2. ID appendix
    (out / "scan_0012.pdf").write_bytes(to_pdf(page([
        ("מדינת ישראל - רשות האוכלוסין וההגירה", 34, True), ("ספח לתעודת זהות", 50, True), ("", 20, False),
        ("מספר זהות: 123456782", 32, False), ("שם: ישראל לדוגמה", 32, False), ("מען: רחוב הדוגמה 1, עיר לדוגמה", 32, False),
        ("מצב אישי: רווק", 32, False), ("תאריך הנפקה: 02/05/2022", 32, False)], seed=4)))
    # 3. Reserve duty order — scanned PDF with a meaningless name
    (out / "document_7.pdf").write_bytes(to_pdf(page([
        ("צבא הגנה לישראל", 40, True), ("צו מילואים - צו 8", 54, True), ("", 20, False),
        ("לכבוד: ישראל לדוגמה, מ.א. 1234567", 32, False), ("הנך מתבקש להתייצב לשירות מילואים פעיל", 32, False),
        ("ביום: 03/11/2026 בשעה 08:00", 32, False), ("מקום ההתייצבות: בסיס לדוגמה", 32, False),
        ("יש להביא תעודה מזהה", 30, False)], seed=5, photo=True)))
    # 4. Reserve service confirmation (form 3010)
    (out / "file_2026_10.pdf").write_bytes(to_pdf(page([
        ("צבא הגנה לישראל", 40, True), ("אישור על שירות מילואים", 52, True), ("טופס 3010", 34, False), ("", 20, False),
        ("הרינו לאשר כי ישראל לדוגמה, מספר זהות 123456782", 30, False), ("שירת ימי מילואים בתקופה:", 30, False),
        ("מתאריך 03/09/2026 עד תאריך 20/10/2026", 30, False), ("סה\"כ ימי מילואים: 48", 30, False),
        ("תאריך הפקה: 22/10/2026", 30, False)], seed=6)))
    # 5. Proof of enrollment — native-text English PDF
    (out / "download (3).pdf").write_bytes(text_pdf([
        "EXAMPLE UNIVERSITY OF TECHNOLOGY", "Office of the Registrar", "", "CERTIFICATE OF ENROLLMENT", "",
        "Date: 05/11/2026", "", "This is to certify that Israel Example (ID 123456782)",
        "is a registered student in the Faculty of Computer Science",
        "for the academic year 2026/2027, Bachelor of Science, year 2.", "",
        "This proof of enrollment is issued at the student's request.", "Registrar (sample signature)"]))
    # 6. Bank account confirmation — Hebrew scan
    (out / "Scan_20261109.pdf").write_bytes(to_pdf(page([
        ("בנק לדוגמה בע\"מ", 42, True), ("אישור ניהול חשבון", 54, True), ("", 20, False),
        ("תאריך: 09/11/2026", 32, False), ("הרינו לאשר כי החשבון שפרטיו להלן מנוהל בסניפנו:", 30, False),
        ("שם בעל החשבון: ישראל לדוגמה", 30, False), ("מספר סניף: 123", 30, False), ("מספר חשבון: 456789", 30, False),
        ("IBAN: IL62 0108 0000 0009 9999 999", 30, False)], seed=7)))
    # 7. Payslip — English text, older (should be flagged as possibly outdated)
    (out / "p_2025_06.pdf").write_bytes(text_pdf([
        "EXAMPLE SOFTWARE LTD", "PAYSLIP - June 2025", "", "Employee: Israel Example", "Pay date: 30/06/2025",
        "Gross salary: 12,000.00", "Deductions: 2,350.00", "Net salary: 9,650.00"]))
    # 8. Photo of something unrelated (should remain unclassified)
    (out / "IMG_20261001_090000.jpg").write_bytes(_jpeg(page([("Grocery list", 40, True), ("milk, eggs, bread", 34, False)],
                                                             size=(900, 700), rtl=False, seed=8)))
    return sorted(p.name for p in out.iterdir())


def _jpeg(img):
    b = io.BytesIO()
    img.save(b, "JPEG", quality=85)
    return b.getvalue()


def whatsapp_export(out: Path, src: Path):
    """A WhatsApp 'Export chat → Attach media' style zip containing the enrollment proof and a photo."""
    import zipfile
    z = out / "WhatsApp Chat with Mom.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("WhatsApp Chat with Mom.txt", "05/11/2026, 10:02 - Mom: here is the confirmation\n"
                                                "05/11/2026, 10:02 - Mom: 00000023-PHOTO-2026-11-05.jpg (file attached)\n")
        zf.write(src / "Scan_20261109.pdf", "00000024-Scan_20261109.pdf")
        zf.write(src / "IMG_20261001_090000.jpg", "00000023-PHOTO-2026-11-05.jpg")
    return z


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_docs")
    print(build(target))
