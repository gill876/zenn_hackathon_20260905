"""
駅すぱあと (Ekispert) MCP client.

Uses only timetable-free tools (ダイヤ情報不使用):
- ekispert_api_get_stations: check that a name is a real station and get its coordinates
- ekispert_api_search_ranges: stations everyone can reach, with each person's average travel time
- ekispert_api_search_routes with searchType "plain": average route time between two stations
"""

import json
import logging
from typing import Any, Optional

import httpx

log = logging.getLogger("ekispert")

KANTO_PREFS = {"8", "9", "10", "11", "12", "13", "14"}


class EkispertError(RuntimeError):
    pass


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


class EkispertClient:
    def __init__(self, access_key: str, mcp_url: str, usage=None, timeout: float = 20.0):
        self.access_key = access_key
        self.mcp_url = mcp_url
        self._usage = usage
        self._timeout = timeout
        self._request_id = 0

    async def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.access_key:
            raise EkispertError("EKISPERT_API_ACCESS_KEY is not set")
        self._request_id += 1
        payload = {"jsonrpc": "2.0", "id": self._request_id, "method": "tools/call",
                   "params": {"name": tool, "arguments": arguments}}
        headers = {"ekispert-api-access-key": self.access_key, "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self._usage:
            await self._usage.note("ekispert")
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self.mcp_url, headers=headers, json=payload)
        resp.raise_for_status()
        body = resp.text
        for line in body.splitlines():
            if line.startswith("data: "):
                body = line[6:]
                break
        message = json.loads(body)
        if "error" in message:
            raise EkispertError(str(message["error"])[:300])
        result = message.get("result", {})
        text = (result.get("content") or [{}])[0].get("text", "{}")
        if result.get("isError"):
            raise EkispertError(text[:300])
        return json.loads(text)

    async def find_stations(self, name: str) -> list[dict[str, Any]]:
        """Train stations whose name matches `name` (partial match on Ekispert's side)."""
        data = await self._call("ekispert_api_get_stations",
                                {"name": name, "type": "train", "simplify": "false", "gcs": "wgs84"})
        return [_point(p) for p in _as_list(data.get("ResultSet", {}).get("Point"))]

    async def station_by_code(self, code: str) -> Optional[dict[str, Any]]:
        data = await self._call("ekispert_api_get_stations", {"code": int(code), "simplify": "false", "gcs": "wgs84"})
        points = _as_list(data.get("ResultSet", {}).get("Point"))
        return _point(points[0]) if points else None

    async def search_ranges(self, base_names: list[str], upper_minutes: int,
                            upper_transfers: int = 2) -> list[dict[str, Any]]:
        """Stations reachable by everyone within `upper_minutes`, with each base's average minutes."""
        n = len(base_names)
        data = await self._call("ekispert_api_search_ranges", {
            "baseList": base_names,
            "upperMinutes": [upper_minutes] * n,
            "upperTransferCounts": [upper_transfers] * n,
            "shinkansen": "false",
            "plane": "false",
            "limitedExpress": "false",
            "waitAverageTime": "true",
            "includeBaseStation": "true",
            "limit": 60,
        })
        out = []
        for p in _as_list(data.get("ResultSet", {}).get("Point")):
            st = p.get("Station", {})
            costs = sorted(_as_list(p.get("Cost")), key=lambda c: int(c.get("baseIndex", 0)))
            if len(costs) != n:
                continue
            out.append({
                "name": st.get("Name"),
                "code": st.get("code"),
                "prefecture": p.get("Prefecture", {}).get("Name"),
                "minutes": [int(c.get("Minute", 0)) for c in costs],
                "transfers": [int(c.get("TransferCount", 0)) for c in costs],
            })
        return out

    async def average_route(self, from_name: str, to_name: str) -> Optional[dict[str, Any]]:
        """Average (timetable-free) route between two stations."""
        data = await self._call("ekispert_api_search_routes",
                                {"viaList": f"{from_name}:{to_name}", "searchType": "plain"})
        courses = _as_list(data.get("ResultSet", {}).get("Course"))
        if not courses:
            return None
        route = courses[0].get("Route", {})
        minutes = int(route.get("timeOnBoard", 0)) + int(route.get("timeOther", 0)) + int(route.get("timeWalk", 0))
        return {
            "minutes": minutes,
            "transfers": int(route.get("transferCount", 0)),
            "lines": [ln.get("Name", "") for ln in _as_list(route.get("Line")) if ln.get("Name")],
        }


def _point(p: dict[str, Any]) -> dict[str, Any]:
    st = p.get("Station", {})
    geo = p.get("GeoPoint", {})
    pref = p.get("Prefecture", {})
    return {
        "name": st.get("Name"),
        "code": st.get("code"),
        "yomi": st.get("Yomi"),
        "pref_code": pref.get("code"),
        "pref": pref.get("Name"),
        "lat": float(geo["lati_d"]) if geo.get("lati_d") else None,
        "lng": float(geo["longi_d"]) if geo.get("longi_d") else None,
    }


def pick_station(name: str, candidates: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Choose the station a person most likely meant by `name`: an exact match, else a disambiguated
    one like 府中(東京都); Kanto first in both cases. Partial matches (横浜 → 横浜駅前) are rejected."""
    exact = [c for c in candidates if c.get("name") == name]
    named = [c for c in candidates if (c.get("name") or "").startswith(name + "(")]
    for group in (exact, named):
        if group:
            kanto = [c for c in group if c.get("pref_code") in KANTO_PREFS]
            return (kanto or group)[0]
    return None
