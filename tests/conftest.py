import dataclasses
import os
import sys
from typing import Any, Optional

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.deps import Deps  # noqa: E402
from config import Settings  # noqa: E402
from services.ids import Ids  # noqa: E402
from services.line_api import RecordingLineApi  # noqa: E402
from services.llm_client import LLMClient  # noqa: E402
from services.stations import StationResolver  # noqa: E402
from services.store import MemoryStore  # noqa: E402
from services.usage import Usage  # noqa: E402

ADMIN = "Uadmin000000000000000000000000000"

STATIONS = {
    "横浜": {"name": "横浜", "code": "23368", "pref_code": "14", "lat": 35.46547, "lng": 139.621257},
    "吉祥寺": {"name": "吉祥寺", "code": "22637", "pref_code": "13", "lat": 35.703, "lng": 139.5797},
    "中目黒": {"name": "中目黒", "code": "22855", "pref_code": "13", "lat": 35.6442, "lng": 139.6990},
    "柏": {"name": "柏", "code": "22228", "pref_code": "12", "lat": 35.8621, "lng": 139.970932},
    "秋葉原": {"name": "秋葉原", "code": "22492", "pref_code": "13", "lat": 35.698353, "lng": 139.773114},
}


def shop(i: int, **extra: Any) -> dict[str, Any]:
    base = {"id": f"J00000000{i}", "name": f"テスト店{i}", "address": "東京都千代田区", "station_name": "秋葉原",
            "lat": 35.6984 + i * 0.001, "lng": 139.7731, "genre": "居酒屋", "genre_code": "G001", "genre_catch": "",
            "sub_genre": None, "budget": "3001～4000円", "budget_average": "3500円", "catch": "テスト",
            "capacity": 40, "party_capacity": 30, "private_room": "あり" if i % 2 else "なし", "non_smoking": "",
            "lunch": "あり", "open": "月～日: 11:00～23:00", "close": "なし",
            "url": f"https://www.hotpepper.jp/strJ00000000{i}/", "photo": f"https://imgfp.hotp.jp/{i}.jpg",
            "access": ""}
    base.update(extra)
    return base


class FakeEkispert:
    def __init__(self):
        self.calls: list[tuple[str, Any]] = []

    async def find_stations(self, name: str) -> list[dict[str, Any]]:
        self.calls.append(("find", name))
        return [STATIONS[name]] if name in STATIONS else []

    async def station_by_code(self, code: str) -> Optional[dict[str, Any]]:
        self.calls.append(("code", code))
        return next((s for s in STATIONS.values() if s["code"] == code), None)

    async def stations_near(self, lat, lng, count=3, radius_m=2000):
        return [dict(STATIONS["中目黒"], distance_m=14), dict(STATIONS["秋葉原"], distance_m=900)][:count]

    async def search_ranges(self, names: list[str], upper_minutes: int, upper_transfers: int = 2):
        self.calls.append(("ranges", tuple(names)))
        table = {"横浜": 42, "吉祥寺": 39, "中目黒": 40, "柏": 44}
        return [{"name": "秋葉原", "code": "22492", "prefecture": "東京都",
                 "minutes": [table.get(n, 30) for n in names], "transfers": [1 for _ in names]},
                {"name": "上野", "code": "22528", "prefecture": "東京都",
                 "minutes": [44 + (i % 2) * 3 for i, _ in enumerate(names)], "transfers": [0 for _ in names]}]


class FakeHotPepper:
    def __init__(self, count: int = 12):
        self.shops = {s["id"]: s for s in (shop(i) for i in range(1, count + 1))}
        self.searches: list[dict[str, Any]] = []

    async def search(self, lat, lng, **kwargs):
        self.searches.append(kwargs)
        shops = list(self.shops.values())
        if kwargs.get("budget"):
            shops = shops[6:]
        return [dict(s) for s in shops]

    async def shops_by_ids(self, ids):
        return {i: dict(self.shops[i]) for i in ids if i in self.shops}


class FakePlaces:
    def __init__(self):
        self.calls = 0

    async def phone_number(self, name, address, lat, lng):
        self.calls += 1
        return "03-1234-5678"

    async def find_place(self, name, lat, lng, radius_m=2000):
        if name != "知らない店":
            return None
        return {"place_id": "pl1", "name": "知らない店", "address": "東京都千代田区", "telephone": "03-5555-0000",
                "lat": 35.6990, "lng": 139.7735, "url": "https://maps.google.com/?cid=1", "genre": "レストラン"}


class Clock:
    def __init__(self, now: float = 1_790_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_settings(**overrides: Any) -> Settings:
    base = dict(
        on_cloud_run=False, public_base_url="https://asobi.example", line_channel_secret="test-secret",
        line_channel_access_token="", line_admin_user_id=ADMIN, line_bot_basic_id="@test",
        line_login_channel_id="1234567890", liff_id="1234567890-abcdefgh",
        vertex_project="", vertex_location="", vertex_model="",
        gmi_api_key="", gmi_base_url="", gmi_model="", ekispert_api_key="k", ekispert_mcp_url="",
        hotpepper_api_key="k", places_api_key="k", app_secret="test-app-secret", admin_api_token="admin-token",
        store_backend="memory", gcp_project="", region="asia-northeast1", form_agent_mode="off",
        form_agent_job="asobi-form-agent", plans_per_group=1, searches_per_group=3, group_active_days=7,
        activation_window_hours=24, max_participants=10, groups_per_user=2, daily_search_limit=100,
        daily_llm_limit=300, daily_places_limit=30, daily_simulator_limit=60, daily_agent_limit=20,
        invite_ttl_days=14, judge_code_days=60, held_messages_max=50, group_retention_days=90,
    )
    base.update(overrides)
    return Settings(**base)


def make_deps(**overrides: Any) -> Deps:
    clock = Clock()
    settings = make_settings(**overrides)
    store = MemoryStore(clock=clock)
    usage = Usage(store, {"searches": settings.daily_search_limit, "llm": settings.daily_llm_limit,
                          "places": settings.daily_places_limit, "simulator": settings.daily_simulator_limit,
                          "agent": settings.daily_agent_limit}, clock=clock)
    ekispert = FakeEkispert()
    deps = Deps(settings=settings, store=store, line=RecordingLineApi(names={}), ids=Ids(settings.app_secret),
                usage=usage, llm=LLMClient([]), ekispert=ekispert,
                stations=StationResolver(ekispert, store, clock=clock), hotpepper=FakeHotPepper(),
                places=FakePlaces(), clock=clock)
    from services.liff_auth import FakeVerifier
    deps.liff = FakeVerifier()
    return deps


@pytest.fixture
def deps() -> Deps:
    return make_deps()


_counter = [0]


def _eid() -> str:
    _counter[0] += 1
    return f"evt{_counter[0]:06d}"


def group_message(text: str, user: Optional[str], group: str = "C1", mention_self: bool = False) -> dict:
    message: dict[str, Any] = {"type": "text", "id": _eid(), "text": text}
    if mention_self:
        message["mention"] = {"mentionees": [{"index": 0, "length": len("@AsobiAgent"), "type": "user", "isSelf": True}]}
    source = {"type": "group", "groupId": group}
    if user:
        source["userId"] = user
    return {"type": "message", "webhookEventId": _eid(), "replyToken": "rt-" + _eid(), "source": source,
            "message": message}


def group_postback(data: str, user: Optional[str], group: str = "C1") -> dict:
    source = {"type": "group", "groupId": group}
    if user:
        source["userId"] = user
    return {"type": "postback", "webhookEventId": _eid(), "replyToken": "rt-" + _eid(), "source": source,
            "postback": {"data": data}}


def join(group: str = "C1") -> dict:
    return {"type": "join", "webhookEventId": _eid(), "replyToken": "rt-" + _eid(),
            "source": {"type": "group", "groupId": group}}


def follow(user: str) -> dict:
    return {"type": "follow", "webhookEventId": _eid(), "replyToken": "rt-" + _eid(),
            "source": {"type": "user", "userId": user}}


def dm(text: str, user: str) -> dict:
    return {"type": "message", "webhookEventId": _eid(), "replyToken": "rt-" + _eid(),
            "source": {"type": "user", "userId": user}, "message": {"type": "text", "id": _eid(), "text": text}}


def texts_of(messages: list[dict]) -> list[str]:
    out = []
    for m in messages:
        if m["type"] == "text":
            out.append(m["text"])
        else:
            out.append(m["altText"])
    return out


def find_postback(messages: list[dict], action: str) -> Optional[str]:
    """The postback data of the first button whose data starts with a=<action>."""
    import json
    blob = json.dumps(messages, ensure_ascii=False)
    import re
    m = re.search(r'"data": "(a=' + action + r'[^"]*)"', blob)
    return m.group(1) if m else None


def with_settings(deps: Deps, **overrides: Any) -> Deps:
    deps.settings = dataclasses.replace(deps.settings, **overrides)
    return deps
