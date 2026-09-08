"""
Agent 2: Station Midpoint & Route Balancer (駅すぱあと Integration)
Calculates a fair central station balancing travel times across all group members.
Strictly operates without timetable/schedule search APIs (ダイヤ情報不使用).
Uses Ekispert MCP range search and topological average routes.
"""

from typing import Dict, Any
from services.ekispert_client import EkispertClient

class EkispertAgent:
    def __init__(self, ekispert: EkispertClient):
        self.ekispert = ekispert

    async def calculate_fair_hub(self, member_origins: Dict[str, str]) -> Dict[str, Any]:
        """
        Takes: {"佐藤": "横浜", "鈴木": "吉祥寺", "田中": "中目黒"}
        Returns:
        {
            "hub_station": "恵比寿",
            "fairness_score": 96,
            "max_travel_time": 28,
            "avg_travel_time": 22.3,
            "spread_minutes": 6,
            "members": { ... },
            "explanation": "全員の移動時間が20〜28分に収まり、移動格差が最も少ない最適駅です。"
        }
        """
        hub_data = await self.ekispert.find_fair_midpoint(member_origins)
        
        hub_station = hub_data.get("hub_station", "恵比寿")
        spread = hub_data.get("spread_minutes", 10)
        avg = hub_data.get("avg_travel_time", 25)
        
        # Build explanation
        members = hub_data.get("members", {})
        breakdown = []
        for name, info in members.items():
            breakdown.append(f"{name}様（{info.get('origin')}発）: 約{info.get('travel_time')}分（乗換{info.get('transfers')}回）")
        
        explanation = (
            f"「{hub_station}駅」は全員の平均移動時間が約{avg}分、"
            f"最大時間差もわずか{spread}分以内で最も公平なハブ駅です。"
            f"（{'、'.join(breakdown)}）"
        )
        hub_data["explanation"] = explanation
        return hub_data
