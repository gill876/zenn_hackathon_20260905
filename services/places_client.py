"""
Google Places API (New): look up a restaurant's phone number so the call-script card can offer a one-tap
call. HotPepper's API doesn't return phone numbers.

Google's terms don't allow caching the phone number, so this is called once per decided venue, and a
daily cap (DAILY_PLACES_LIMIT) keeps it inside the free monthly usage.
"""

import logging
import math
from typing import Optional

import httpx

log = logging.getLogger("places")

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class PlacesClient:
    def __init__(self, api_key: str, usage=None, timeout: float = 8.0):
        self.api_key = api_key
        self._usage = usage
        self._timeout = timeout

    async def phone_number(self, name: str, address: str, lat: Optional[float], lng: Optional[float]) -> Optional[str]:
        if not self.api_key:
            return None
        if self._usage and not await self._usage.take("places"):
            log.info("daily Places limit reached; skipping phone lookup")
            return None
        body: dict = {"textQuery": f"{name} {address or ''}".strip(), "languageCode": "ja", "regionCode": "JP",
                      "pageSize": 1}
        if lat is not None and lng is not None:
            body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": 300.0}}
        headers = {"X-Goog-Api-Key": self.api_key,
                   "X-Goog-FieldMask": "places.displayName,places.nationalPhoneNumber,places.location"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(SEARCH_URL, json=body, headers=headers)
            if resp.status_code >= 300:
                log.warning("Places -> %s %s", resp.status_code, resp.text[:300])
                return None
            places = resp.json().get("places", [])
        except httpx.HTTPError as e:
            log.warning("Places request failed: %s", e)
            return None
        if not places:
            return None
        place = places[0]
        loc = place.get("location") or {}
        # Only trust the match if it's the same spot as HotPepper's shop.
        if lat is not None and lng is not None and loc:
            if distance_m(lat, lng, loc.get("latitude", 0), loc.get("longitude", 0)) > 250:
                return None
        return place.get("nationalPhoneNumber")


    async def find_place(self, name: str, lat: Optional[float], lng: Optional[float], radius_m: float = 2000) -> Optional[dict]:
        """A place by name near a point: name, address, phone, location and its Google Maps link."""
        if not self.api_key or not name:
            return None
        if self._usage and not await self._usage.take("places"):
            return None
        body: dict = {"textQuery": name, "languageCode": "ja", "regionCode": "JP", "pageSize": 1}
        if lat is not None and lng is not None:
            body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius_m}}
        headers = {"X-Goog-Api-Key": self.api_key,
                   "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,"
                                       "places.nationalPhoneNumber,places.googleMapsUri,places.primaryTypeDisplayName"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(SEARCH_URL, json=body, headers=headers)
            if resp.status_code >= 300:
                log.warning("Places find -> %s %s", resp.status_code, resp.text[:200])
                return None
            places = resp.json().get("places", [])
        except httpx.HTTPError as e:
            log.warning("Places find failed: %s", e)
            return None
        if not places:
            return None
        p = places[0]
        loc = p.get("location") or {}
        return {"place_id": p.get("id"), "name": (p.get("displayName") or {}).get("text") or name,
                "address": p.get("formattedAddress"), "telephone": p.get("nationalPhoneNumber"),
                "lat": loc.get("latitude"), "lng": loc.get("longitude"), "url": p.get("googleMapsUri"),
                "genre": (p.get("primaryTypeDisplayName") or {}).get("text")}
