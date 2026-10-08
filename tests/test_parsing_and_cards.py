import datetime as dt
import json

from agents.form_agent import booking_values, rule_based_mapping
from agents.voice_agent import call_script
from bot.text_parse import date_hint, station_candidates
from services import line_flex
from services.ids import Ids, normalize_invite_code
from tests.conftest import shop


def test_station_candidates_from_real_messages():
    assert station_candidates("横浜から行くよ") == ["横浜"]
    assert station_candidates("私「中目黒」から行くよ") == ["中目黒"]
    assert station_candidates("俺は「品川」で退勤予定！") == ["品川"]
    assert "吉祥寺" in station_candidates("俺は吉祥寺から")
    assert station_candidates("家から向かう") == []
    assert station_candidates("13時からね") == []


def test_date_hints():
    assert date_hint("みんな来週土曜日の昼13時くらいから空いてる？") == {"day": "来週土曜", "time": "13:00"}
    assert date_hint("10月18日の18時半") == {"day": "10/18", "time": "18:30"}


def test_invite_code_normalization():
    assert normalize_invite_code("asbi 7kq2 m9xd") == "ASBI-7KQ2-M9XD"
    assert normalize_invite_code("ASBI-0000-0000") is None   # 0 is not in the alphabet
    assert normalize_invite_code("hello") is None


def test_hashed_ids_and_signed_links():
    ids = Ids("secret")
    assert ids.user("U1") == ids.user("U1") != Ids("other").user("U1")
    assert "U1" not in ids.user("U1")
    token = ids.sign({"r": "abc"}, 60)
    assert ids.verify(token)["r"] == "abc"
    assert ids.verify(token[:-2] + "xx") is None
    assert Ids("other").verify(token) is None


def test_call_script_never_claims_a_booking():
    script = call_script("テスト店", "来週土曜", "13:00", 4, "佐藤")
    assert script["lines"][0].startswith("「来週土曜の13:00から、4名で")
    assert call_script("テスト店", None, None, 2, "佐藤")["lines"][0].startswith("「（日時）")


def _buttons(node):
    if isinstance(node, dict):
        if node.get("type") == "button":
            yield node
        for v in node.values():
            yield from _buttons(v)
    elif isinstance(node, list):
        for v in node:
            yield from _buttons(v)


def test_cards_respect_line_limits():
    picks = [{"id": f"J00000000{i}", "reason": "テスト", "crowd": {"level": "低", "facts": []}, "walk_min": 3} for i in (1, 2, 3)]
    cards = [
        line_flex.welcome(), line_flex.activated(1, 3, "10/15"), line_flex.gathering("n1", 10),
        line_flex.ready_check("n1", [("佐藤", "横浜"), ("鈴木", None)], None),
        line_flex.hub_card({"name": "秋葉原", "spread": 5}, [("佐藤", "横浜", 42)], "土曜 13:00"),
        line_flex.venues_carousel("n1", [shop(1), shop(2), shop(3)], picks, list("ABC"), 2, 2),
        line_flex.decision_card(shop(1), "土曜 13:00", 4, 3, "秋葉原", "https://x/agent/t"),
        line_flex.script_card(call_script("店", "土曜", "13:00", 4, "佐藤"), "03-1234-5678", None),
    ]
    for card in cards:
        assert card["type"] == "flex" and 0 < len(card["altText"]) <= 400
        for b in _buttons(card):
            assert len(b["action"]["label"]) <= 40
            if b["action"]["type"] == "postback":
                assert len(b["action"]["data"]) <= 300
    assert "Powered by ホットペッパーグルメ Webサービス" in json.dumps(cards[5], ensure_ascii=False)


def test_form_agent_values_and_fallback_mapping():
    values = booking_values({"day": "来週土曜", "time": "13:00", "pax": 4, "name": "佐藤"}, today=dt.date(2026, 10, 9))
    assert values["date"] == "2026-10-17" and values["party_size"] == "4" and values["phone"] == ""
    fields = [{"name": "visit_date", "label": "ご来店日"}, {"name": "visit_time", "label": "ご来店時間"},
              {"name": "guests", "label": "人数"}, {"name": "guest_name", "label": "お名前"},
              {"name": "tel", "label": "電話番号（任意）"}, {"name": "request", "label": "ご要望"}]
    assert rule_based_mapping(fields) == {"visit_date": "date", "visit_time": "time", "guests": "party_size",
                                          "guest_name": "name", "tel": "phone", "request": "notes"}


def test_time_out_badge_links_without_copying_content():
    from services.timeout_index import TimeOutIndex
    index = TimeOutIndex([{"name": "テスト店1", "lat": 35.6994, "lng": 139.7731, "url": "https://www.timeout.jp/tokyo/ja/レストラン/x"}])
    s = shop(1)
    featured = index.match(s)
    assert featured["url"].startswith("https://www.timeout.jp/")
    picks = [{"id": s["id"], "reason": "テスト", "crowd": {"level": "低", "facts": []}, "walk_min": 3}]
    card = json.dumps(line_flex.venues_carousel("n", [s], picks, ["A"], 0, 0, [featured]), ensure_ascii=False)
    assert "Time Out で紹介されています" in card and "Time Outの記事" in card
    assert index.match(shop(5)) is None   # far away
