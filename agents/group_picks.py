"""
Agent 3 with profiles: real places that cover the whole group's tastes.

Instead of searching one kind of food, each slot in the carousel is assigned a kind (services/taste.py
allocate: everyone's favourite first, then the most-liked), and each kind gets its own HotPepper search near
the meeting station. Places of a kind anyone dropped, or closed at the planned time, never appear. So one
carousel has something for everyone, and nobody has to vote on "what kind of food" first.
"""

import logging
from typing import Any, Callable, Optional

from agents.spot_agent import _rule_based_order, crowd_estimate, is_open, planned_moment, time_out_picks, walk_minutes
from services.hotpepper_client import HotPepperClient
from services.taste import BY_ID, GENRE_TO_KIND, allocate
from services.timeout_index import TimeOutIndex

log = logging.getLogger("group_picks")

MAX_KINDS = 6


def _reason(likers: list[str], shop: dict[str, Any], walk: Optional[int]) -> str:
    who = "・".join(likers[:3]) + ("ほか" if len(likers) > 3 else "")
    bits = [f"♡ {who}の好み" if likers else None, shop.get("genre"), f"駅から徒歩約{walk}分" if walk else None]
    return " · ".join(b for b in bits if b)[:60]


async def group_picks(hotpepper: HotPepperClient, station: dict[str, Any], details: dict[str, Any], pax: int,
                      taste: dict[str, Any], exclude: Optional[set[str]] = None,
                      featured: Optional[Callable[[dict[str, Any]], Optional[dict]]] = None,
                      timeout: Optional[TimeOutIndex] = None, size: int = 12) -> list[dict[str, Any]]:
    exclude = set(exclude or ())
    dropped_genres = set(taste.get("dropped_genres", []))
    kinds = {k["id"]: k for k in taste["kinds"]}
    # Something said in the chat this time ("和食がいい") beats the profiles, unless someone dropped it.
    chat_kind = GENRE_TO_KIND.get(details.get("genre") or "")
    if chat_kind and BY_ID[chat_kind]["genre"] not in dropped_genres:
        slots = [chat_kind] * size
        kinds.setdefault(chat_kind, {"id": chat_kind, "label": BY_ID[chat_kind]["label"],
                                     "genre": BY_ID[chat_kind]["genre"], "likers": [], "keyword": None})
    else:
        slots = allocate(taste, slots=size)
    distinct = list(dict.fromkeys(slots))[:MAX_KINDS]
    slots = [s for s in slots if s in distinct]
    weekday, minute = planned_moment(details)
    quiet = taste.get("quiet", True) if details.get("quiet") is None else details.get("quiet")

    async def candidates(genre: Optional[str], keyword: Optional[str]) -> list[dict[str, Any]]:
        found = await hotpepper.search(
            station["lat"], station["lng"], range_code=2 if details.get("near") else 3, genre=genre,
            keyword=keyword, budget=details.get("budget"), lunch=details.get("meal") == "lunch",
            private_room=bool(details.get("private_room") or taste.get("private")))
        ok = []
        for s in found:
            if s["id"] in exclude or s.get("genre_code") in dropped_genres:
                continue
            if s.get("capacity") and s["capacity"] < pax:
                continue
            if is_open(s, weekday, minute) is False:
                continue
            s["walk_min"] = walk_minutes(s, station)
            s["crowd"] = crowd_estimate(s, s["walk_min"])
            match = featured(s) if featured else None
            s["featured"] = bool(match)
            s["featured_id"] = (match or {}).get("id")
            ok.append(s)
        return _rule_based_order(ok, {"quiet": quiet})

    pools: dict[str, list[dict[str, Any]]] = {}
    for kind_id in distinct:
        kind = kinds[kind_id]
        keyword = details.get("keyword") or kind.get("keyword")
        pool = await candidates(kind["genre"], keyword)
        if len(pool) < 2 and keyword:
            pool = await candidates(kind["genre"], None)
        pools[kind_id] = pool

    picks: list[dict[str, Any]] = []
    used: set[str] = set()
    for kind_id in slots:
        pool = pools.get(kind_id, [])
        shop = next((s for s in pool if s["id"] not in used), None)
        if not shop:
            continue
        used.add(shop["id"])
        likers = kinds[kind_id].get("likers", [])
        picks.append({"id": shop["id"], "kind": kind_id, "likers": likers, "crowd": shop["crowd"],
                      "walk_min": shop["walk_min"], "reason": _reason(likers, shop, shop["walk_min"])})

    if len(picks) < min(size, 6):
        # Thin area or no profiles yet: fill from a general search, still respecting dropped kinds.
        for shop in await candidates(None, details.get("keyword")):
            if len(picks) >= size:
                break
            if shop["id"] not in used:
                used.add(shop["id"])
                picks.append({"id": shop["id"], "kind": GENRE_TO_KIND.get(shop.get("genre_code") or ""), "likers": [],
                              "crowd": shop["crowd"], "walk_min": shop["walk_min"],
                              "reason": _reason([], shop, shop["walk_min"])})

    # One slot per page of six can be a place Time Out has written about, matching a liked kind.
    if timeout and distinct:
        matched = {p.get("featured_id") for p in picks}
        extra = []
        for kind_id in distinct:
            for tp in time_out_picks(timeout, station, dict(details, genre=kinds[kind_id]["genre"], budget=None),
                                     exclude | used, {m for m in matched if m}, limit=1):
                tp["kind"], tp["likers"] = kind_id, kinds[kind_id].get("likers", [])
                tp["reason"] = "Time Out で紹介 · " + (_reason(tp["likers"], {}, tp.get("walk_min")) or "")
                extra.append(tp)
                used.add(tp["id"])
            if len(extra) >= 2:
                break
        for i, tp in enumerate(extra):
            pos = 5 + i * 6
            if pos <= len(picks):
                picks.insert(pos, tp)
    return picks[:size]
