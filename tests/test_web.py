"""HTTP layer: webhook signatures, the public simulator, and the form agent pages."""

import base64
import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from server import create_app
from tests.conftest import make_deps, with_settings


def signed(body: dict, secret: str = "test-secret") -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    sig = base64.b64encode(hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode()
    return raw, {"x-line-signature": sig, "content-type": "application/json"}


def test_webhook_rejects_bad_signatures():
    client = TestClient(create_app(make_deps()))
    raw, headers = signed({"events": []}, secret="wrong")
    assert client.post("/webhook", content=raw, headers=headers).status_code == 400
    assert client.post("/webhook", content=raw).status_code == 400


def test_webhook_accepts_lines_verify_request():
    client = TestClient(create_app(make_deps()))
    raw, headers = signed({"destination": "U0", "events": []})
    assert client.post("/webhook", content=raw, headers=headers).json() == {"ok": True}


def test_webhook_handles_a_signed_join():
    deps = make_deps()
    client = TestClient(create_app(deps))
    raw, headers = signed({"events": [{"type": "join", "webhookEventId": "e1", "replyToken": "rt",
                                       "source": {"type": "group", "groupId": "C9"}}]})
    assert client.post("/webhook", content=raw, headers=headers).status_code == 200
    assert "有効化" in deps.line.replies[0]["messages"][0]["altText"]


def test_simulator_replays_without_the_llm():
    deps = make_deps()
    client = TestClient(create_app(deps))
    data = client.post("/api/scenario", json={"scenario_id": "tokyo_meat_4"}).json()
    assert data["session_state"]["midpoint_data"]["hub_station"] == "秋葉原"
    assert data["bot_messages"][1]["flex"]["contents"]["type"] == "carousel"
    assert data["session_state"]["schedule_data"]["details"]["source"] == "rules"
    # the hub is cached, so a second visitor costs no Ekispert call
    before = len([c for c in deps.ekispert.calls if c[0] == "ranges"])
    client.post("/api/scenario", json={"scenario_id": "tokyo_meat_4"})
    assert len([c for c in deps.ekispert.calls if c[0] == "ranges"]) == before


def test_simulator_daily_cap():
    deps = make_deps()
    deps.usage._limits["simulator"] = 1
    client = TestClient(create_app(deps))
    assert client.post("/api/scenario", json={"scenario_id": "cafe_girls_3"}).status_code == 200
    assert client.post("/api/scenario", json={"scenario_id": "cafe_girls_3"}).status_code == 429


def test_free_text_chat_needs_the_admin_token():
    client = TestClient(create_app(make_deps()))
    body = {"messages": [{"sender": "A", "text": "横浜から"}]}
    assert client.post("/api/chat", json=body).status_code == 403
    assert client.post("/api/chat", json=body, headers={"x-admin-token": "nope"}).status_code == 403
    assert client.post("/api/chat", json=body, headers={"x-admin-token": "admin-token"}).status_code == 200


def test_reserve_returns_a_script_not_a_fake_booking():
    client = TestClient(create_app(make_deps()))
    data = client.post("/api/reserve", json={"venue_id": "J000000001",
                                             "plan": {"day": "土曜", "time": "13:00", "pax": 4, "organizer": "佐藤"}}).json()
    assert "4名" in data["script"]["lines"][0]
    assert "まだ予約は完了していません" in json.dumps(data["bot_messages"], ensure_ascii=False)
    assert client.post("/api/reserve", json={"venue_id": "../../etc"}).status_code == 400


class FakeRunner:
    def __init__(self):
        self.launched = []

    async def launch(self, run_id):
        self.launched.append(run_id)
        return True


def test_agent_link_runs_once_and_expires():
    deps = with_settings(make_deps(), form_agent_mode="job")
    deps.form_agent = FakeRunner()
    client = TestClient(create_app(deps))
    data = client.post("/api/reserve", json={"venue_id": "J000000001", "plan": {"pax": 2}}).json()
    path = data["agent_url"].replace("https://asobi.example", "")
    assert client.get(path).status_code == 200
    assert client.post(path + "/start").json()["status"] == "queued"
    assert client.post(path + "/start").json()["status"] == "queued"
    assert len(deps.form_agent.launched) == 1
    deps.clock.advance(2 * 86400)
    assert client.get(path).status_code == 404
    assert client.get("/agent/garbage.token").status_code == 404


def test_demo_venue_form_round_trip():
    client = TestClient(create_app(make_deps()))
    page = client.get("/demo-venue/J000000001?n=テスト店").text
    assert "デモ店舗" in page and 'name="visit_date"' in page
    done = client.post("/demo-venue/J000000001", data={"visit_date": "2026-10-17", "visit_time": "13:00",
                                                       "guests": "4", "guest_name": "佐藤"}).text
    assert "data-confirmation" in done and "4名" in done
