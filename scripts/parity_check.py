"""Checks that the phone edition (JS) classifies documents and understands requests exactly like the server (Python),
and that mobile/js/catalog.js is up to date. Run: python scripts/parity_check.py"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from docmind.assistant.intent import parse  # noqa: E402
from docmind.services import classifier, extract  # noqa: E402

before = (root / "mobile/js/catalog.js").read_text(encoding="utf-8")
subprocess.run([sys.executable, str(root / "scripts/export_catalog.py")], check=True, capture_output=True)
if (root / "mobile/js/catalog.js").read_text(encoding="utf-8") != before:
    sys.exit("mobile/js/catalog.js was stale: regenerated it, commit the change")

out = {"docs": [], "intents": []}
for p in sorted((root / "backend/tests/fixtures").iterdir()):
    d = p.read_bytes()
    ex = extract.extract_text(d, extract.sniff_mime(d, p.name))
    c = classifier.classify(ex.text, p.name)
    out["docs"].append({"name": p.name, "text": ex.text, "py": [c.doc_type, c.issuer, c.doc_date, c.expiry_date]})
for t in ["אני צריך מסמכים למלגת מילואים", "Identity card and appendix, reserve order, proof of enrollment, and bank account confirmation.",
          "תעודת זהות וספח, צו מילואים, אישור לימודים ואישור ניהול חשבון", "I need the documents for my apartment insurance claim",
          "Find my latest bank confirmation", "צריך להגיש שוב מלגת מילואים", "also the reserve service confirmation", "find my passport",
          "כן", "זה הכל", "מה צריך להנחה בארנונה", "find my vehicle license and marriage certificate", "I need documents for a mortgage",
          "תמצא לי את אישור ניהול החשבון", "איפה תעודת הזהות והספח", "צריך את אישור הלימודים ואת תלוש השכר"]:
    i = parse(t)
    out["intents"].append({"t": t, "py": [i.process_key, i.doc_types, i.custom_purpose, i.yes, i.no, i.nothing_more, i.adding, i.find_only, i.lang]})

js = f"""
import fs from "fs";
import {{ classify }} from "{root}/mobile/js/core/classifier.js";
import {{ parse }} from "{root}/mobile/js/core/intent.js";
const d = JSON.parse(fs.readFileSync(process.argv[2], "utf8")); let bad = 0;
for (const x of d.docs) {{ const c = classify(x.text, x.name); const r = [c.doc_type, c.issuer, c.doc_date, c.expiry_date];
  if (JSON.stringify(r) !== JSON.stringify(x.py)) {{ bad++; console.log("DOC", x.name, x.py, r); }} }}
for (const x of d.intents) {{ const i = parse(x.t); const r = [i.process_key, i.doc_types, i.custom_purpose, i.yes, i.no, i.nothing_more, i.adding, i.find_only, i.lang];
  if (JSON.stringify(r) !== JSON.stringify(x.py)) {{ bad++; console.log("INTENT", x.t, JSON.stringify(x.py), JSON.stringify(r)); }} }}
console.log(bad ? bad + " mismatches" : `parity OK: ${{d.docs.length}} documents, ${{d.intents.length}} requests`); process.exit(bad ? 1 : 0);
"""
with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "data.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    (Path(tmp) / "check.mjs").write_text(js, encoding="utf-8")
    sys.exit(subprocess.run(["node", str(Path(tmp) / "check.mjs"), str(Path(tmp) / "data.json")]).returncode)
