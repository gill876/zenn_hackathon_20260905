"""
How much does the Time Out index add around common meeting stations?

For each station: Time Out places within 1 km, HotPepper's top 30 within 1 km, and how many of those
HotPepper shops Time Out has also covered (the "Time Out で紹介" badge). HotPepper calls are free;
station coordinates come from Ekispert.

    python -m jobs.timeout_report
"""

import asyncio
import collections

from dotenv import dotenv_values

from services.ekispert_client import EkispertClient, pick_station
from services.hotpepper_client import HotPepperClient
from services.timeout_index import TimeOutIndex

STATIONS = ["渋谷", "新宿", "池袋", "東京", "銀座", "有楽町", "神田", "秋葉原", "上野", "浅草", "恵比寿",
            "中目黒", "下北沢", "高円寺", "吉祥寺", "三軒茶屋", "表参道", "六本木", "品川", "横浜", "梅田", "難波"]


async def main() -> None:
    env = dotenv_values(".env")
    index = TimeOutIndex.load()
    ekispert = EkispertClient(env["EKISPERT_API_ACCESS_KEY"], env.get("EKISPERT_MCP_URL") or "https://api-mcp.ekispert.jp/mcp")
    hotpepper = HotPepperClient(env["HOTPEPPER_API_KEY"])
    print(f"Time Out index: {index.size} places\n")
    print(f"{'station':<8} {'TO≤1km':>7} {'TO≤500m':>8} {'HP top30 matched':>17}")
    totals = collections.Counter()
    for name in STATIONS:
        station = pick_station(name, await ekispert.find_stations(name))
        if not station:
            print(f"{name:<8} (not found)")
            continue
        near = index.nearby(station["lat"], station["lng"], 1000)
        close = [p for d, p in near if d <= 500]
        shops = await hotpepper.search(station["lat"], station["lng"], range_code=3, count=30)
        matched = [s for s in shops if index.match(s)]
        totals.update(to=len(near), hp=len(shops), matched=len(matched))
        print(f"{name:<8} {len(near):>7} {len(close):>8} {len(matched):>9}/{len(shops)}")
    if totals["hp"]:
        print(f"\nbadge rate on HotPepper's top results: {totals['matched']}/{totals['hp']}"
              f" = {totals['matched'] / totals['hp']:.1%}")


if __name__ == "__main__":
    asyncio.run(main())
