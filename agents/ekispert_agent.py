"""
Agent 2: the fairest station to meet at.

One Ekispert range search returns every station that all members can reach, with each member's average
travel time (no timetable). The winner has the smallest worst-case trip, then the smallest gap between
the fastest and slowest member, then the lowest average.
"""

from typing import Any, Optional

from services.ekispert_client import EkispertClient


def _score(point: dict[str, Any]) -> tuple:
    minutes = point["minutes"]
    return (max(minutes), max(minutes) - min(minutes), sum(minutes) / len(minutes), sum(point["transfers"]))


async def find_hub(ekispert: EkispertClient, stations: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """`stations` are the members' resolved stations (name, code). Returns the hub, or None."""
    unique: dict[str, dict[str, Any]] = {}
    for st in stations:
        unique.setdefault(st["name"], st)
    names = list(unique)
    if len(names) == 1:
        only = unique[names[0]]
        return {"name": only["name"], "code": only["code"], "minutes": {only["name"]: 0},
                "transfers": {only["name"]: 0}, "max": 0, "spread": 0, "avg": 0, "alternatives": [],
                "upper_minutes": 0}

    points: list[dict[str, Any]] = []
    upper = 0
    for upper in (45, 60, 90):
        points = await ekispert.search_ranges(names, upper_minutes=upper)
        if points:
            break
    if not points:
        return None

    ranked = sorted(points, key=_score)
    best = ranked[0]
    minutes = dict(zip(names, best["minutes"]))
    transfers = dict(zip(names, best["transfers"]))
    return {
        "name": best["name"],
        "code": best["code"],
        "minutes": minutes,
        "transfers": transfers,
        "max": max(best["minutes"]),
        "spread": max(best["minutes"]) - min(best["minutes"]),
        "avg": round(sum(best["minutes"]) / len(best["minutes"]), 1),
        "alternatives": [p["name"] for p in ranked[1:3]],
        "upper_minutes": upper,
    }
