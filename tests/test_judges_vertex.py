"""The judges' shared code (LINE and the web demo), a judge planning alone, and the Vertex → GMI fallback."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from bot import texts
from server import create_app
from services.llm_client import LLMClient, Provider
from tests.conftest import ADMIN, dm, find_postback, follow, group_postback, group_message, join, make_deps, texts_of
from tests.test_group_flow import SATO, SUZUKI, TAKAHASHI, TANAKA, send
from tests.test_profiles_poll import auth, save_profile

DAY = 86400


async def judge_code(deps, uses="3"):
    reply = await send(deps, dm(f"/judge {uses}", ADMIN))
    return reply[0]["text"], reply[1]["text"].strip()


# ---- the judges' code in LINE ---------------------------------------------------------------------------

async def test_judge_code_is_shared_up_to_its_limit(deps):
    header, code = await judge_code(deps, "3")
    assert "3人まで" in header and "Web版" in header
    for user in (SATO, SUZUKI, TANAKA):
        await send(deps, follow(user))
        assert "認証しました" in (await send(deps, dm(code, user)))[0]["text"]
        assert (await deps.store.get("users", deps.ids.user(user)))["via"] == "judge"
    assert (await send(deps, dm(code, TAKAHASHI)))[0]["text"] == texts.CODE_USED
    invite = await deps.store.get("invites", code)
    assert invite["uses"] == 3 and invite["used_by"] is None      # no judge is tied to the code


async def test_a_judge_redeeming_twice_uses_one_seat(deps):
    _, code = await judge_code(deps, "2")
    await send(deps, dm(code, SATO))
    assert (await send(deps, dm(code, SATO)))[0]["text"] == texts.ALREADY_VERIFIED
    assert (await deps.store.get("invites", code))["uses"] == 1


async def test_judge_code_outlives_normal_invites_then_expires(deps):
    _, code = await judge_code(deps)
    deps.clock.advance(45 * DAY)                                     # normal invites last 14 days
    assert "認証しました" in (await send(deps, dm(code, SATO)))[0]["text"]
    deps.clock.advance(16 * DAY)                                     # 61 days after it was made
    assert (await send(deps, dm(code, SUZUKI)))[0]["text"] == texts.CODE_EXPIRED


async def test_judge_command_bounds_the_count(deps):
    header, _ = await judge_code(deps, "abc")
    assert "30人まで" in header
    header, _ = await judge_code(deps, "1")
    assert "2人まで" in header                                      # a shared code is at least two seats
    header, _ = await judge_code(deps, "5000")
    assert "100人まで" in header


async def test_only_the_admin_can_make_judge_codes(deps):
    reply = await send(deps, dm("/judge 30", SATO))
    assert reply[0]["text"] == texts.ASK_FOR_CODE
    assert await deps.store.count("invites") == 0


# ---- the judges' code on the web demo ---------------------------------------------------------------------

CHAT = {"messages": [{"sender": "佐藤", "text": "土曜のランチ、横浜から行くよ"},
                     {"sender": "鈴木", "text": "吉祥寺から！"}]}


async def test_judge_code_unlocks_free_text_on_the_web(deps):
    _, code = await judge_code(deps)
    invites = await send(deps, dm("/invite 1", ADMIN))
    single = invites[1]["text"].strip()
    client = TestClient(create_app(deps))

    assert client.post("/api/chat", json=CHAT).status_code == 403
    assert client.post("/api/chat", json=CHAT, headers={"X-Access-Code": single}).status_code == 403
    assert client.post("/api/chat", json=CHAT, headers={"X-Access-Code": "ASBI-2222-2222"}).status_code == 403
    r = client.post("/api/chat", json=CHAT, headers={"X-Access-Code": code.lower().replace("-", " ")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_state"]["midpoint_data"]["hub_station"] == "秋葉原"
    assert len(body["bot_messages"]) == 2
    assert client.post("/api/chat", json=CHAT, headers={"X-Admin-Token": "admin-token"}).status_code == 200

    deps.clock.advance(61 * DAY)
    assert client.post("/api/chat", json=CHAT, headers={"X-Access-Code": code}).status_code == 403


async def test_web_free_text_still_counts_toward_the_daily_cap():
    deps = make_deps(daily_simulator_limit=1)
    _, code = await judge_code(deps)
    client = TestClient(create_app(deps))
    assert client.post("/api/chat", json=CHAT, headers={"X-Access-Code": code}).status_code == 200
    assert client.post("/api/chat", json=CHAT, headers={"X-Access-Code": code}).status_code == 429


# ---- a judge planning alone in a ひとりグループ ---------------------------------------------------------------

async def solo_group(deps, judge=SATO, group="C9"):
    _, code = await judge_code(deps)
    await send(deps, follow(judge))
    await send(deps, dm(code, judge))
    deps.line.members = 1                                            # LINE's count leaves the bot out
    await send(deps, join(group))
    assert "使えるようになりました" in texts_of(await send(deps, group_postback("a=activate", judge, group)))[0]


async def test_a_judge_alone_with_a_profile_gets_to_a_decision(deps):
    client = TestClient(create_app(deps))
    save_profile(client, SATO, "審査員", ["yakiniku", "cafe"], [], "23368")
    await solo_group(deps)

    ready = await send(deps, group_postback("a=start", SATO, "C9"))
    assert "出発駅がそろいました" in ready[0]["altText"]             # no 参加する step for one person
    assert "これでOK" in str(ready[0].get("quickReply"))
    places = await send(deps, group_postback(find_postback(ready, "ready"), SATO, "C9"))
    assert "集合駅は横浜" in places[0]["altText"]                     # one station: meet there
    assert [c for c in deps.ekispert.calls if c[0] == "ranges"] == []    # no range search for one person

    plan = await deps.store.get("plans", deps.ids.chat("C9"))
    pick = plan["picks"][0]["id"]
    done = await send(deps, group_postback(f"a=vote&p={plan['nonce']}&v={pick}", SATO, "C9"))
    assert any("に決まりました" in m.get("altText", "") for m in done)
    assert "1/1人" in done[0]["altText"]
    assert ("group", "C9") in deps.line.left


async def test_a_judge_alone_without_a_profile_types_a_station(deps):
    await solo_group(deps)
    gathering = await send(deps, group_message("@AsobiAgent 土曜のランチ", SATO, "C9", mention_self=True))
    assert "参加する" in str(gathering)
    ready = await send(deps, group_message("横浜から行きます", SATO, "C9"))
    assert "出発駅がそろいました" in ready[0]["altText"]


async def test_a_judge_alone_can_also_force_the_search(deps):
    await solo_group(deps)
    gathering = await send(deps, group_message("@AsobiAgent 土曜のランチ", SATO, "C9", mention_self=True))
    force = find_postback(gathering, "force")
    assert (await send(deps, group_postback(force, SATO, "C9")))[0]["text"] == texts.NEED_TWO   # no station yet
    await send(deps, group_message("横浜から行きます", SATO, "C9"))
    forced = await send(deps, group_postback(force, SATO, "C9"))
    assert "集合駅は横浜" in forced[0]["altText"]


async def test_bigger_groups_still_wait_for_two_people(deps):
    client = TestClient(create_app(deps))
    save_profile(client, SATO, "佐藤", ["cafe"], [], "23368")
    await solo_group(deps)
    deps.line.members = 3
    reply = await send(deps, group_postback("a=start", SATO, "C9"))
    assert "参加する" in str(reply) and "出発駅がそろいました" not in str(reply)
    gathering = reply
    forced = await send(deps, group_postback(find_postback(gathering, "force"), SATO, "C9"))
    assert forced[0]["text"] == texts.NEED_TWO


async def test_unknown_group_size_keeps_the_two_person_rule(deps):
    client = TestClient(create_app(deps))
    save_profile(client, SATO, "佐藤", ["cafe"], [], "23368")
    await solo_group(deps)
    deps.line.members = None                                         # the count API failed
    reply = await send(deps, group_postback("a=start", SATO, "C9"))
    assert "出発駅がそろいました" not in str(reply)


async def test_a_judge_alone_can_use_the_date_poll(deps):
    client = TestClient(create_app(deps))
    save_profile(client, SATO, "審査員", ["cafe"], [], "23368")
    await solo_group(deps)
    import re
    start = await send(deps, group_message("@AsobiAgent 日程調整", SATO, "C9", mention_self=True))
    token = re.search(r"/calendar\?t=([^\"'\s]+)", str(start)).group(1)
    client.post("/api/liff/poll/dates", headers=auth(SATO, "審査員"),
                json={"t": token, "dates": ["2026-10-24", "2026-10-25"], "slot": "lunch"})
    await send(deps, group_message("日程調整を作りました（2日）", SATO, "C9"))
    client.post("/api/liff/poll/answer", headers=auth(SATO, "審査員"),
                json={"t": token, "marks": {"2026-10-24": "x", "2026-10-25": "o"}})
    closed = await send(deps, group_message("日程に回答しました ✅", SATO, "C9"))
    assert texts.POLL_ALL_ANSWERED in str(closed)                   # one answer is everyone
    places = await send(deps, group_postback(find_postback(closed, "pollplan"), SATO, "C9"))
    assert "集合駅は横浜" in places[0]["altText"]
    plan = await deps.store.get("plans", deps.ids.chat("C9"))
    assert plan["hint"]["day"] == "10/25"


# ---- Gemini on Vertex AI first, GMI Cloud as the fallback -------------------------------------------------

def fake_provider(name, answer=None, error=None, calls=None):
    async def create(**kwargs):
        if calls is not None:
            calls.append((name, kwargs["model"]))
        if error:
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return Provider(name, client, f"{name}-model")


async def test_vertex_answers_first():
    calls = []
    llm = LLMClient([fake_provider("vertex", '{"day": "10/24"}', calls=calls),
                     fake_provider("gmi", '{"day": "never"}', calls=calls)])
    assert await llm.generate_json("p", "s") == {"day": "10/24"}
    assert calls == [("vertex", "vertex-model")]


async def test_gmi_takes_over_when_vertex_fails():
    calls = []
    llm = LLMClient([fake_provider("vertex", error=RuntimeError("503"), calls=calls),
                     fake_provider("gmi", '```json\n{"day": "10/24"}\n```', calls=calls)])
    assert await llm.generate_json("p", "s") == {"day": "10/24"}
    assert [c[0] for c in calls] == ["vertex", "gmi"]


async def test_every_provider_down_means_the_rule_based_fallback():
    llm = LLMClient([fake_provider("vertex", error=TimeoutError()), fake_provider("gmi", error=RuntimeError())])
    assert await llm.generate_json("p", "s") == {}
    assert await LLMClient([]).generate_json("p", "s") == {}
    assert LLMClient([]).available is False


async def test_the_daily_cap_counts_one_call_however_many_providers_answer():
    deps = make_deps(daily_llm_limit=1)
    calls = []
    llm = LLMClient([fake_provider("vertex", error=RuntimeError(), calls=calls),
                     fake_provider("gmi", '{"ok": true}', calls=calls)], usage=deps.usage)
    assert await llm.generate_json("p", "s") == {"ok": True}
    assert await llm.generate_json("p", "s") == {}                    # cap reached: no provider is called
    assert len(calls) == 2


def test_providers_come_from_settings():
    from tests.conftest import make_settings
    both = LLMClient.from_settings(make_settings(vertex_project="asobi-agent-dw9h", vertex_location="global",
                                                 vertex_model="google/gemini-3.5-flash-lite", gmi_api_key="k",
                                                 gmi_base_url="https://api.gmi-serving.com/v1", gmi_model="m"))
    assert [p.name for p in both.providers] == ["vertex", "gmi"]
    assert both.model == "google/gemini-3.5-flash-lite"
    assert str(both.providers[0].client.base_url).startswith(
        "https://aiplatform.googleapis.com/v1/projects/asobi-agent-dw9h/locations/global/endpoints/openapi")
    only_gmi = LLMClient.from_settings(make_settings(gmi_api_key="k", gmi_base_url="https://api.gmi-serving.com/v1",
                                                     gmi_model="m"))
    assert [p.name for p in only_gmi.providers] == ["gmi"]
    assert LLMClient.from_settings(make_settings()).providers == []
