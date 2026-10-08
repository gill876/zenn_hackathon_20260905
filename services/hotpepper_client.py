"""
ホットペッパーグルメ Webサービス client (グルメサーチAPI).

Recruit's terms require showing a credit wherever this data appears and refreshing cached data within
24 hours, so every cached response here expires after 24 hours.
"""

import hashlib
import json
import logging
import time
from typing import Any, Callable, Optional

import httpx

log = logging.getLogger("hotpepper")

GOURMET_URL = "https://webservice.recruit.co.jp/hotpepper/gourmet/v1/"
CREDIT_TEXT = "Powered by ホットペッパーグルメ Webサービス"
CREDIT_URL = "https://webservice.recruit.co.jp/"
CACHE_SECONDS = 24 * 3600

GENRES = {
    "G001": "居酒屋", "G002": "ダイニングバー・バル", "G003": "創作料理", "G004": "和食", "G005": "洋食",
    "G006": "イタリアン・フレンチ", "G007": "中華", "G008": "焼肉・ホルモン", "G017": "韓国料理",
    "G009": "アジア・エスニック料理", "G010": "各国料理", "G011": "カラオケ・パーティ", "G012": "バー・カクテル",
    "G013": "ラーメン", "G016": "お好み焼き・もんじゃ", "G014": "カフェ・スイーツ", "G015": "その他グルメ",
}
BUDGETS = {
    "B009": "～500円", "B010": "501～1000円", "B011": "1001～1500円", "B001": "1501～2000円",
    "B002": "2001～3000円", "B003": "3001～4000円", "B008": "4001～5000円", "B015": "5001～6000円",
    "B016": "6001～7000円", "B017": "7001～8000円", "B018": "8001～9000円", "B019": "9001～10000円",
    "B020": "10001～12000円", "B021": "12001～15000円", "B012": "15001～20000円", "B013": "20001～30000円",
    "B014": "30001円～",
}


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_shop(s: dict[str, Any]) -> dict[str, Any]:
    photo = s.get("photo", {})
    return {
        "id": s.get("id"),
        "name": s.get("name"),
        "address": s.get("address"),
        "station_name": s.get("station_name"),
        "lat": float(s["lat"]) if s.get("lat") else None,
        "lng": float(s["lng"]) if s.get("lng") else None,
        "genre": (s.get("genre") or {}).get("name"),
        "genre_code": (s.get("genre") or {}).get("code"),
        "genre_catch": (s.get("genre") or {}).get("catch"),
        "sub_genre": (s.get("sub_genre") or {}).get("name"),
        "budget": (s.get("budget") or {}).get("name"),
        "budget_average": (s.get("budget") or {}).get("average"),
        "catch": s.get("catch"),
        "capacity": _int_or_none(s.get("capacity")),
        "party_capacity": _int_or_none(s.get("party_capacity")),
        "private_room": s.get("private_room"),
        "non_smoking": s.get("non_smoking"),
        "lunch": s.get("lunch"),
        "open": s.get("open"),
        "close": s.get("close"),
        "url": (s.get("urls") or {}).get("pc"),
        "photo": (photo.get("pc") or {}).get("l") or (photo.get("mobile") or {}).get("l"),
        "access": s.get("mobile_access") or s.get("access"),
    }


class HotPepperClient:
    def __init__(self, api_key: str, store=None, usage=None, clock: Callable[[], float] = time.time,
                 timeout: float = 15.0):
        self.api_key = api_key
        self._store = store
        self._usage = usage
        self._clock = clock
        self._timeout = timeout

    async def _get(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("HOTPEPPER_API_KEY is not set")
        cache_key = hashlib.sha1(json.dumps(params, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if self._store:
            cached = await self._store.get("cache_hotpepper", cache_key)
            if cached:
                return cached["shops"]
        if self._usage:
            await self._usage.note("hotpepper")
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(GOURMET_URL, params={**params, "key": self.api_key, "format": "json"})
        resp.raise_for_status()
        results = resp.json().get("results", {})
        if "error" in results:
            raise RuntimeError(f"HotPepper error: {results['error']}")
        shops = [normalize_shop(s) for s in results.get("shop", [])]
        if self._store:
            await self._store.set("cache_hotpepper", cache_key,
                                  {"shops": shops, "expire_at": self._clock() + CACHE_SECONDS})
            for shop in shops:
                await self._store.set("cache_shop", shop["id"], {"shop": shop, "expire_at": self._clock() + CACHE_SECONDS})
        return shops

    async def search(self, lat: float, lng: float, *, range_code: int = 3, genre: Optional[str] = None,
                     budget: Optional[str] = None, lunch: bool = False, private_room: bool = False,
                     keyword: Optional[str] = None, count: int = 30) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"lat": round(lat, 6), "lng": round(lng, 6), "range": range_code,
                                  "count": count, "order": 4}
        if genre:
            params["genre"] = genre
        if budget:
            params["budget"] = budget
        if lunch:
            params["lunch"] = 1
        if private_room:
            params["private_room"] = 1
        if keyword:
            params["keyword"] = keyword
        return await self._get(params)

    async def shops_by_ids(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """Shop details by HotPepper ID, from the 24-hour cache when possible."""
        found: dict[str, dict[str, Any]] = {}
        missing = []
        for shop_id in ids:
            cached = await self._store.get("cache_shop", shop_id) if self._store else None
            if cached:
                found[shop_id] = cached["shop"]
            else:
                missing.append(shop_id)
        if missing:
            for shop in await self._get({"id": ",".join(missing[:20]), "count": len(missing[:20])}):
                found[shop["id"]] = shop
        return found
