"""
Turns words from chat into real stations, using Ekispert's station list.

Answers are cached for 90 days (stations don't move), including "not a station", so a name only costs
an Ekispert call the first time anyone uses it.
"""

import logging
import time
from typing import Any, Callable, Optional

from bot.text_parse import spelling_variants, station_candidates
from services.ekispert_client import EkispertClient, pick_station

log = logging.getLogger("stations")

CACHE_SECONDS = 90 * 86400


def _doc_id(name: str) -> str:
    return name.replace("/", "／")[:200]


class StationResolver:
    def __init__(self, ekispert: EkispertClient, store, clock: Callable[[], float] = time.time,
                 max_lookups_per_message: int = 3):
        self._ekispert = ekispert
        self._store = store
        self._clock = clock
        self._max_lookups = max_lookups_per_message

    async def _lookup(self, name: str) -> Optional[dict[str, Any]]:
        stations = await self._ekispert.find_stations(name)
        return pick_station(name, stations)

    async def resolve(self, name: str, budget: Optional[list[int]] = None) -> Optional[dict[str, Any]]:
        """The station `name` refers to, or None. `budget` is a one-item list counting uncached lookups left."""
        cached = await self._store.get("cache_station", _doc_id(name))
        if cached is not None:
            return cached.get("station")
        if budget is not None:
            if budget[0] <= 0:
                return None
            budget[0] -= 1
        try:
            station = await self._lookup(name)
            if station is None:
                for variant in spelling_variants(name)[:1]:
                    station = await self._lookup(variant)
                    if station:
                        break
        except Exception as e:  # don't cache "not a station" when Ekispert itself failed
            log.warning("station lookup failed for %r: %s", name, e)
            return None
        await self._store.set("cache_station", _doc_id(name),
                              {"station": station, "expire_at": self._clock() + CACHE_SECONDS})
        if station:
            await self._store.set("cache_station_code", station["code"],
                                  {"station": station, "expire_at": self._clock() + CACHE_SECONDS})
        return station

    async def from_text(self, text: str) -> Optional[dict[str, Any]]:
        budget = [self._max_lookups]
        for candidate in station_candidates(text):
            station = await self.resolve(candidate, budget)
            if station:
                return station
        return None

    async def by_code(self, code: str) -> Optional[dict[str, Any]]:
        cached = await self._store.get("cache_station_code", code)
        if cached is not None:
            return cached.get("station")
        station = await self._ekispert.station_by_code(code)
        if station:
            await self._store.set("cache_station_code", code,
                                  {"station": station, "expire_at": self._clock() + CACHE_SECONDS})
        return station
