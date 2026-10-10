"""
Date poll (日程調整), chouseisan-style.

The organizer picks candidate dates on a calendar page; everyone marks ○ (can come), △ (maybe) or × per date
on the poll page; the organizer closes it in the chat. Stored per group (hashed ID) for at most 14 days and
deleted when a plan starts from it.

Best date: most ○, then most △, then fewest ×, then the earliest.
"""

import datetime as dt
from typing import Any, Optional

from services.ids import new_nonce
from services.store import KEEP
from services.usage import JST

POLL_DAYS = 14
MARKS = {"o", "t", "x"}
WEEKDAYS = "月火水木金土日"
SLOT_LABELS = {"lunch": "ランチ", "dinner": "夜"}


def date_label(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def slot_label(slot: Optional[str]) -> str:
    if not slot:
        return "未定"
    return SLOT_LABELS.get(slot, slot)


def tally(poll: dict[str, Any]) -> list[tuple[str, int, int, int]]:
    """[(iso date, ○, △, ×)] best first."""
    rows = []
    for d in poll.get("dates", []):
        marks = [a.get("a", {}).get(d) for a in poll.get("answers", {}).values()]
        rows.append((d, marks.count("o"), marks.count("t"), marks.count("x")))
    return sorted(rows, key=lambda r: (-r[1], -r[2], r[3], r[0]))


def people_for(poll: dict[str, Any], iso: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """([(uhash, name)] who said ○, [(uhash, name)] who said △) for a date."""
    yes, maybe = [], []
    for u, a in poll.get("answers", {}).items():
        mark = a.get("a", {}).get(iso)
        if mark == "o":
            yes.append((u, a.get("name", "メンバー")))
        elif mark == "t":
            maybe.append((u, a.get("name", "メンバー")))
    return yes, maybe


def valid_dates(dates: list[str], today: dt.date) -> list[str]:
    out = []
    for d in dates:
        try:
            day = dt.date.fromisoformat(d)
        except (TypeError, ValueError):
            continue
        if today <= day <= today + dt.timedelta(days=120):
            out.append(day.isoformat())
    return sorted(set(out))[:14]


def valid_slot(slot: Optional[str]) -> Optional[str]:
    if slot in SLOT_LABELS:
        return slot
    if isinstance(slot, str) and len(slot) == 5 and slot[2] == ":" and slot.replace(":", "").isdigit():
        hour, minute = int(slot[:2]), int(slot[3:])
        if 0 <= hour < 30 and 0 <= minute < 60:
            return slot
    return None


async def start(store, ghash: str, organizer: str, organizer_name: str, now: float) -> dict[str, Any]:
    """The group's poll: the existing open/draft one, or a new draft."""
    def fn(docs):
        poll = docs[0]
        if poll and poll.get("status") in ("draft", "open"):
            return [KEEP], poll
        poll = {"nonce": new_nonce(), "status": "draft", "organizer": organizer, "organizer_name": organizer_name,
                "dates": [], "slot": None, "answers": {}, "announced": False, "created_at": now,
                "expire_at": now + POLL_DAYS * 86400}
        return [poll], poll

    return await store.transact([("polls", ghash)], fn)


async def set_dates(store, ghash: str, nonce: str, uhash: str, dates: list[str], slot: Optional[str],
                    now: float) -> tuple[str, Optional[dict[str, Any]]]:
    today = dt.datetime.fromtimestamp(now, JST).date()
    dates = valid_dates(dates, today)

    def fn(docs):
        poll = docs[0]
        if not poll or poll.get("nonce") != nonce or poll.get("status") == "closed":
            return [KEEP], ("gone", None)
        if poll.get("organizer") != uhash:
            return [KEEP], ("not_organizer", poll)
        if not dates:
            return [KEEP], ("no_dates", poll)
        poll = dict(poll, dates=dates, slot=valid_slot(slot), status="open")
        # Answers for dates that were removed no longer count.
        for a in poll.get("answers", {}).values():
            a["a"] = {d: m for d, m in a.get("a", {}).items() if d in dates}
        return [poll], ("ok", poll)

    return await store.transact([("polls", ghash)], fn)


async def answer(store, ghash: str, nonce: str, uhash: str, name: str,
                 marks: dict[str, str]) -> tuple[str, Optional[dict[str, Any]], bool]:
    def fn(docs):
        poll = docs[0]
        if not poll or poll.get("nonce") != nonce or poll.get("status") != "open":
            return [KEEP], ("gone", poll, False)
        clean = {d: m for d, m in marks.items() if d in poll["dates"] and m in MARKS}
        poll = dict(poll)
        answers = dict(poll.get("answers", {}))
        first = uhash not in answers
        answers[uhash] = {"name": name[:20], "a": clean}
        poll["answers"] = answers
        return [poll], ("ok", poll, first)

    return await store.transact([("polls", ghash)], fn)


def view(poll: dict[str, Any], uhash: str) -> dict[str, Any]:
    """What the poll page shows: the table with names, your own row, and whether you're the organizer."""
    people = [{"name": a.get("name", "メンバー"), "marks": a.get("a", {}), "me": u == uhash}
              for u, a in poll.get("answers", {}).items()]
    ranked = tally(poll)
    return {
        "status": poll.get("status"), "dates": [{"iso": d, "label": date_label(d)} for d in poll.get("dates", [])],
        "slot": poll.get("slot"), "slot_label": slot_label(poll.get("slot")),
        "organizer_name": poll.get("organizer_name"), "is_organizer": poll.get("organizer") == uhash,
        "people": people, "mine": poll.get("answers", {}).get(uhash, {}).get("a", {}),
        "best": ranked[0][0] if ranked and ranked[0][1] + ranked[0][2] > 0 else None,
    }
