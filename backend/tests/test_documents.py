from datetime import date

from docmind.services import classifier


def by_name(docs):
    return {d["original_filename"]: d for d in docs}


def test_classification_of_unclear_filenames(library):
    docs = by_name(library.get("/api/documents").json["documents"])
    expected = {
        "IMG_20261115_132411.jpg": ("id_card", "identity"),
        "scan_0012.pdf": ("id_appendix", "identity"),
        "document_7.pdf": ("reserve_order", "military"),
        "file_2026_10.pdf": ("reserve_service_confirmation", "military"),
        "download (3).pdf": ("enrollment_proof", "education"),
        "Scan_20261109.pdf": ("bank_confirmation", "finance"),
        "p_2025_06.pdf": ("payslip", "employment"),
        "IMG_20261001_090000.jpg": ("unknown", "other"),
    }
    for name, (dt, cat) in expected.items():
        assert docs[name]["status"] == "ready", (name, docs[name]["error"])
        assert (docs[name]["doc_type"], docs[name]["category_key"]) == (dt, cat), name


def test_ocr_and_smart_names(library):
    docs = by_name(library.get("/api/documents").json["documents"])
    idc = docs["IMG_20261115_132411.jpg"]
    assert idc["ocr_used"] and idc["language"] == "he"
    assert idc["display_name"] == "תעודת זהות"
    assert idc["expiry_date"] == "2032-05-01"
    order = docs["document_7.pdf"]
    assert order["issuer"] == "IDF" and order["display_name"] == "צו מילואים · IDF"


def test_exact_duplicate_detected_and_never_auto_deleted(library):
    dup = library.upload("IMG-20261102-WA0007.jpg")[0]
    assert dup["duplicate_kind"] == "exact" and dup["duplicate_of"]
    r = library.post(f"/api/documents/{dup['id']}/duplicate", json={"action": "archive_this"})
    assert r.json["document"]["archived"] is True
    # Original untouched, archived copy still retrievable.
    assert library.get(f"/api/documents/{dup['duplicate_of']}").status_code == 200
    assert library.get(f"/api/documents/{dup['id']}").status_code == 200


def test_search_hebrew_english_and_content(library):
    def top(q):
        return library.get("/api/documents", query_string={"q": q}).json["documents"][0]["original_filename"]
    assert top("אישור לימודים") == "download (3).pdf"
    assert top("proof of enrollment") == "download (3).pdf"
    assert top("ניהול חשבון בנק") == "Scan_20261109.pdf"
    assert top("צו 8") == "document_7.pdf"
    assert top("registrar faculty of computer science") == "download (3).pdf"  # body text only


def test_filters(library):
    mil = library.get("/api/documents", query_string={"category": "military"}).json["documents"]
    assert {d["doc_type"] for d in mil} == {"reserve_order", "reserve_service_confirmation"}
    recent = library.get("/api/documents", query_string={"from": "2026-01-01"}).json["documents"]
    assert "p_2025_06.pdf" not in {d["original_filename"] for d in recent}


def test_manual_correction_teaches_classifier(library):
    docs = by_name(library.get("/api/documents").json["documents"])
    grocery = docs["IMG_20261001_090000.jpg"]
    r = library.patch(f"/api/documents/{grocery['id']}", json={"doc_type": "invoice_receipt", "tags": ["home"]})
    assert r.json["document"]["doc_type_source"] == "user" and r.json["document"]["category_key"] == "finance"
    # A near-identical new document now inherits the user's label.
    import io
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (900, 700), "white")
    ImageDraw.Draw(img).text((100, 120), "Grocery list\nmilk, eggs, bread, apples",
                             font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40), fill="black")
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    r = library.post("/api/documents", data={"files": [(io.BytesIO(buf.getvalue()), "IMG_1.jpg")]},
                     content_type="multipart/form-data")
    assert r.json["documents"][0]["id"]
    new = library.get(f"/api/documents/{r.json['documents'][0]['id']}").json["document"]
    assert new["doc_type"] == "invoice_receipt"


def test_freshness_flags():
    old_payslip = {"doc_type": "payslip", "doc_date": "2025-06-30"}
    assert classifier.freshness(old_payslip, date(2026, 11, 16))["state"] == "maybe_outdated"
    expired = {"doc_type": "passport", "expiry_date": "2026-01-01"}
    assert classifier.freshness(expired, date(2026, 11, 16))["state"] == "expired"
    assert classifier.freshness({"doc_type": "id_card", "doc_date": "2010-01-01"}, date(2026, 11, 16))["state"] == "ok"


def test_israeli_id_checksum():
    assert classifier.valid_israeli_id("123456782")
    assert not classifier.valid_israeli_id("123456789")


def test_whatsapp_export_import(session, tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from make_sample_docs import whatsapp_export
    z = whatsapp_export(tmp_path, Path(__file__).parent / "fixtures")
    r = session.post("/api/import/whatsapp", data={"file": (open(z, "rb"), z.name)}, content_type="multipart/form-data")
    assert r.status_code == 201 and len(r.json["imported"]) == 2 and r.json["chat"] == "Mom"
    docs = session.get("/api/documents", query_string={"source": "whatsapp_import"}).json["documents"]
    assert {d["doc_type"] for d in docs} == {"bank_confirmation", "unknown"}


def test_delete_requires_confirmation(library, ctx):
    doc = library.get("/api/documents").json["documents"][0]
    assert library.delete(f"/api/documents/{doc['id']}", json={}).status_code == 400
    assert library.delete(f"/api/documents/{doc['id']}", json={"confirm": True}).status_code == 200
    assert library.get(f"/api/documents/{doc['id']}").status_code == 404
