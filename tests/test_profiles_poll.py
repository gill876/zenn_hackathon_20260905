"""Profiles (LIFF), the date poll, places from profiles, multi-choice votes and suggestions."""

import re

from fastapi.testclient import TestClient

from bot import texts
from bot.handler import handle_event
from server import create_app
from services.taste import allocate, group_taste
from tests.conftest import find_postback, group_message, group_postback, make_deps
from tests.test_group_flow import SATO, SUZUKI, TAKAHASHI, TANAKA, activated_group, send


def auth(user, name):
    from urllib.parse import quote
    return {"Authorization": f"Bearer user:{user}:{quote(name)}"}


def save_profile(client, user, name, likes, dislikes=(), station_code=None):
    r = client.put("/api/liff/profile", headers=auth(user, name),
                   json={"likes": list(likes), "dislikes": list(dislikes), "station_code": station_code})
    assert r.status_code == 200, r.text


def test_profile_api_round_trip():
    deps = make_deps()
    client = TestClient(create_app(deps))
    assert client.get("/api/liff/profile").status_code == 401
    save_profile(client, SATO, "佐藤", ["yakiniku", "yakiniku/steak", "bogus"], ["korean"], "23368")
    got = client.get("/api/liff/profile", headers=auth(SATO, "佐藤")).json()
    assert got["likes"] == ["yakiniku", "yakiniku/steak"] and got["dislikes"] == ["korean"]
    assert got["station"] == {"name": "横浜", "code": "23368"}
    near = client.post("/api/liff/stations/near", headers=auth(SATO, "佐藤"), json={"lat": 35.64, "lng": 139.70}).json()
    assert near["stations"][0]["name"] == "中目黒"
    assert client.delete("/api/liff/profile", headers=auth(SATO, "佐藤")).json() == {"ok": True}
    assert client.get("/api/liff/profile", headers=auth(SATO, "佐藤")).json()["exists"] is False


def test_group_taste_never_includes_a_dropped_kind():
    people = [{"name": "A", "profile": {"likes": ["yakiniku", "cafe"], "dislikes": ["korean"]}},
              {"name": "B", "profile": {"likes": ["korean", "italian"], "dislikes": []}},
              {"name": "C", "profile": None}]
    taste = group_taste(people)
    kinds = [k["id"] for k in taste["kinds"]]
    assert "korean" not in kinds and set(kinds) == {"yakiniku", "cafe", "italian"}
    slots = allocate(taste, 6)
    assert slots[:2] == ["yakiniku", "italian"]          # each person's favourite comes first


async def test_date_poll_to_places_to_decision():
    deps = make_deps()
    client = TestClient(create_app(deps))
    for user, name, station, likes in ((SATO, "佐藤", "23368", ["yakiniku", "cafe"]), (SUZUKI, "鈴木", "22637", ["yakiniku"]),
                                       (TANAKA, "田中", "22855", ["cafe"]), (TAKAHASHI, "高橋", "22228", ["italian"])):
        save_profile(client, user, name, likes, ["korean"], station)
    await activated_group(deps)

    start = await send(deps, group_message("@AsobiAgent 日程調整", SATO, mention_self=True))
    url = re.search(r"https://liff\.line\.me/[^\"']+/calendar\?t=([^\"'\s]+)", str(start)).group(1)
    token = url
    # only the organizer can pick dates
    assert client.post("/api/liff/poll/dates", headers=auth(SUZUKI, "鈴木"),
                       json={"t": token, "dates": ["2026-10-24"], "slot": "lunch"}).status_code == 403
    r = client.post("/api/liff/poll/dates", headers=auth(SATO, "佐藤"),
                    json={"t": token, "dates": ["2026-10-17", "2026-10-24", "1999-01-01"], "slot": "lunch"})
    assert r.json()["count"] == 2                          # the past date is dropped
    card = await send(deps, group_message("日程調整を作りました（2日）", SATO))
    assert "○△×" in card[0]["altText"]
    assert await send(deps, group_message("日程調整を作りました（2日）", SATO)) == []   # announced once

    answers = {SATO: {"2026-10-17": "o", "2026-10-24": "o"}, SUZUKI: {"2026-10-17": "x", "2026-10-24": "o"},
               TANAKA: {"2026-10-17": "o", "2026-10-24": "t"}, TAKAHASHI: {"2026-10-17": "x", "2026-10-24": "o"}}
    names = {SATO: "佐藤", SUZUKI: "鈴木", TANAKA: "田中", TAKAHASHI: "高橋"}
    for user, marks in answers.items():
        r = client.post("/api/liff/poll/answer", headers=auth(user, names[user]), json={"t": token, "marks": marks})
        assert r.json()["first"] is True
    view = client.get(f"/api/liff/poll?t={token}", headers=auth(TANAKA, "田中")).json()
    assert view["best"] == "2026-10-24" and len(view["people"]) == 4

    nonce = re.search(r"a=pollclose&p=([0-9a-f]+)", str(card)).group(1)
    assert "幹事" in (await send(deps, group_postback(f"a=pollclose&p={nonce}", SUZUKI)))[0]["text"]
    result = await send(deps, group_postback(f"a=pollclose&p={nonce}", SATO))
    assert "10/24(土) に決まりました" in result[0]["altText"]

    places = await send(deps, group_postback(find_postback(result, "pollplan"), SATO))
    assert "集合駅は" in places[0]["altText"]               # everyone had a station: straight to places
    carousel = places[1]["contents"]["contents"]
    assert len(carousel) == 7                                # six places + the last card
    assert "♡" in str(carousel[0])
    assert await deps.store.get("polls", deps.ids.chat("C1")) is None

    plan = await deps.store.get("plans", deps.ids.chat("C1"))
    assert plan["hint"]["day"] == "10/24" and plan["hint"]["meal"] == "lunch"
    a, b = plan["picks"][0]["id"], plan["picks"][1]["id"]
    n = plan["nonce"]
    assert await send(deps, group_postback(f"a=vote&p={n}&v={a}", SATO)) == []
    assert await send(deps, group_postback(f"a=vote&p={n}&v={b}", SATO)) == []        # several choices
    assert await send(deps, group_postback(f"a=vote&p={n}&v={b}", SATO)) == []        # tap again: undo
    res = await send(deps, group_postback(f"a=results&p={n}", TANAKA))
    assert "1/4人が投票" in res[0]["altText"]
    for user in (SUZUKI, TANAKA):
        assert await send(deps, group_postback(f"a=vote&p={n}&v={a}", user)) == []
    done = await send(deps, group_postback(f"a=vote&p={n}&v={a}", TAKAHASHI))    # all four approve A
    assert "に決まりました" in done[0]["altText"] and "4/4人" in done[0]["altText"]
    assert deps.line.left == [("group", "C1")]


async def test_suggestions_join_the_vote(deps):
    from tests.test_group_flow import to_voting
    await to_voting(deps)
    plan = await deps.store.get("plans", deps.ids.chat("C1"))
    how = await send(deps, group_postback(f"a=suggest&p={plan['nonce']}", SUZUKI))
    assert how[0]["text"] == texts.SUGGEST_HOW
    card = await send(deps, group_message("@AsobiAgent 提案 知らない店", SUZUKI, mention_self=True))
    assert "鈴木さんの提案" in card[0]["altText"] or "メンバーさんの提案" in card[0]["altText"]
    again = await send(deps, group_message("@AsobiAgent 提案 知らない店", TANAKA, mention_self=True))
    assert again[0]["text"] == texts.SUGGEST_DUP
    plan = await deps.store.get("plans", deps.ids.chat("C1"))
    sid = plan["suggestions"][0]["id"]
    assert sid.startswith("SG")
    for user in (SATO, SUZUKI, TANAKA):
        assert await send(deps, group_postback(f"a=vote&p={plan['nonce']}&v={sid}", user)) == []
    done = await send(deps, group_postback(f"a=vote&p={plan['nonce']}&v={sid}", TAKAHASHI))
    assert "知らない店" in done[1]["altText"]
    assert "地図で見る" in str(done[1]) and "tel:0355550000" in str(done[2])
    assert deps.places.calls == 0                 # Places already gave the number when it was suggested


async def test_participants_with_profiles_need_no_station_message(deps):
    client = TestClient(create_app(deps))
    save_profile(client, SATO, "佐藤", ["yakiniku"], [], "23368")
    save_profile(client, SUZUKI, "鈴木", ["cafe"], [], "22637")
    await activated_group(deps)
    gathering = await send(deps, group_message("@AsobiAgent 土曜ランチ", SATO, mention_self=True))
    ready = await send(deps, group_postback(find_postback(gathering, "join"), SUZUKI))
    assert "全員の出発駅がそろいました" in ready[0]["altText"]       # both stations came from profiles
