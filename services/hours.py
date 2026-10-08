"""
Rule-based reading of Japanese opening-hours text, so venues closed at the planned time can be skipped
without an LLM. Handles HotPepper's format and Time Out's:

  HotPepper open:  "月～金: 11:00～13:45 （料理L.O. 12:45）17:00～23:00 土: 17:00～23:00"
  HotPepper close: "日、祝日" / "月曜日" / "なし" / "不定休"
  Time Out hours:  "17〜23時／定休日は月・火曜" / "11時30分〜15時、17〜22時"

open_at() answers True, False, or None when the text is too unclear to say. Callers only drop False.
"""

import re
from typing import Optional

DAYS = "月火水木金土日"
_DASH = "[〜～~\\-－ー―？?]"     # Time Out pages sometimes have ？ where 〜 was meant
# Parentheses that only hold last-order or entry notes; other parentheses can hold day exceptions.
_NOTE_PAREN = re.compile(r"[（(][^）)]*(?:L\.?O|ラストオーダー|入店|料理|ドリンク|最終)[^）)]*[）)]")
_PAREN = re.compile(r"[（(][^）)]*[）)]")
_TIME = r"(\d{1,2})(?:[:：](\d{2})|時(?:(\d{1,2})分|(半))?)?"
_RANGE = re.compile(rf"(翌)?{_TIME}\s*{_DASH}\s*(翌)?{_TIME}")
_DAY_TOKEN = rf"(?:平日|祝日|祝前日|祝後日|[{DAYS}](?:曜日?)?|[、・,]|{_DASH})"
# 「月～金:」 (HotPepper) or 「土・日曜・祝日は」 (Time Out); not the 日 in 定休日は / 毎日 / 平日.
_DAY_PREFIX = re.compile(rf"(?<![休定毎平])((?:{_DAY_TOKEN})+?)\s*(?:[:：]|は)")
_DAY_SPAN = re.compile(rf"([{DAYS}])(?:曜日?)?\s*{_DASH}\s*([{DAYS}])")


def _minutes(hour: str, minute: Optional[str], minute_ja: Optional[str], half: Optional[str]) -> int:
    return int(hour) * 60 + (30 if half else int(minute or minute_ja or 0))


def parse_ranges(text: str) -> list[tuple[int, int]]:
    """Every 'start〜end' in the text as minutes after midnight (end may pass 24:00)."""
    out = []
    for m in _RANGE.finditer(_PAREN.sub(" ", text or "")):
        next_a, h1, mm1, jm1, half1, next_b, h2, mm2, jm2, half2 = m.groups()
        start = _minutes(h1, mm1, jm1, half1) + (24 * 60 if next_a else 0)
        end = _minutes(h2, mm2, jm2, half2)
        if next_b or end <= start:
            end += 24 * 60
        if 0 <= start < 48 * 60 and start < end <= 54 * 60:
            out.append((start, end))
    return out


def _day_set(prefix: str) -> set[int]:
    days: set[int] = set()
    if "平日" in prefix:
        days.update(range(5))
        prefix = prefix.replace("平日", "")
    for a, b in _DAY_SPAN.findall(prefix):
        i, j = DAYS.index(a), DAYS.index(b)
        days.update(range(i, j + 1) if i <= j else list(range(i, 7)) + list(range(0, j + 1)))
    without_spans = _DAY_SPAN.sub("", prefix).replace("祝日", "").replace("祝前日", "").replace("祝後日", "")
    days.update(DAYS.index(ch) for ch in without_spans if ch in DAYS)
    return days


def _clean(text: str) -> str:
    text = _NOTE_PAREN.sub(" ", text or "")
    return re.sub(r"[（）()]", " ", text)


def ranges_for_day(text: str, weekday: int) -> Optional[list[tuple[int, int]]]:
    """Opening ranges on `weekday` (0 = Monday): [] means closed that day, None means the text doesn't say.

    HotPepper lists every open day with a prefix (月～金: …), so a day that isn't listed is closed.
    Time Out writes default hours first and exceptions after (…（土・日曜は12～24時）), so a day that
    isn't listed gets the default hours."""
    text = _clean(text)
    prefixes = [m for m in _DAY_PREFIX.finditer(text) if _day_set(m.group(1))]
    if not prefixes:
        return parse_ranges(text) or None
    default = parse_ranges(text[:prefixes[0].start()])
    found_day = False
    ranges: list[tuple[int, int]] = []
    for i, m in enumerate(prefixes):
        segment = text[m.end(): prefixes[i + 1].start() if i + 1 < len(prefixes) else len(text)]
        if weekday in _day_set(m.group(1)):
            found_day = True
            ranges += parse_ranges(segment)
    if not found_day:
        return default if default else []
    return ranges or None


def closed_days(text: str) -> set[int]:
    """Weekdays a shop is regularly closed, from a 定休日 / close field. Unclear text gives an empty set."""
    if not text or any(w in text for w in ("不定休", "なし", "無休", "年中無休")):
        return set()
    m = re.search(r"定休日[はー:：\s]*([^／/。（(]*)", text)
    part = m.group(1) if m else text
    return _day_set(part)


def open_at(open_text: Optional[str], close_text: Optional[str], weekday: Optional[int],
            minute_of_day: Optional[int]) -> Optional[bool]:
    if weekday is None:
        return None
    if weekday in closed_days(close_text or ""):
        return False
    if minute_of_day is None:
        return None
    ranges = ranges_for_day(open_text or "", weekday)
    if ranges is None:
        return None
    if not ranges:
        return False
    # Also count yesterday's late-night hours that run past midnight.
    yesterday = ranges_for_day(open_text or "", (weekday - 1) % 7) or []
    return any(s <= minute_of_day < e for s, e in ranges) or \
        any(s <= minute_of_day + 24 * 60 < e for s, e in yesterday)


def split_time_ok(hours: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Time Out puts hours and closed days in one string: '17〜23時／定休日は月・火曜'."""
    if not hours:
        return None, None
    parts = re.split(r"[／/]", hours, maxsplit=1)
    close = next((p for p in parts if "定休" in p or "休み" in p), None)
    open_part = next((p for p in parts if p is not close), hours)
    return open_part, close
