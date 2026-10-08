"""
Agent 3: real venues near the meeting station, from HotPepper.

The LLM's job is narrow: drop places that are closed at the planned time, order the rest for this group,
and write one line on why each fits. Crowding is a rule-based estimate from seats, private rooms and
walking distance, labelled 推定 everywhere it appears, because no live crowd data is used.
"""

import json
import logging
import math
from typing import Any, Callable, Optional

from services.hotpepper_client import BUDGETS, HotPepperClient
from services.llm_client import LLMClient
from services.places_client import distance_m

log = logging.getLogger("spot_agent")

SHORTLIST_SIZE = 9   # three pages of three
BUDGET_ORDER = list(BUDGETS)  # cheapest first, as Recruit lists them
SYSTEM = "You recommend restaurants for a group outing in Japan. Reply in Japanese inside a JSON object."


def walk_minutes(shop: dict[str, Any], station: dict[str, Any]) -> Optional[int]:
    if None in (shop.get("lat"), shop.get("lng"), station.get("lat"), station.get("lng")):
        return None
    meters = distance_m(station["lat"], station["lng"], shop["lat"], shop["lng"])
    return max(1, math.ceil(meters * 1.25 / 80))  # 80 m/min, 25% for streets not being straight lines


def crowd_estimate(shop: dict[str, Any], walk_min: Optional[int]) -> dict[str, Any]:
    score = 0
    facts = []
    if walk_min is not None:
        facts.append(f"駅から徒歩約{walk_min}分")
        if walk_min >= 5:
            score -= 1
    if (shop.get("private_room") or "").startswith("あり"):
        score -= 1
        facts.append("個室あり")
    capacity = shop.get("capacity")
    if capacity and capacity >= 80:
        score += 1
        facts.append(f"{capacity}席の大型店")
    elif capacity:
        facts.append(f"{capacity}席")
    level = "低" if score <= -1 else "中" if score == 0 else "高"
    return {"level": level, "facts": facts}


def cheaper_budget(shops: list[dict[str, Any]], current: Optional[str]) -> str:
    """One HotPepper budget band below what the group was shown (or below `current`)."""
    if current in BUDGET_ORDER:
        idx = BUDGET_ORDER.index(current)
    else:
        seen = [BUDGET_ORDER.index(b) for b in (_budget_code(s) for s in shops) if b in BUDGET_ORDER]
        idx = sorted(seen)[len(seen) // 2] if seen else BUDGET_ORDER.index("B003")
    return BUDGET_ORDER[max(0, idx - 1)]


def _budget_code(shop: dict[str, Any]) -> Optional[str]:
    name = shop.get("budget")
    return next((code for code, label in BUDGETS.items() if label == name), None)


async def search_shops(hotpepper: HotPepperClient, station: dict[str, Any], details: dict[str, Any],
                       pax: int, exclude: set[str]) -> list[dict[str, Any]]:
    """HotPepper search near the station, loosening filters until there are enough candidates."""
    range_code = 2 if details.get("near") else 3
    attempts = [
        dict(genre=details.get("genre"), budget=details.get("budget"), keyword=details.get("keyword")),
        dict(genre=details.get("genre"), budget=details.get("budget"), keyword=None),
        dict(genre=details.get("genre"), budget=None, keyword=None),
        dict(genre=None, budget=None, keyword=None),
    ]
    seen_params = []
    shops: list[dict[str, Any]] = []
    for params in attempts:
        if params in seen_params:
            continue
        seen_params.append(params)
        found = await hotpepper.search(
            station["lat"], station["lng"], range_code=range_code, lunch=details.get("meal") == "lunch",
            private_room=bool(details.get("private_room")), **params)
        shops = [s for s in found if s["id"] not in exclude and (not s.get("capacity") or s["capacity"] >= pax)]
        if len(shops) >= 3:
            break
    return shops


def _rule_based_order(shops: list[dict[str, Any]], details: dict[str, Any]) -> list[dict[str, Any]]:
    rank = {"低": 0, "中": 1, "高": 2}
    quiet = details.get("quiet", True)
    return sorted(shops, key=lambda s: ((rank[s["crowd"]["level"]] if quiet else 0),
                                        0 if s.get("featured") else 1, s.get("walk_min") or 99))


def _fallback_reason(shop: dict[str, Any]) -> str:
    bits = [shop.get("genre") or "", *shop["crowd"]["facts"][:2]]
    return "・".join(b for b in bits if b)[:60]


async def shortlist(llm: LLMClient, hotpepper: HotPepperClient, station: dict[str, Any],
                    details: dict[str, Any], pax: int, exclude: Optional[set[str]] = None,
                    use_llm: bool = True,
                    featured: Optional[Callable[[dict[str, Any]], Optional[dict]]] = None) -> list[dict[str, Any]]:
    """Up to nine venues, best first: [{id, reason, crowd, walk_min}]."""
    shops = await search_shops(hotpepper, station, details, pax, exclude or set())
    for shop in shops:
        shop["walk_min"] = walk_minutes(shop, station)
        shop["crowd"] = crowd_estimate(shop, shop["walk_min"])
        shop["featured"] = bool(featured and featured(shop))
    ordered = _rule_based_order(shops, details)[:15]

    picks: list[dict[str, Any]] = []
    if use_llm and llm.available and ordered:
        candidates = [{
            "id": s["id"], "name": s["name"], "genre": s.get("genre"), "catch": (s.get("catch") or "")[:60],
            "budget": s.get("budget"), "open": (s.get("open") or "")[:160], "close": s.get("close"),
            "lunch": s.get("lunch"), "private_room": (s.get("private_room") or "")[:20],
            "seats": s.get("capacity"), "walk_min": s.get("walk_min"), "crowd_estimate": s["crowd"]["level"],
            "featured_by_time_out": s["featured"],
        } for s in ordered]
        prompt = f"""A group of {pax} wants: {json.dumps({k: details.get(k) for k in ('day', 'time', 'meal', 'preferences', 'quiet')}, ensure_ascii=False)}
Candidates near {station['name']} station (from HotPepper):
{json.dumps(candidates, ensure_ascii=False)}

Return {{"picks": [{{"id": "...", "reason": "one short Japanese sentence, max 40 characters"}}]}}
- Up to {SHORTLIST_SIZE} picks, best fit first.
- Leave out places whose opening hours clearly exclude the planned day/time.
- If the group wants to avoid crowds, prefer crowd_estimate 低.
- The reason must only use facts given above; do not invent dishes, reviews, or ratings."""
        raw = await llm.generate_json(prompt, SYSTEM, max_tokens=900)
        by_id = {s["id"]: s for s in ordered}
        for item in raw.get("picks", []) if isinstance(raw.get("picks"), list) else []:
            shop = by_id.pop(str(item.get("id")), None) if isinstance(item, dict) else None
            if shop:
                reason = str(item.get("reason") or "").strip()[:60] or _fallback_reason(shop)
                picks.append({"id": shop["id"], "reason": reason, "crowd": shop["crowd"], "walk_min": shop["walk_min"]})
    if not picks:
        picks = [{"id": s["id"], "reason": _fallback_reason(s), "crowd": s["crowd"], "walk_min": s["walk_min"]}
                 for s in ordered]
    return picks[:SHORTLIST_SIZE]
