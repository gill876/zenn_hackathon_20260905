"""
Rule-based reading of chat messages: station names, dates and times, and bot triggers.

This runs on every message from a participant while a plan is gathering, so it must not call an LLM.
Station candidates found here are only guesses; services/stations.py checks them against Ekispert.
"""

import re
import datetime
from datetime import date
from typing import Optional

_NAME_CHARS = r"一-龥々〆ヵヶぁ-んァ-ヴーｦ-ﾟA-Za-zＡ-Ｚａ-ｚ・()（）"
_BRACKETED = re.compile(r"[「『“\"]([^」』”\"]{1,14})[」』”\"]")
_BEFORE_MARKER = re.compile(rf"([{_NAME_CHARS}]{{1,14}}?)駅?(?:から|より|発|方面)")
_BEFORE_EKI = re.compile(rf"([{_NAME_CHARS}]{{1,14}})駅")
_PARTICLES = set("はがもでにをへとのや")
_HIRAGANA = re.compile(r"[ぁ-ん]")
_HAS_DIGIT_OR_TIME = re.compile(r"[0-9０-９時分半]")
_KANJI = re.compile(r"[一-龥々]")
# A kanji word ending in one of these is almost always a verb or adjective (向かう, 近い), not a station.
_VERB_ENDINGS = set("うくすつるむぶぬぐいたてよねだ")

# Words people write before から that are never a station.
_NOT_STATIONS = {
    "家", "自宅", "実家", "会社", "職場", "仕事", "学校", "大学", "バイト", "今", "いま", "そこ", "ここ", "駅",
    "近く", "うち", "うちの近く", "最寄り", "最寄", "地元", "都内", "みんな", "全員", "そっち", "こっち",
    "あっち", "現地", "昼", "夜", "朝", "午後", "午前", "前", "後", "あと", "先", "ちょっと", "俺", "私", "僕",
    "わたし", "ぼく", "おれ", "自分", "ホテル", "オフィス", "事務所", "病院",
}


def _clean(text: str) -> str:
    return text.strip().strip("・").replace("（", "(").replace("）", ")")


def _suffixes(span: str) -> list[str]:
    """The span itself, then the parts after particles or hiragana→kanji boundaries, longest first."""
    out = [span]
    for i in range(1, len(span)):
        prev, cur = span[i - 1], span[i]
        if prev in _PARTICLES or (_HIRAGANA.match(prev) and not _HIRAGANA.match(cur)):
            if len(span) - i >= 2:
                out.append(span[i:])
    return out


def station_candidates(text: str, limit: int = 4) -> list[str]:
    found: list[str] = []

    def add(raw: str) -> None:
        name = _clean(raw)
        if name.endswith("駅"):
            name = name[:-1]
        if not name or name in _NOT_STATIONS or _HAS_DIGIT_OR_TIME.search(name):
            return
        if name.startswith(("から", "より", "まで")):
            return
        if _KANJI.search(name) and name[-1] in _VERB_ENDINGS:
            return
        if name not in found:
            found.append(name)

    for m in _BRACKETED.finditer(text):
        add(m.group(1))
    for pattern in (_BEFORE_MARKER, _BEFORE_EKI):
        for m in pattern.finditer(text):
            for candidate in _suffixes(_clean(m.group(1))):
                add(candidate)
    return found[:limit]


_DAY = re.compile(
    r"(今日|明日|明後日|あさって|今夜|今晩|今週末|来週末|週末|"
    r"(?:再来週|来週|今週)の?\s*[月火水木金土日](?:曜日?)?|[月火水木金土日]曜日?|"
    r"\d{1,2}\s*[/月]\s*\d{1,2}\s*日?)"
)
_TIME = re.compile(r"(\d{1,2})\s*(?::\s*(\d{2})|時\s*(?:(\d{1,2})\s*分|(半))?)")
_MEAL = re.compile(r"(ランチ|お昼|昼ごはん|昼ご飯|ディナー|夜ごはん|夜ご飯|夕飯|晩ごはん|晩ご飯|飲み|お茶|カフェ)")


def _normalize_day(day: str) -> str:
    day = re.sub(r"\s+", "", day).replace("の", "")
    day = re.sub(r"曜日$", "曜", day)
    day = re.sub(r"(\d{1,2})月(\d{1,2})日?", r"\1/\2", day)
    return day


def date_hint(text: str) -> dict[str, str]:
    """{'day': '来週土曜', 'time': '13:00', 'meal': 'lunch'} with whatever this message mentions."""
    hint: dict[str, str] = {}
    if m := _DAY.search(text):
        hint["day"] = _normalize_day(m.group(1))
    for m in _TIME.finditer(text):
        hour = int(m.group(1))
        if hour > 29:
            continue
        minute = int(m.group(2) or m.group(3) or 0)
        if m.group(4):
            minute = 30
        hint["time"] = f"{hour:02d}:{minute:02d}"
        break
    if m := _MEAL.search(text):
        word = m.group(1)
        hint["meal"] = "lunch" if word in {"ランチ", "お昼", "昼ごはん", "昼ご飯"} else \
            "cafe" if word in {"お茶", "カフェ"} else "dinner"
    return hint


def merge_hints(old: Optional[dict[str, str]], new: dict[str, str]) -> dict[str, str]:
    merged = dict(old or {})
    for key, value in new.items():
        if not value:
            continue
        # 「来週土曜」 then 「土曜」 is the same day; keep the more specific one.
        if key == "day" and merged.get("day", "").endswith(value):
            continue
        merged[key] = value
    return merged


_PREF_SUFFIX = re.compile(r"\([^()]*[都道府県]\)$")


def short_station(name: str) -> str:
    """霞ケ関(東京都) → 霞ケ関. Other suffixes like 新宿(東京メトロ) name a different station and stay."""
    return _PREF_SUFFIX.sub("", name or "")


def hint_text(hint: Optional[dict[str, str]]) -> Optional[str]:
    if not hint:
        return None
    parts = [p for p in (hint.get("day"), hint.get("time")) if p]
    if not parts and hint.get("meal"):
        parts = [{"lunch": "ランチ", "dinner": "ディナー", "cafe": "お茶"}[hint["meal"]]]
    return " ".join(parts) or None


# 「@AsobiAgent M1 …」 typed by hand (not picked from LINE's @ list, so no mention data comes with it).
_TRIGGER = re.compile(r"^\s*[@＠]\s*(asobi\s*agent(\s*m\d+)?|アソビ|あそび)\s*", re.IGNORECASE)
JOIN_WORDS = {"参加する", "参加", "参加します", "さんか"}
PASS_WORDS = {"今回はパス", "パス", "不参加"}


def spelling_variants(name: str) -> list[str]:
    """Other ways the same station is commonly written (お茶の水 → 御茶ノ水, 市ケ谷 → 市ヶ谷)."""
    aliases = {"お茶の水": "御茶ノ水", "御茶の水": "御茶ノ水", "お茶ノ水": "御茶ノ水"}
    out = [aliases[name]] if name in aliases else []
    for a, b in (("ヶ", "ケ"), ("ケ", "ヶ"), ("の", "ノ"), ("ノ", "の")):
        if a in name:
            out.append(name.replace(a, b))
    return [v for v in dict.fromkeys(out) if v != name]


def is_trigger_text(text: str) -> bool:
    return bool(_TRIGGER.search(text)) or text.strip() == "プランを立てる"


def strip_trigger(text: str) -> str:
    """「@AsobiAgent M1 日程調整」 → 「日程調整」."""
    return _TRIGGER.sub("", text, count=1).strip()


_WEEKDAYS = "月火水木金土日"


def resolve_day(day: Optional[str], today: date) -> Optional[date]:
    """A calendar date for a day phrase like 来週土曜, 土曜, 明日 or 10/18, counted from `today` (a date)."""
    import datetime as _dt
    if not day:
        return None
    if day in ("今日", "今夜", "今晩"):
        return today
    if day == "明日":
        return today + _dt.timedelta(days=1)
    if day in ("明後日", "あさって"):
        return today + _dt.timedelta(days=2)
    m = re.match(r"^(\d{1,2})/(\d{1,2})$", day)
    if m:
        month, dom = int(m.group(1)), int(m.group(2))
        try:
            candidate = _dt.date(today.year, month, dom)
        except ValueError:
            return None
        return candidate if candidate >= today else _dt.date(today.year + 1, month, dom)
    m = re.match(r"^(再来週|来週|今週)?([月火水木金土日])曜?$", day)
    if m:
        target = _WEEKDAYS.index(m.group(2))
        monday = today - _dt.timedelta(days=today.weekday())
        if m.group(1):
            weeks = {"今週": 0, "来週": 1, "再来週": 2}[m.group(1)]
            return monday + _dt.timedelta(days=7 * weeks + target)
        ahead = (target - today.weekday()) % 7
        return today + _dt.timedelta(days=ahead or 7)
    if day in ("週末", "今週末"):
        return today + _dt.timedelta(days=(5 - today.weekday()) % 7)
    if day == "来週末":
        monday = today - _dt.timedelta(days=today.weekday())
        return monday + _dt.timedelta(days=12)
    return None
