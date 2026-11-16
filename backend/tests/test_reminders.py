from datetime import date, timedelta


def test_reminders_and_ics(library, client):
    docs = library.get("/api/documents").json["documents"]
    idc = [d for d in docs if d["doc_type"] == "id_card"][0]
    soon = (date.today() + timedelta(days=20)).isoformat()
    library.patch(f"/api/documents/{idc['id']}", json={"expiry_date": soon})
    r = library.get("/api/reminders").json
    assert r["lead_days"] == 60 and r["reminders"][0]["document"]["id"] == idc["id"]
    assert r["reminders"][0]["days_left"] == 20
    assert library.get("/api/dashboard").json["reminders"][0]["state"] == "expiring"
    url = library.post("/api/reminders/calendar-link", json={"document_ids": [idc["id"]]}).json["url"]
    ics = client.get(url)
    assert ics.status_code == 200 and ics.headers["Content-Type"].startswith("text/calendar")
    body = ics.data.decode()
    assert body.startswith("BEGIN:VCALENDAR") and "BEGIN:VEVENT" in body and "תעודת זהות" in body
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))


def test_reminder_window_setting(library):
    assert library.patch("/api/me", json={"reminder_days": 7}).status_code == 400
    assert library.patch("/api/me", json={"reminder_days": 14}).status_code == 200
    docs = library.get("/api/documents").json["documents"]
    idc = [d for d in docs if d["doc_type"] == "id_card"][0]
    library.patch(f"/api/documents/{idc['id']}", json={"expiry_date": (date.today() + timedelta(days=40)).isoformat()})
    assert library.get("/api/reminders").json["reminders"] == []
