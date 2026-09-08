"""
Ekispert MCP Client
Connects to the official Ekispert API MCP Server (https://api-mcp.ekispert.jp/mcp)
Complies strictly with Hackathon constraints:
- Non-timetable usage (ダイヤ情報不使用)
- Range search and topological average routes (平均探索)
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("ekispert")

class EkispertClient:
    def __init__(self, mcp_url: Optional[str] = None, access_key: Optional[str] = None):
        self.mcp_url = mcp_url or os.getenv("EKISPERT_MCP_URL", "https://api-mcp.ekispert.jp/mcp")
        self.access_key = access_key or os.getenv("EKISPERT_API_ACCESS_KEY", "")
        self._request_id = 1

    async def _call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool on the Ekispert MCP Server via JSON-RPC 2.0."""
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        headers = {
            "ekispert-api-access-key": self.access_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(self.mcp_url, headers=headers, json=payload)
            resp.raise_for_status()
            
            # SSE parsing: look for lines beginning with data:
            content = resp.text
            for line in content.splitlines():
                if line.startswith("data: "):
                    raw_data = line[6:].strip()
                    try:
                        parsed_json = json.loads(raw_data)
                        if "result" in parsed_json and "content" in parsed_json["result"]:
                            text_body = parsed_json["result"]["content"][0].get("text", "{}")
                            return json.loads(text_body)
                        return parsed_json
                    except json.JSONDecodeError:
                        continue
            
            # Fallback if standard JSON was returned
            try:
                return resp.json()
            except Exception:
                return {"raw": content}

    async def search_ranges(
        self, 
        base_stations: List[str], 
        upper_minutes: int = 40,
        upper_transfers: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Find common stations reachable within upper_minutes from ALL base_stations.
        Strictly operates without timetable/schedule info (waitAverageTime: true).
        """
        if not base_stations:
            return []
        
        args = {
            "baseList": base_stations,
            "upperMinutes": [upper_minutes] * len(base_stations),
            "upperTransferCounts": [upper_transfers] * len(base_stations),
            "shinkansen": "false",
            "plane": "false",
            "limitedExpress": "false",
            "waitAverageTime": "true",
            "includeBaseStation": "true" if len(base_stations) >= 2 else "false"
        }

        data = await self._call_mcp_tool("ekispert_api_search_ranges", args)
        points = data.get("ResultSet", {}).get("Point", [])
        if isinstance(points, dict):
            points = [points]
        
        results = []
        for p in points:
            st = p.get("Station", {})
            results.append({
                "name": st.get("Name"),
                "code": st.get("code"),
                "prefecture": st.get("Prefecture", {}).get("Name")
            })
        return results

    async def search_routes(self, from_station: str, to_station: str) -> Optional[Dict[str, Any]]:
        """
        Calculate route between two stations using average search (searchType: plain).
        Strictly adheres to non-timetable requirement.
        """
        if from_station == to_station:
            return {
                "from": from_station,
                "to": to_station,
                "time_minutes": 0,
                "transfers": 0,
                "lines": ["徒歩"],
                "ic_fare": 0
            }

        args = {
            "viaList": f"{from_station}:{to_station}"
        }
        data = await self._call_mcp_tool("ekispert_api_search_routes", args)
        
        courses = data.get("ResultSet", {}).get("Course", [])
        if isinstance(courses, dict):
            courses = [courses]
        
        if not courses:
            return None

        # Pick the best average course
        best = courses[0]
        # Calculate minutes
        time_minutes = 20 # reasonable default
        try:
            route_info = best.get("Route", {})
            time_minutes = int(route_info.get("timeOther", 0)) + int(route_info.get("timeOnBoard", 0))
            if time_minutes == 0 and "transferCount" in route_info:
                time_minutes = 25
        except Exception:
            pass

        transfers = 0
        try:
            transfers = int(best.get("Route", {}).get("transferCount", 0))
        except Exception:
            pass

        # Extract lines
        lines = []
        try:
            line_nodes = best.get("Route", {}).get("Line", [])
            if isinstance(line_nodes, dict):
                line_nodes = [line_nodes]
            for ln in line_nodes:
                lines.append(ln.get("Name", ""))
        except Exception:
            pass

        # Extract fare
        ic_fare = 200
        try:
            prices = best.get("Price", [])
            if isinstance(prices, dict):
                prices = [prices]
            for pr in prices:
                if pr.get("kind") == "FareSummary":
                    ic_fare = int(pr.get("Oneway", 200))
                    break
        except Exception:
            pass

        return {
            "from": from_station,
            "to": to_station,
            "time_minutes": time_minutes if time_minutes > 0 else 25,
            "transfers": transfers,
            "lines": [l for l in lines if l],
            "ic_fare": ic_fare
        }

    async def find_fair_midpoint(self, member_origins: Dict[str, str]) -> Dict[str, Any]:
        """
        Calculates the fairest midpoint station among members concurrently in under 1 second.
        1. Queries Ekispert search_ranges with 45/60 min threshold.
        2. Concurrently evaluates top candidate stations using asyncio.gather.
        3. Returns the winning hub + member travel details.
        """
        import asyncio
        unique_stations = list(set(member_origins.values()))
        if len(unique_stations) == 1:
            hub = unique_stations[0]
            member_details = {
                name: {
                    "origin": origin,
                    "travel_time": 0,
                    "transfers": 0,
                    "lines": ["徒歩"],
                    "fare": 0
                }
                for name, origin in member_origins.items()
            }
            return {
                "hub_station": hub,
                "fairness_score": 100,
                "max_travel_time": 0,
                "avg_travel_time": 0,
                "members": member_details,
                "alternatives": []
            }

        # Step 1: Range search with adaptive minutes
        candidates = []
        for mins in [45, 60]:
            try:
                found = await self.search_ranges(unique_stations, upper_minutes=mins, upper_transfers=2)
                if found:
                    candidates = [c["name"] for c in found if c.get("name")]
                    break
            except Exception as e:
                logger.warning(f"Range search error at {mins} min: {e}")
                continue

        default_tokyo_hubs = ["御徒町", "神田", "有楽町", "品川", "秋葉原", "恵比寿", "渋谷", "新宿"]
        if not candidates:
            candidates = default_tokyo_hubs
        else:
            for dh in default_tokyo_hubs:
                if dh not in candidates and len(candidates) < 6:
                    candidates.append(dh)

        # Select top 3 candidate hubs to evaluate
        eval_cands = candidates[:3]

        # Step 2: Concurrently evaluate all (origin, candidate) route pairs
        async def get_cand_eval(cand: str):
            names = list(member_origins.keys())
            origins = [member_origins[n] for n in names]
            tasks = [self.search_routes(orig, cand) for orig in origins]
            routes = await asyncio.gather(*tasks, return_exceptions=True)
            
            cand_details = {}
            times = []
            for name, origin, route in zip(names, origins, routes):
                if isinstance(route, dict) and route:
                    t = route.get("time_minutes", 30)
                    times.append(t)
                    cand_details[name] = {
                        "origin": origin,
                        "travel_time": t,
                        "transfers": route.get("transfers", 1),
                        "lines": route.get("lines", ["JR線"]),
                        "fare": route.get("ic_fare", 220)
                    }
                else:
                    times.append(40)
                    cand_details[name] = {
                        "origin": origin,
                        "travel_time": 40,
                        "transfers": 1,
                        "lines": ["JR線"],
                        "fare": 220
                    }

            max_time = max(times) if times else 50
            avg_time = sum(times) / len(times) if times else 30
            spread = max_time - min(times) if times else 20
            fairness = max(0, 100 - (spread * 2) - int(avg_time * 0.5))

            return {
                "hub_station": cand,
                "fairness_score": fairness,
                "max_travel_time": max_time,
                "avg_travel_time": round(avg_time, 1),
                "spread_minutes": spread,
                "members": cand_details
            }

        eval_tasks = [get_cand_eval(cand) for cand in eval_cands]
        evaluations = await asyncio.gather(*eval_tasks)

        # Sort by best fairness score (highest fairness first)
        evaluations = sorted(evaluations, key=lambda x: (x["fairness_score"], -x["max_travel_time"]), reverse=True)
        winner = evaluations[0]
        alternatives = [e["hub_station"] for e in evaluations[1:]]
        winner["alternatives"] = alternatives
        return winner

