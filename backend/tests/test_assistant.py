"""The headline product flow: first request -> ask requirements -> find -> remember (with consent)
-> second request reuses the checklist -> asks what changed -> never silently edits memory."""
from docmind.assistant.intent import parse


def results(reply, i=0):
    return {r["requirement"]["doc_type"]: r for r in [b for b in reply["blocks"] if b["type"] == "requirements"][i]["results"]}


def test_intent_parser_hebrew_and_english():
    it = parse("אני צריך מסמכים למלגת מילואים")
    assert it.process_key == "reserve_scholarship" and it.lang == "he" and it.is_task
    it = parse("Identity card and appendix, reserve order, proof of enrollment, and bank account confirmation.")
    assert it.doc_types == ["id_card", "id_appendix", "reserve_order", "enrollment_proof", "bank_confirmation"]
    it = parse("תעודת זהות וספח, צו מילואים, אישור לימודים ואישור ניהול חשבון")
    assert it.doc_types == ["id_card", "id_appendix", "reserve_order", "enrollment_proof", "bank_confirmation"]
    it = parse("I need the documents for my apartment insurance claim")
    assert it.custom_purpose == "apartment insurance claim" and it.is_task
    assert parse("Find my latest bank confirmation").doc_types == ["bank_confirmation"]
    assert parse("תמצא לי את אישור ניהול החשבון").doc_types == ["bank_confirmation"]
    assert parse("איפה תעודת הזהות והספח").doc_types == ["id_card", "id_appendix"]
    assert parse("צריך את אישור הלימודים ואת תלוש השכר").doc_types == ["enrollment_proof", "payslip"]


def test_full_learning_flow_english(library):
    s = library
    r1 = s.say("I need documents for a military reserve scholarship.", new=True)
    assert "Which documents were required" in r1["text"]
    sugg = [b for b in r1["blocks"] if b["type"] == "suggestions"][0]
    assert "suggestions only" in sugg["note"]

    r2 = s.say("Identity card and appendix, reserve order, proof of enrollment, and bank account confirmation.")
    res = results(r2)
    assert set(res) == {"id_card", "id_appendix", "reserve_order", "enrollment_proof", "bank_confirmation"}
    assert all(r["status"] == "found_local" for r in res.values())
    assert res["enrollment_proof"]["best"]["document"]["original_filename"] == "download (3).pdf"
    searched = [b for b in r2["blocks"] if b["type"] == "requirements"][0]["sources_searched"]
    assert [x["key"] for x in searched] == ["device_files"]  # only what is really searchable
    assert "additional documents" in r2["text"]
    prop = [b for b in r2["blocks"] if b["type"] == "proposal"][0]["proposal"]
    assert prop["kind"] == "create_checklist"
    assert s.get("/api/memory").json["checklists"] == []  # nothing saved without consent

    r3 = s.say("yes")
    assert "Saved" in r3["text"]
    cl = s.get("/api/memory").json["checklists"]
    assert len(cl) == 1 and len(cl[0]["items"]) == 5

    # Second application: checklist reused automatically.
    r4 = s.say("I need to submit another military reserve scholarship application.", new=True)
    assert "saved checklist" in r4["text"] and "anything changed" in r4["text"]
    assert set(results(r4)) == set(results(r2))
    assert not [b for b in r4["blocks"] if b["type"] == "proposal"]
    # Suggestions beyond the checklist are labelled as suggestions.
    sugg = [b for b in r4["blocks"] if b["type"] == "suggestions"][0]
    assert sugg["items"][0]["doc_type"] == "reserve_service_confirmation"

    # User adds a requirement: searched, but checklist only changes after confirmation.
    r5 = s.say("also the reserve service confirmation")
    assert results(r5)["reserve_service_confirmation"]["status"] == "found_local"
    assert [b for b in r5["blocks"] if b["type"] == "proposal"][0]["proposal"]["kind"] == "update_checklist"
    assert len(s.get("/api/memory").json["checklists"][0]["items"]) == 5
    s.say("yes")
    assert len(s.get("/api/memory").json["checklists"][0]["items"]) == 6


def test_full_flow_hebrew(library):
    s = library
    r1 = s.say("אני צריך מסמכים למלגת מילואים", new=True)
    assert r1["lang"] == "he" and "אילו מסמכים" in r1["text"]
    r2 = s.say("תעודת זהות וספח, צו מילואים, אישור לימודים ואישור ניהול חשבון")
    assert all(r["status"] == "found_local" for r in results(r2).values())
    s.say("כן")
    r3 = s.say("צריך להגיש שוב מלגת מילואים", new=True)
    assert "ברשימה השמורה" in r3["text"]


def test_not_found_after_search_gets_official_source(library):
    r = library.say("find my passport and my transcript", new=True)
    res = results(r)
    for dt in ("passport", "transcript"):
        assert res[dt]["status"] == "not_found"
        assert res[dt]["acquisition"]["source"]
    assert res["passport"]["acquisition"]["url"] == "https://www.gov.il"
    assert "url" not in res["transcript"]["acquisition"]  # no invented links


def test_outdated_document_flagged(library):
    r = library.say("find my payslip", new=True)
    res = results(r)["payslip"]
    assert res["status"] == "found_local" and res["freshness"]["state"] == "maybe_outdated"
    assert "outdated" in r["text"]


def test_custom_task_learning(library):
    s = library
    r = s.say("I need the documents for my apartment insurance claim", new=True)
    assert "apartment insurance claim" in r["text"]
    s.say("identity card and bank confirmation")
    s.say("yes")
    r2 = s.say("Prepare everything for my apartment insurance claim", new=True)
    assert "saved checklist" in r2["text"]
    assert set(results(r2)) == {"id_card", "bank_confirmation"}


def test_suggestions_can_be_accepted(library):
    s = library
    s.say("I need documents for my reserve benefits", new=True)
    r = s.say("yes")
    assert set(results(r)) == {"id_card", "reserve_service_confirmation", "reserve_order", "bank_confirmation"}


def test_free_text_content_search(library):
    r = library.say("the letter from the registrar", new=True)
    docs = [b for b in r["blocks"] if b["type"] == "documents"][0]["documents"]
    assert docs[0]["original_filename"] == "download (3).pdf"


def test_empty_library_message(session):
    r = session.say("something from last year", new=True)
    assert "empty" in r["text"] or "ריקה" in r["text"]


def test_conversation_history_encrypted_and_listed(library, ctx):
    library.say("find my identity card", new=True)
    convs = library.get("/api/conversations").json["conversations"]
    msgs = library.get(f"/api/conversations/{convs[0]['id']}").json["messages"]
    assert msgs[0]["text"] == "find my identity card" and msgs[1]["payload"]["blocks"]
    raw = ctx.db.one("SELECT content_enc FROM messages LIMIT 1")["content_enc"]
    assert b"identity" not in raw


def test_memory_inspect_edit_delete(library):
    s = library
    s.say("documents for university registration", new=True)
    s.say("identity card, diploma")
    s.say("yes")
    cl = s.get("/api/memory").json["checklists"][0]
    r = s.patch(f"/api/memory/checklists/{cl['id']}", json={"name": "Uni registration", "items": cl["items"][:1]})
    assert r.json["checklist"]["name"] == "Uni registration" and r.json["checklist"]["version"] == 2
    assert s.delete(f"/api/memory/checklists/{cl['id']}").status_code == 200
    assert s.get("/api/memory").json["checklists"] == []


def test_find_during_task_does_not_touch_checklist(library):
    s = library
    s.say("documents for university registration", new=True)
    s.say("identity card, diploma")
    s.say("yes")
    s.say("Prepare everything for university registration", new=True)
    r = s.say("find my passport")
    assert not [b for b in r["blocks"] if b["type"] == "proposal"]
    r = s.say("also my passport")
    assert [b for b in r["blocks"] if b["type"] == "proposal"][0]["proposal"]["kind"] == "update_checklist"


def test_catalog_is_consistent():
    from docmind.knowledge.catalog import ACQUISITION, DOC_TYPES, PROCESSES, REQUEST_ALIASES
    assert set(DOC_TYPES) == set(ACQUISITION) == set(REQUEST_ALIASES)
    for p in PROCESSES.values():
        assert p["triggers"] and all(d in DOC_TYPES for d in p["suggested"])
    for a in ACQUISITION.values():  # only the one official domain we are sure about
        assert a.get("url") in (None, "https://www.gov.il")
        assert a["he"]["source"] and a["en"]["how"]


def test_new_processes_and_types_parse():
    assert parse("אני צריך מסמכים לדמי אבטלה").process_key == "unemployment_benefits"
    assert parse("I need documents for a mortgage").process_key == "mortgage"
    assert parse("מה צריך להנחה בארנונה").process_key == "arnona_discount"
    assert parse("find my vehicle license and marriage certificate").doc_types == ["vehicle_license", "marriage_certificate"]
