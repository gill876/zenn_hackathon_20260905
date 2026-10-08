"""The whole LINE group lifecycle from the wireframe, with fake LINE/Ekispert/HotPepper."""

from bot import texts
from bot.handler import handle_event
from tests.conftest import (ADMIN, dm, find_postback, follow, group_message, group_postback, join, texts_of,
                            with_settings)

SATO, SUZUKI, TANAKA, TAKAHASHI = (f"U{c * 32}" for c in "1234")


async def send(deps, ev):
    before = len(deps.line.replies)
    await handle_event(deps, ev)
    new = deps.line.replies[before:]
    return new[0]["messages"] if new else []


async def verified_user(deps, user):
    codes = await send(deps, dm("/invite 1", ADMIN))
    code = codes[1]["text"].strip()
    await send(deps, follow(user))
    reply = await send(deps, dm(code.lower().replace("-", " "), user))
    assert "認証しました" in reply[0]["text"]


async def activated_group(deps, group="C1", by=SATO):
    await verified_user(deps, by)
    welcome = await send(deps, join(group))
    assert "有効化" in texts_of(welcome)[0]
    reply = await send(deps, group_postback("a=activate", by, group))
    assert "使えるようになりました" in texts_of(reply)[0]


async def to_ready(deps):
    await activated_group(deps)
    gathering = await send(deps, group_message("@AsobiAgent 来週土曜13時からランチ決めたい", SATO, mention_self=True))
    nonce_data = find_postback(gathering, "join")
    assert nonce_data
    for user in (SUZUKI, TANAKA, TAKAHASHI):
        assert await send(deps, group_postback(nonce_data, user)) == []
    assert await send(deps, group_message("横浜から行くよ", SATO)) == []
    assert await send(deps, group_message("吉祥寺から！混んでない所がいいな", SUZUKI)) == []
    assert await send(deps, group_message("中目黒から。お肉食べたい", TANAKA)) == []
    ready = await send(deps, group_message("柏から向かう", TAKAHASHI))
    assert "全員の出発駅がそろいました" in texts_of(ready)[0]
    return ready


async def to_voting(deps):
    ready = await to_ready(deps)
    ready_data = find_postback(ready, "ready")
    for user in (SUZUKI, TAKAHASHI, TANAKA):
        assert await send(deps, group_postback(ready_data, user)) == []
    results = await send(deps, group_postback(ready_data, SATO))
    return results


async def test_full_flow_from_invite_to_decision(deps):
    results = await to_voting(deps)
    assert len(results) == 2
    assert "集合駅は秋葉原" in results[0]["altText"]
    assert results[1]["contents"]["type"] == "carousel"
    assert [c for c in deps.ekispert.calls if c[0] == "ranges"] == [("ranges", ("横浜", "吉祥寺", "中目黒", "柏"))]

    ghash = deps.ids.chat("C1")
    plan = await deps.store.get("plans", ghash)
    assert plan["phase"] == "voting"
    assert plan["held"] == []                                   # chat text deleted after the search
    assert all("station" not in p for p in plan["participants"].values())

    first = plan["picks"][0]["id"]
    third = plan["picks"][2]["id"]
    nonce = plan["nonce"]
    assert await send(deps, group_postback(f"a=vote&p={nonce}&v={first}", SUZUKI)) == []
    assert await send(deps, group_postback(f"a=vote&p={nonce}&v={third}", TAKAHASHI)) == []
    decided = await send(deps, group_postback(f"a=vote&p={nonce}&v={first}", TANAKA))
    # 2 of 4 is not a majority; the third vote for the same shop is
    assert decided == []
    decided = await send(deps, group_postback(f"a=vote&p={nonce}&v={first}", SATO))
    assert "に決まりました" in decided[0]["altText"]
    assert "電話" in decided[1]["altText"]
    assert "tel:0312345678" in str(decided[1])
    assert decided[2]["text"] == texts.GOODBYE
    assert deps.line.left == [("group", "C1")]
    assert await deps.store.get("plans", ghash) is None         # names and votes deleted
    group = await deps.store.get("groups", ghash)
    assert group["state"] == "done" and group["plans_used"] == 1

    again = await send(deps, join("C1"))
    assert again[0]["text"] == texts.USED_UP
    assert deps.line.left[-1] == ("group", "C1")


async def test_idle_chat_is_not_read_or_stored(deps):
    await activated_group(deps)
    assert await send(deps, group_message("来週の土曜ひま？", SUZUKI)) == []
    assert await send(deps, group_message("横浜から行くよ", TANAKA)) == []
    assert await deps.store.get("plans", deps.ids.chat("C1")) is None
    assert deps.ekispert.calls == []


async def test_unverified_member_cannot_activate(deps):
    await send(deps, join("C1"))
    reply = await send(deps, group_postback("a=activate", SUZUKI))
    assert reply[0]["text"] == texts.NOT_VERIFIED
    group = await deps.store.get("groups", deps.ids.chat("C1"))
    assert group["state"] == "pending"


async def test_admin_can_activate_without_a_code(deps):
    await send(deps, join("C1"))
    reply = await send(deps, group_postback("a=activate", ADMIN))
    assert "使えるようになりました" in texts_of(reply)[0]


async def test_each_verified_person_can_activate_two_groups(deps):
    await verified_user(deps, SATO)
    for group in ("C1", "C2"):
        await send(deps, join(group))
        assert "使えるようになりました" in texts_of(await send(deps, group_postback("a=activate", SATO, group)))[0]
    await send(deps, join("C3"))
    reply = await send(deps, group_postback("a=activate", SATO, "C3"))
    assert reply[0]["text"] == texts.USER_GROUP_LIMIT


async def test_invite_codes_are_single_use(deps):
    codes = await send(deps, dm("/invite 1", ADMIN))
    code = codes[1]["text"].strip()
    assert "認証しました" in (await send(deps, dm(code, SATO)))[0]["text"]
    assert (await send(deps, dm(code, SUZUKI)))[0]["text"] == texts.CODE_USED
    assert (await send(deps, dm("ASBI-2222-2222", TANAKA)))[0]["text"] == texts.CODE_UNKNOWN


async def test_invite_codes_expire(deps):
    codes = await send(deps, dm("/invite 1", ADMIN))
    deps.clock.advance(15 * 86400)
    assert (await send(deps, dm(codes[1]["text"].strip(), SATO)))[0]["text"] == texts.CODE_EXPIRED


async def test_pending_group_is_left_after_24_hours(deps):
    await send(deps, join("C1"))
    deps.clock.advance(25 * 3600)
    reply = await send(deps, group_message("こんにちは", SUZUKI))
    assert reply[0]["text"] == texts.PENDING_TIMEOUT
    assert deps.line.left == [("group", "C1")]


async def test_active_group_expires_after_7_days(deps):
    await activated_group(deps)
    deps.clock.advance(8 * 86400)
    reply = await send(deps, group_message("@AsobiAgent まだいる？", SATO, mention_self=True))
    assert reply[0]["text"] == texts.ACTIVE_EXPIRED
    assert deps.line.left == [("group", "C1")]


async def test_only_the_organizer_can_force_a_search(deps):
    ready = await to_ready(deps)
    force = find_postback(ready, "force")
    reply = await send(deps, group_postback(force, SUZUKI))
    assert "幹事" in reply[0]["text"]
    results = await send(deps, group_postback(force, SATO))
    assert "集合駅" in results[0]["altText"]


async def test_daily_search_limit_stops_the_search(deps):
    with_settings(deps)
    deps.usage._limits["searches"] = 0
    ready = await to_ready(deps)
    reply = await send(deps, group_postback(find_postback(ready, "force"), SATO))
    assert reply[0]["text"] == texts.DAILY_LIMIT
    plan = await deps.store.get("plans", deps.ids.chat("C1"))
    assert plan["phase"] == "ready"


async def test_refining_counts_toward_the_search_limit(deps):
    await to_voting(deps)
    plan = await deps.store.get("plans", deps.ids.chat("C1"))
    nonce = plan["nonce"]
    first = await send(deps, group_postback(f"a=refine&p={nonce}&r=private", SUZUKI))
    assert "条件を変えて探しました" in first[0]["text"]
    second = await send(deps, group_postback(f"a=refine&p={nonce}&r=cheaper", SUZUKI))
    assert "条件を変えて探しました" in second[0]["text"]
    assert deps.hotpepper.searches[-1].get("budget")
    third = await send(deps, group_postback(f"a=refine&p={nonce}&r=near", SUZUKI))
    assert third[0]["text"] == texts.SEARCHES_USED_UP
    group = await deps.store.get("groups", deps.ids.chat("C1"))
    assert group["searches_used"] == 3


async def test_free_text_refinement_by_mention(deps):
    await to_voting(deps)
    reply = await send(deps, group_message("@AsobiAgent 和食がいい", TANAKA, mention_self=True))
    assert "条件を変えて探しました" in reply[0]["text"]
    plan = await deps.store.get("plans", deps.ids.chat("C1"))
    assert plan["details"]["genre"] == "G004"


async def test_more_shows_the_next_three(deps):
    await to_voting(deps)
    plan = await deps.store.get("plans", deps.ids.chat("C1"))
    reply = await send(deps, group_postback(f"a=more&p={plan['nonce']}", SUZUKI))
    assert reply[0]["contents"]["type"] == "carousel"
    assert "D  " in str(reply[0])


async def test_organizer_can_close_the_vote(deps):
    await to_voting(deps)
    plan = await deps.store.get("plans", deps.ids.chat("C1"))
    second = plan["picks"][1]["id"]
    await send(deps, group_postback(f"a=vote&p={plan['nonce']}&v={second}", SUZUKI))
    decided = await send(deps, group_postback(f"a=close&p={plan['nonce']}", SATO))
    assert deps.hotpepper.shops[second]["name"] in decided[0]["altText"]


async def test_old_buttons_are_rejected(deps):
    await to_voting(deps)
    reply = await send(deps, group_postback("a=vote&p=deadbeef&v=J000000001", SUZUKI))
    assert reply[0]["text"] == texts.STALE_BUTTON


async def test_pc_users_are_asked_to_use_the_phone_app(deps):
    await send(deps, join("C1"))
    reply = await send(deps, group_postback("a=activate", None))
    assert reply[0]["text"] == texts.USE_PHONE_APP


async def test_redelivered_events_are_handled_once(deps):
    ev = join("C1")
    await handle_event(deps, ev)
    await handle_event(deps, ev)
    assert len(deps.line.replies) == 1


async def test_missing_date_is_shown_as_undecided_then_noted(deps):
    await activated_group(deps)
    gathering = await send(deps, group_message("@AsobiAgent ご飯いこう", SATO, mention_self=True))
    join_data = find_postback(gathering, "join")
    await send(deps, group_postback(join_data, SUZUKI))
    await send(deps, group_message("横浜から", SATO))
    ready = await send(deps, group_message("吉祥寺から", SUZUKI))
    assert "未定" in str(ready)
    noted = await send(deps, group_message("土曜19時でどう？", SUZUKI))
    assert noted[0]["text"] == texts.when_noted("土曜 19:00")


async def test_passing_removes_only_your_own_messages(deps):
    await activated_group(deps)
    gathering = await send(deps, group_message("@AsobiAgent 土曜ランチ", SATO, mention_self=True))
    join_data = find_postback(gathering, "join")
    pass_data = find_postback(gathering, "pass")
    for user in (SUZUKI, TANAKA):
        await send(deps, group_postback(join_data, user))
    await send(deps, group_message("横浜から", SATO))
    await send(deps, group_message("お肉がいいな", TANAKA))
    await send(deps, group_message("吉祥寺から", SUZUKI))
    ready = await send(deps, group_postback(pass_data, TANAKA))   # Tanaka had no station; the rest are ready
    assert "全員の出発駅がそろいました" in texts_of(ready)[0]
    plan = await deps.store.get("plans", deps.ids.chat("C1"))
    held = [h["t"] for h in plan["held"]]
    assert "お肉がいいな" not in held
    assert "横浜から" in held and "吉祥寺から" in held
    assert len(plan["participants"]) == 2


async def test_participant_cap(deps):
    with_settings(deps, max_participants=2)
    await activated_group(deps)
    gathering = await send(deps, group_message("@AsobiAgent 土曜", SATO, mention_self=True))
    join_data = find_postback(gathering, "join")
    assert await send(deps, group_postback(join_data, SUZUKI)) == []
    reply = await send(deps, group_postback(join_data, TANAKA))
    assert reply[0]["text"] == texts.full(2)


async def test_time_out_pick_can_win_and_uses_time_out_phone(deps):
    from services.timeout_index import TimeOutIndex
    deps.timeout = TimeOutIndex([{"name": "路地裏 肉ビストロ", "lat": 35.6990, "lng": 139.7740, "address": "東京都千代田区",
                                  "telephone": "03-9999-0000", "hours": "11〜23時／定休日は水曜", "section": "レストラン",
                                  "url": "https://www.timeout.jp/tokyo/ja/レストラン/roji"}])
    await to_voting(deps)
    plan = await deps.store.get("plans", deps.ids.chat("C1"))
    third = plan["picks"][2]
    assert third["id"].startswith("TO")                       # slot C is the Time Out pick
    for user in (SATO, SUZUKI, TANAKA):
        out = await send(deps, group_postback(f"a=vote&p={plan['nonce']}&v={third['id']}", user))
    assert "路地裏 肉ビストロ" in out[0]["altText"]
    assert "お店の情報（Time Out）" in str(out[0]) and "ホットペッパーで予約" not in str(out[0])
    assert "tel:0399990000" in str(out[1])
    assert deps.places.calls == 0                             # Time Out already had the number


async def test_closed_shops_are_dropped_at_the_planned_time(deps):
    closed = deps.hotpepper.shops["J000000001"]
    closed["open"] = "月～金: 11:00～14:00 土: 17:00～23:00"   # Saturday lunch: closed
    closed["close"] = "日"
    await to_voting(deps)                                     # the plan is 来週土曜 13:00
    plan = await deps.store.get("plans", deps.ids.chat("C1"))
    assert "J000000001" not in [p["id"] for p in plan["picks"]]
