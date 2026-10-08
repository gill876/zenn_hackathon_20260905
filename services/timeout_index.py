"""
"Time Out で紹介" badge: matches a HotPepper shop to a place Time Out Japan has written about, using the
facts collected by jobs/timeout_crawl.py (name and coordinates). The bot shows a link to Time Out's
page and nothing else from it.
"""

import hashlib
import json
import logging
import pathlib
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Optional

from services.places_client import distance_m

log = logging.getLogger("timeout_index")

DEFAULT_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "timeout_venues.jsonl"
_STRIP = re.compile(r"[\s　・･\-‐－ー—_.,、。!！?？'’\"“”()（）【】\[\]「」『』&＆]+")
# Branch suffixes like 銀座店 / 本店 / 新宿東口店 shouldn't stop a match.
_BRANCH = re.compile(r"[一-龥ァ-ヴA-Za-z0-9]{0,8}(本店|店)$")


def _norm(name: str) -> str:
    text = unicodedata.normalize("NFKC", name or "").lower()
    return _STRIP.sub("", text)


_GENERIC = {"店", "本店", "別館", "ダイニング", "dining", "bar", "バー", "cafe", "カフェ", "restaurant", "レストラン",
            "居酒屋", "酒場", "食堂", "東京", "tokyo", "ビル", "1f", "2f", "b1f"}


def _tokens(name: str, place_words: set[str]) -> set[str]:
    text = unicodedata.normalize("NFKC", name or "").lower()
    out = set()
    for tok in _STRIP.split(text):
        tok = re.sub(r"(本店|店)$", "", tok)
        if len(tok) >= 2 and tok not in _GENERIC and not any(w and w in tok for w in place_words):
            out.add(tok)
    return out


def _shares_distinct_token(a: str, b: str, place_words: set[str]) -> bool:
    return bool(_tokens(a, place_words) & _tokens(b, place_words))


def _similar(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return min(len(na), len(nb)) >= 2
    ba, bb = _BRANCH.sub("", na) or na, _BRANCH.sub("", nb) or nb
    if ba and bb and (ba in bb or bb in ba) and min(len(ba), len(bb)) >= 3:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.72


def place_id(url: str) -> str:
    return "TO" + hashlib.sha1(url.encode()).hexdigest()[:12]


def as_shop(place: dict[str, Any]) -> dict[str, Any]:
    """A Time Out place in the same shape as a HotPepper shop, so cards and votes treat both alike."""
    section = place.get("section") or ""
    genre = "バー" if section in ("バー", "ナイトライフ") or place.get("type") == "BarOrPub" else "レストラン"
    if place.get("type") == "CafeOrCoffeeShop":
        genre = "カフェ"
    return {"id": place["id"], "name": place["name"], "address": place.get("address"), "station_name": None,
            "lat": place["lat"], "lng": place["lng"], "genre": genre, "budget": None, "budget_average": None,
            "catch": None, "capacity": None, "private_room": None, "lunch": None,
            "open": place.get("hours"), "close": None, "url": place["url"], "photo": None,
            "telephone": place.get("telephone"), "source": "timeout"}


class TimeOutIndex:
    def __init__(self, places: list[dict[str, Any]]):
        self._grid: dict[tuple[int, int], list[dict[str, Any]]] = {}
        self._by_id: dict[str, dict[str, Any]] = {}
        for p in places:
            p = dict(p, id=p.get("id") or place_id(p["url"]))
            self._grid.setdefault(self._cell(p["lat"], p["lng"]), []).append(p)
            self._by_id[p["id"]] = p
        self.size = len(self._by_id)

    def get(self, pid: str) -> Optional[dict[str, Any]]:
        return self._by_id.get(pid)

    def nearby(self, lat: float, lng: float, radius_m: float = 1000) -> list[tuple[float, dict[str, Any]]]:
        """Places within radius_m, nearest first."""
        cx, cy = self._cell(lat, lng)
        reach = int(radius_m / 200) + 1
        found = []
        for dx in range(-reach, reach + 1):
            for dy in range(-reach, reach + 1):
                for place in self._grid.get((cx + dx, cy + dy), []):
                    d = distance_m(lat, lng, place["lat"], place["lng"])
                    if d <= radius_m:
                        found.append((d, place))
        return sorted(found, key=lambda x: x[0])

    @staticmethod
    def _cell(lat: float, lng: float) -> tuple[int, int]:
        return int(lat * 500), int(lng * 500)   # ~200 m cells

    @classmethod
    def load(cls, path: pathlib.Path = DEFAULT_PATH) -> "TimeOutIndex":
        places = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    places.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        log.info("Time Out index: %d places", len(places))
        return cls(places)

    def match(self, shop: dict[str, Any], max_meters: float = 120) -> Optional[dict[str, Any]]:
        if shop.get("lat") is None or shop.get("lng") is None or not self.size:
            return None
        cx, cy = self._cell(shop["lat"], shop["lng"])
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for place in self._grid.get((cx + dx, cy + dy), []):
                    d = distance_m(shop["lat"], shop["lng"], place["lat"], place["lng"])
                    if d > max_meters:
                        continue
                    area = {_norm(shop.get("station_name") or "")}
                    if _similar(shop.get("name", ""), place["name"]) or (
                            d <= 80 and _shares_distinct_token(shop.get("name", ""), place["name"], area)):
                        if best is None or d < best[0]:
                            best = (d, place)
        if not best:
            return None
        place = best[1]
        return {"id": place["id"], "url": place["url"], "name": place["name"],
                "telephone": place.get("telephone"), "hours": place.get("hours")}
