"""
"💡 お店を提案する": turn what someone sends (a HotPepper link, a Google Maps link, or a shop name) into a
candidate card that joins the group's vote.

HotPepper links and names are looked up with the HotPepper API first (free); otherwise Google Places finds the
place near the meeting station. Tabelog and Instagram pages are not fetched; the bot asks for the name instead.
"""

import hashlib
import logging
import re
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from services.places_client import distance_m
from services.timeout_index import _similar

log = logging.getLogger("suggest")

URL = re.compile(r"https?://\S+")
HOTPEPPER_ID = re.compile(r"str(J\d{6,12})")
MAPS_HOSTS = ("maps.app.goo.gl", "goo.gl", "google.com", "google.co.jp", "maps.google")
NO_FETCH_HOSTS = ("tabelog.com", "instagram.com", "retty.me", "gnavi.co.jp")


class SuggestionError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _maps_place(url: str) -> tuple[Optional[str], Optional[float], Optional[float]]:
    """Name and coordinates from a Google Maps place URL (…/maps/place/<name>/@lat,lng,…)."""
    path = unquote(urlparse(url).path)
    name = None
    m = re.search(r"/place/([^/]+)", path)
    if m:
        name = m.group(1).replace("+", " ")
    q = parse_qs(urlparse(url).query).get("q")
    if not name and q:
        name = q[0]
    lat = lng = None
    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url) or re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
    return name, lat, lng


async def _expand(url: str) -> str:
    """Follow a short link (maps.app.goo.gl) to the full Google Maps URL, without reading the page."""
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        resp = await client.head(url)
        if resp.status_code >= 400:
            resp = await client.get(url)
    return str(resp.url)


async def resolve(deps, text: str, hub: dict[str, Any]) -> dict[str, Any]:
    """A shop dict for the suggestion. Raises SuggestionError with a message for the chat."""
    url_match = URL.search(text)
    name = URL.sub("", text).strip()
    lat, lng = hub.get("lat"), hub.get("lng")
    if url_match:
        url = url_match.group(0)
        host = urlparse(url).netloc.lower()
        if "hotpepper.jp" in host:
            m = HOTPEPPER_ID.search(url)
            if m:
                shop = (await deps.hotpepper.shops_by_ids([m.group(1)])).get(m.group(1))
                if shop:
                    return dict(shop, source="hotpepper")
            raise SuggestionError("そのホットペッパーのお店が見つかりませんでした。お店の名前で送ってみてください。")
        if any(h in host for h in NO_FETCH_HOSTS):
            if not name:
                raise SuggestionError("このリンクは読み取れないので、お店の名前も送ってください（例：@AsobiAgent 提案 利久 秋葉原）。")
        elif any(h in host for h in MAPS_HOSTS):
            full = await _expand(url) if "goo.gl" in host else url
            maps_name, mlat, mlng = _maps_place(full)
            name = maps_name or name
            if mlat is not None:
                lat, lng = mlat, mlng
    if not name:
        raise SuggestionError("お店のリンクか名前を送ってください（例：@AsobiAgent 提案 利久 秋葉原）。")

    # HotPepper first (free), near where the place should be.
    if lat is not None and lng is not None:
        for shop in await deps.hotpepper.search(lat, lng, range_code=4, keyword=name[:30], count=10):
            if _similar(shop.get("name", ""), name):
                return dict(shop, source="hotpepper")
    place = await deps.places.find_place(name, lat, lng)
    if not place or place.get("lat") is None:
        raise SuggestionError(f"「{name[:20]}」が見つかりませんでした。リンクか、もう少しくわしい名前で送ってください。")
    if hub.get("lat") is not None and distance_m(hub["lat"], hub["lng"], place["lat"], place["lng"]) > 15000:
        raise SuggestionError(f"「{place['name']}」は集合駅から遠すぎるようです。近くのお店を提案してください。")
    pid = "SG" + hashlib.sha1((place.get("place_id") or place["name"]).encode()).hexdigest()[:12]
    return {"id": pid, "name": place["name"], "address": place.get("address"), "lat": place["lat"],
            "lng": place["lng"], "genre": place.get("genre"), "url": place.get("url"),
            "telephone": place.get("telephone"), "photo": None, "source": "places"}
