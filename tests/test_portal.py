import re

from tests.conftest import login


def _upload_query(client, csrf, patient_id, path):
    with open(path, "rb") as fh:
        r = client.post(f"/patients/{patient_id}/queries", data={"csrf_token": csrf},
                        files={"file": (path.name, fh, "application/pdf")}, follow_redirects=False)
    assert r.status_code == 303
    return int(r.headers["location"].rsplit("/", 1)[1])


def test_query_upload_runs_end_to_end(client, seeded):
    csrf = login(client, "staff", "staff12345")
    qid = _upload_query(client, csrf, 1, seeded / "query_letters" / "PT-0001_query_letter.pdf")
    data = client.get(f"/queries/{qid}/status").json()
    assert data["status"] == "sent"
    page = client.get(f"/queries/{qid}").text
    assert page.count('class="stamp needed"') == 3
    assert page.count('class="stamp available"') == 2
    assert "Not sent (test mode)" in page  # both channels recorded in console mode
    from app.db import session_scope
    from app.models import Message, QueryLetter

    with session_scope() as db:
        msgs = db.query(Message).filter(Message.query_id == qid).all()
        assert {m.channel for m in msgs} == {"whatsapp", "email"}
        assert "itemised final hospital bill" in msgs[0].body
        assert "KYC" in msgs[0].body  # listed as already held, not requested
        assert db.get(QueryLetter, qid).seconds_to_send is not None


def test_all_available_sends_no_action_message(client, seeded):
    csrf = login(client, "staff", "staff12345")
    qid = _upload_query(client, csrf, 7, seeded / "query_letters" / "PT-0007_query_letter.pdf")
    assert client.get(f"/queries/{qid}/status").json()["status"] == "no_action"


def test_upload_missing_doc_resolves_point(client, seeded, tmp_path):
    csrf = login(client, "staff", "staff12345")
    qid = _upload_query(client, csrf, 9, seeded / "query_letters" / "PT-0009_query_letter.pdf")
    assert client.get(f"/queries/{qid}/status").json()["status"] in ("no_action", "sent")
    # PT-0002 lacks a cancelled cheque; ask, then upload it and watch the point resolve
    qid2 = _upload_query(client, csrf, 2, seeded / "query_letters" / "PT-0002_query_letter.pdf")
    before = client.get(f"/queries/{qid2}").text.count('class="stamp needed"')
    f = tmp_path / "cheque.txt"
    f.write_text("State Bank of India\nCANCELLED\nPay to Priya Mehta\nIFSC SBIN0000001\nA/c No 123456789012")
    with open(f, "rb") as fh:
        client.post("/patients/2/documents", data={"csrf_token": csrf}, files={"files": ("cheque.txt", fh, "text/plain")})
    after = client.get(f"/queries/{qid2}").text
    assert after.count('class="stamp needed"') == before - 1
    assert 'class="stamp resolved"' in after


def test_duplicate_document_not_added_twice(client, seeded, tmp_path):
    csrf = login(client, "staff", "staff12345")
    f = tmp_path / "note.txt"
    f.write_text("Laboratory report CBC haemoglobin reference range")
    for _ in range(2):
        with open(f, "rb") as fh:
            client.post("/patients/3/documents", data={"csrf_token": csrf}, files={"files": ("note.txt", fh, "text/plain")})
    page = client.get("/patients/3").text
    assert page.count(">note.txt<") == 1


def test_patient_sees_only_own_locker(client, seeded):
    login(client, "pt-0001", "patient12345")
    assert client.get("/patients/1").status_code == 200
    assert client.get("/patients/2").status_code == 404
    assert client.get("/dashboard").status_code == 403
    assert client.get("/settings").status_code == 403
    from app.db import session_scope
    from app.models import Document

    with session_scope() as db:
        other = db.query(Document).filter(Document.patient_id == 2).first().id
        mine = db.query(Document).filter(Document.patient_id == 1).first().id
    assert client.get(f"/documents/{other}/file").status_code == 404
    assert client.get(f"/documents/{mine}/file").status_code == 200


def test_staff_cannot_open_admin_pages(client, seeded):
    login(client, "staff", "staff12345")
    assert client.get("/settings").status_code == 403
    assert client.get("/audit").status_code == 403


def test_anonymous_redirected_and_files_protected(client, seeded):
    client.cookies.clear()
    r = client.get("/patients/1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert client.get("/documents/1/file", follow_redirects=False).status_code == 303


def test_csrf_required(client, seeded):
    login(client, "staff", "staff12345")
    r = client.post("/patients/1/documents", data={"csrf_token": "wrong"}, files={"files": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 400


def test_api_requires_key_and_works(client, seeded):
    path = seeded / "query_letters" / "PT-0005_query_letter.pdf"
    with open(path, "rb") as fh:
        assert client.post("/api/v1/patients/PT-0005/query-letters", files={"file": (path.name, fh)}).status_code == 401
    with open(path, "rb") as fh:
        r = client.post("/api/v1/patients/PT-0005/query-letters", files={"file": (path.name, fh)},
                        headers={"X-API-Key": "test-api-key"})
    qid = r.json()["query_id"]
    out = client.get(f"/api/v1/query-letters/{qid}", headers={"X-API-Key": "test-api-key"}).json()
    decisions = {p["ref"]: p["decision"] for p in out["points"]}
    assert decisions == {"1": "needed", "2": "needed", "3": "available", "4": "needed", "5": "needed"}


def test_admin_pages_render(client, seeded):
    login(client, "admin", "admin12345")
    for url in ("/dashboard", "/settings", "/audit", "/patients/1", "/patients/new", "/patients/1/edit"):
        assert client.get(url).status_code == 200, url
    assert re.search(r"document opened|viewed patient", client.get("/audit").text)
