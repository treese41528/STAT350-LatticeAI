"""HTTP-level tests: identity, deterministic SSE turns, CRUD, feedback,
admin auth. Runs against the degraded app (no gateway key needed)."""

from __future__ import annotations

import re


import time


def _events(sse_text: str) -> list[tuple[str, str]]:
    return re.findall(r"event: (\w+)\ndata: (.*)", sse_text)


def _h(device_id: str) -> dict:
    return {"X-Device-Id": device_id}


def _wait_for_messages(client, headers: dict, cid: str, n: int,
                       timeout: float = 3.0) -> dict:
    """Message rows land via the async recorder (~250ms batches) — poll."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail = client.get(f"/api/conversations/{cid}", headers=headers).json()
        if len(detail.get("messages", [])) >= n:
            return detail
        time.sleep(0.15)
    raise AssertionError(f"conversation {cid} never reached {n} messages: "
                         f"{detail}")


def test_identity_cookie_binding(client, device_id):
    r = client.get("/api/profile", headers=_h(device_id))
    assert r.status_code == 200
    assert "stat350_device" in r.cookies or client.cookies.get("stat350_device")
    # header/cookie mismatch is rejected (cookie is authoritative)
    r2 = client.get("/api/profile",
                    headers=_h("11111111-2222-3333-4444-555555555555"))
    assert r2.status_code == 401
    # matching pair still fine
    assert client.get("/api/profile", headers=_h(device_id)).status_code == 200


def test_identity_requires_header(client):
    assert client.get("/api/conversations").status_code == 401
    assert client.get("/api/conversations",
                      headers=_h("not a uuid!!")).status_code == 401


def test_profile_roundtrip(client, device_id):
    r = client.patch("/api/profile", headers=_h(device_id),
                     json={"modality": "flipped"})
    assert r.json() == {"modality": "flipped"}
    assert client.get("/api/profile",
                      headers=_h(device_id)).json()["modality"] == "flipped"


def test_chat_worksheet_lookup_sse(client, device_id):
    r = client.post("/api/chat", headers=_h(device_id),
                    json={"conversationId": None,
                          "message": "show me worksheet 5 please"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    names = [e for e, _ in _events(r.text)]
    assert names[0] == "meta"
    assert "resources" in names and names[-1] == "done"
    assert "worksheet5.html" in r.text


def test_chat_exam_info_sse(client, device_id):
    r = client.post("/api/chat", headers=_h(device_id),
                    json={"conversationId": None, "message": "what's on exam 2?"})
    body = r.text
    assert "Sampling Distributions" in body       # ch 7 topic from course map
    assert "exams_index.html" in body


def test_chat_syllabus_asks_modality_then_answers(client, device_id):
    r = client.post("/api/chat", headers=_h(device_id),
                    json={"conversationId": None, "message": "where is the syllabus?"})
    assert "Which section" in r.text
    client.patch("/api/profile", headers=_h(device_id),
                 json={"modality": "winter"})
    r2 = client.post("/api/chat", headers=_h(device_id),
                     json={"conversationId": None, "message": "where is the syllabus?"})
    assert "Winter" in r2.text and "Syllabus%20Winter" in r2.text


def test_chat_concept_degrades_without_gateway(client, device_id):
    r = client.post("/api/chat", headers=_h(device_id),
                    json={"conversationId": None,
                          "message": "why do we divide by n-1 in sample variance?"})
    names = [e for e, _ in _events(r.text)]
    assert "error" in names           # gateway_unavailable, honest
    assert "gateway_unavailable" in r.text


def test_conversation_crud_and_isolation(client, device_id):
    r = client.post("/api/chat", headers=_h(device_id),
                    json={"conversationId": None, "message": "link to worksheet 3"})
    cid = re.search(r'"conversationId": "([^"]+)"', r.text).group(1)

    listing = client.get("/api/conversations", headers=_h(device_id)).json()
    assert [c["id"] for c in listing] == [cid]

    detail = _wait_for_messages(client, _h(device_id), cid, 2)
    roles = [msg["role"] for msg in detail["messages"]]
    assert roles == ["user", "assistant"]

    renamed = client.patch(f"/api/conversations/{cid}", headers=_h(device_id),
                           json={"title": "Bayes practice"}).json()
    assert renamed["title"] == "Bayes practice"

    # another device cannot see or touch it — use a fresh client so the
    # first device's cookie doesn't ride along
    from fastapi.testclient import TestClient
    with TestClient(client.app) as other:
        other_h = _h("99999999-8888-7777-6666-555555555555")
        assert other.get(f"/api/conversations/{cid}",
                         headers=other_h).status_code == 404
        assert other.delete(f"/api/conversations/{cid}",
                            headers=other_h).status_code == 404

    assert client.delete(f"/api/conversations/{cid}",
                         headers=_h(device_id)).status_code == 204
    assert client.get("/api/conversations", headers=_h(device_id)).json() == []


def test_feedback_flow(client, device_id):
    r = client.post("/api/chat", headers=_h(device_id),
                    json={"conversationId": None, "message": "link to worksheet 3"})
    mid = re.search(r'"messageId": "([^"]+)"', r.text).group(1)
    cid = re.search(r'"conversationId": "([^"]+)"', r.text).group(1)
    _wait_for_messages(client, _h(device_id), cid, 2)  # recorder flush

    bad = client.post(f"/api/messages/{mid}/feedback", headers=_h(device_id),
                      json={"rating": "down", "tags": []})
    assert bad.status_code == 422

    ok = client.post(f"/api/messages/{mid}/feedback", headers=_h(device_id),
                     json={"rating": "down", "tags": ["broken-link"],
                           "comment": "went to the wrong worksheet"})
    assert ok.status_code == 204
    # upsert
    again = client.post(f"/api/messages/{mid}/feedback", headers=_h(device_id),
                        json={"rating": "up", "tags": ["clear"]})
    assert again.status_code == 204


def test_message_too_long(client, device_id):
    r = client.post("/api/chat", headers=_h(device_id),
                    json={"conversationId": None, "message": "x" * 5000})
    assert r.status_code == 413


def test_admin_requires_token(client, device_id):
    assert client.get("/admin/api/overview").status_code == 401
    r = client.get("/admin/api/overview",
                   headers={"Authorization": "Bearer test-admin-token"})
    assert r.status_code == 200
    csv_r = client.get("/admin/api/weak-retrievals?format=csv",
                       headers={"Authorization": "Bearer test-admin-token"})
    assert csv_r.status_code == 200


def test_spa_route_blocks_path_traversal(client):
    # app_static/ has a real build in this checkout, so the SPA catch-all is
    # active. Percent-encoded traversal must NOT escape the static dir.
    for path in ("/%2e%2e/%2e%2e/etc/passwd",
                 "/..%2f..%2fconfig.yaml",
                 "/%2e%2e%2fapp%2fmain.py"):
        r = client.get(path)
        # served the SPA index (fallback), never the traversed file
        assert r.status_code == 200
        assert "root-outside" not in r.text.lower()
        assert "GENAI_STUDIO_API_KEY" not in r.text  # never leak config
        assert "<!doctype html" in r.text.lower() or "<html" in r.text.lower()


def test_identity_reset_clears_cookie(client, device_id):
    # bind a cookie, then reset should let a *new* device id work again
    client.get("/api/profile", headers=_h(device_id))
    r = client.post("/api/identity/reset")
    assert r.status_code == 204
    client.cookies.clear()  # emulate the browser dropping the deleted cookie
    new_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert client.get("/api/profile", headers=_h(new_id)).status_code == 200


def test_ui_events_accepted(client, device_id):
    r = client.post("/api/events", headers=_h(device_id),
                    json={"events": [
                        {"type": "resource_card_click",
                         "payload": {"target": "worksheet5"}},
                        {"type": "not_a_real_event", "payload": {}}]})
    assert r.status_code == 204
