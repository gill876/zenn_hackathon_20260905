"""
AsobiAgent Orchestrator
Central multi-agent coordinator that manages the 4-agent pipeline:
Schedule Sync -> Ekispert Hub Calculation -> Crowd Spot Discovery -> Autonomous Voice Booking
"""

import logging
from typing import Dict, Any, List, Optional
from services.ekispert_client import EkispertClient
from services.llm_client import LLMClient
from services import line_flex

from agents.schedule_agent import ScheduleAgent
from agents.ekispert_agent import EkispertAgent
from agents.spot_agent import SpotAgent
from agents.voice_agent import VoiceAgent

logger = logging.getLogger("orchestrator")

class AsobiOrchestrator:
    def __init__(self):
        self.ekispert_client = EkispertClient()
        self.llm_client = LLMClient()
        
        self.schedule_agent = ScheduleAgent(self.llm_client)
        self.ekispert_agent = EkispertAgent(self.ekispert_client)
        self.spot_agent = SpotAgent(self.llm_client)
        self.voice_agent = VoiceAgent(self.llm_client)

        self.reset_session()

    def reset_session(self):
        """Reset conversation and agent state."""
        self.chat_history: List[Dict[str, Any]] = []
        self.schedule_data: Dict[str, Any] = {}
        self.midpoint_data: Optional[Dict[str, Any]] = None
        self.venues: List[Dict[str, Any]] = []
        self.reservation: Optional[Dict[str, Any]] = None
        self.agent_logs: List[Dict[str, Any]] = []

    def log_agent_action(self, agent_id: str, agent_name: str, step: str, details: Any):
        """Record real-time execution log for judges and inspection UI."""
        self.agent_logs.append({
            "agent_id": agent_id,
            "agent_name": agent_name,
            "step": step,
            "details": details
        })

    async def process_chat_message(self, sender: str, text: str) -> Dict[str, Any]:
        """
        Processes an incoming user message in the LINE chat.
        Step 1: Agent 1 parses conversation intent.
        Step 2: If 2+ origins are detected, Agent 2 calculates Ekispert midpoint.
        Step 3: Agent 3 finds crowd-avoidance spots.
        Returns generated bot responses and LINE Flex cards.
        """
        self.chat_history.append({"sender": sender, "text": text})

        # Step 1: Schedule Agent
        self.log_agent_action("agent_1", "Schedule Synchronizer", "自然言語から希望・出発駅を解析中", {"sender": sender, "text": text})
        extracted = await self.schedule_agent.extract_intent_and_schedule(self.chat_history)
        self.schedule_data.update(extracted)
        self.log_agent_action("agent_1", "Schedule Synchronizer", "抽出完了", extracted)

        bot_messages = []
        
        origins = self.schedule_data.get("origins", {})
        members = self.schedule_data.get("members", [])
        date_time = self.schedule_data.get("date_time", "今週末")
        pref = self.schedule_data.get("preferences", "落ち着いた場所")

        # Create schedule summary flex
        sched_flex = line_flex.create_schedule_summary_flex(members, origins, date_time, pref)
        bot_messages.append({
            "type": "flex",
            "flex": sched_flex,
            "sender": "AsobiAgent",
            "text": "グループの希望と出発駅を把握しました！"
        })

        # Step 2: If we have at least 2 member origins, trigger Agent 2 (Ekispert Hub Balancer)
        if len(origins) >= 2:
            self.log_agent_action("agent_2", "Ekispert Hub Balancer", "駅すぱあとMCPで公平な中間駅を探索中", {"origins": origins})
            midpoint = await self.ekispert_agent.calculate_fair_hub(origins)
            self.midpoint_data = midpoint
            self.log_agent_action("agent_2", "Ekispert Hub Balancer", "最適中間駅の算出完了", midpoint)

            midpoint_flex = line_flex.create_midpoint_flex(midpoint)
            bot_messages.append({
                "type": "flex",
                "flex": midpoint_flex,
                "sender": "AsobiAgent",
                "text": f"全員の移動時間差が最小になる公平な集合駅は「{midpoint.get('hub_station')}駅」です！"
            })

            # Step 3: Trigger Agent 3 (Crowd Avoidance Spot Finder)
            hub_station = midpoint.get("hub_station", "恵比寿")
            pax = self.schedule_data.get("pax", len(members))
            self.log_agent_action("agent_3", "Crowd & Spot Discovery", f"{hub_station}駅周辺の混雑回避スポットを検索中", {"station": hub_station, "preferences": pref})
            venues = await self.spot_agent.find_crowd_avoidance_spots(hub_station, pref, pax, date_time)
            self.venues = venues
            self.log_agent_action("agent_3", "Crowd & Spot Discovery", "穴場スポット3選の選定完了", {"count": len(venues), "venues": venues})

            venues_flex = line_flex.create_venues_carousel_flex(hub_station, venues)
            bot_messages.append({
                "type": "flex",
                "flex": venues_flex,
                "sender": "AsobiAgent",
                "text": f"「{hub_station}駅」近くで混雑を避けられる穴場スポットを厳選しました！"
            })

        return {
            "status": "success",
            "bot_messages": bot_messages,
            "session_state": self.get_current_state()
        }

    async def process_scenario_fast(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Processes a full multi-turn conversation scenario in one optimized pass
        (Agent 1 once -> Agent 2 once -> Agent 3 once) instead of redundant loops.
        Runs in 2-3 seconds!
        """
        for m in messages:
            self.chat_history.append({"sender": m["sender"], "text": m["text"]})

        # Agent 1: Parse all messages
        self.log_agent_action("agent_1", "Schedule Synchronizer", "グループ会話から参加者・希望・出発駅を一括解析中", {"message_count": len(messages)})
        extracted = await self.schedule_agent.extract_intent_and_schedule(self.chat_history)
        self.schedule_data.update(extracted)
        self.log_agent_action("agent_1", "Schedule Synchronizer", "希望・出発駅の抽出完了", extracted)

        bot_messages = []
        origins = self.schedule_data.get("origins", {})
        members = self.schedule_data.get("members", [])
        date_time = self.schedule_data.get("date_time", "今週末")
        pref = self.schedule_data.get("preferences", "落ち着いた場所")

        # 1. Schedule Summary Flex
        sched_flex = line_flex.create_schedule_summary_flex(members, origins, date_time, pref)
        bot_messages.append({
            "type": "flex",
            "flex": sched_flex,
            "sender": "AsobiAgent",
            "text": "グループの希望と出発駅を把握しました！"
        })

        # 2. Agent 2: Ekispert Hub Balancer
        if len(origins) >= 2:
            self.log_agent_action("agent_2", "Ekispert Hub Balancer", "駅すぱあとMCPで公平な中間駅を探索中", {"origins": origins})
            midpoint = await self.ekispert_agent.calculate_fair_hub(origins)
            self.midpoint_data = midpoint
            self.log_agent_action("agent_2", "Ekispert Hub Balancer", "最適中間駅の算出完了", midpoint)

            midpoint_flex = line_flex.create_midpoint_flex(midpoint)
            bot_messages.append({
                "type": "flex",
                "flex": midpoint_flex,
                "sender": "AsobiAgent",
                "text": f"全員の移動時間差が最小になる公平な集合駅は「{midpoint.get('hub_station')}駅」です！"
            })

            # 3. Agent 3: Crowd Avoidance Spot Finder
            hub_station = midpoint.get("hub_station", "恵比寿")
            pax = self.schedule_data.get("pax", len(members))
            self.log_agent_action("agent_3", "Crowd & Spot Discovery", f"{hub_station}駅周辺の混雑回避スポットを検索中", {"station": hub_station, "preferences": pref})
            venues = await self.spot_agent.find_crowd_avoidance_spots(hub_station, pref, pax, date_time)
            self.venues = venues
            self.log_agent_action("agent_3", "Crowd & Spot Discovery", "穴場スポット3選の選定完了", {"count": len(venues), "venues": venues})

            venues_flex = line_flex.create_venues_carousel_flex(hub_station, venues)
            bot_messages.append({
                "type": "flex",
                "flex": venues_flex,
                "sender": "AsobiAgent",
                "text": f"「{hub_station}駅」近くで混雑を避けられる穴場スポットを厳選しました！"
            })

        return {
            "status": "success",
            "bot_messages": bot_messages,
            "session_state": self.get_current_state()
        }


    async def execute_reservation(self, venue_id: str, organizer: str = "佐藤") -> Dict[str, Any]:
        """
        Triggers Agent 4: Autonomous Voice Booking.
        Places autonomous phone call simulation to the restaurant.
        """
        # Find venue
        selected_venue = None
        for v in self.venues:
            if v.get("id") == venue_id or v.get("name") == venue_id:
                selected_venue = v
                break
        if not selected_venue:
            selected_venue = self.venues[0] if self.venues else {
                "name": "恵比寿 隠れ家ビストロ CANTE",
                "phone": "03-5792-4810"
            }

        date_time = self.schedule_data.get("date_time", "来週土曜日 13:00")
        pax = self.schedule_data.get("pax", len(self.schedule_data.get("members", [1, 2, 3])))

        self.log_agent_action("agent_4", "Autonomous Voice Agent", f"店舗「{selected_venue.get('name')}」へ自律架電中...", {"venue": selected_venue, "pax": pax})
        res = await self.voice_agent.execute_phone_reservation(selected_venue, date_time, pax, organizer)
        self.reservation = res
        self.log_agent_action("agent_4", "Autonomous Voice Agent", "予約確定・通話終了", res)

        ticket_flex = line_flex.create_reservation_ticket_flex(
            venue_name=res["venue_name"],
            date_time=res["date_time"],
            pax=res["pax"],
            organizer=res["organizer"],
            booking_id=res["booking_id"]
        )

        bot_message = {
            "type": "flex",
            "flex": ticket_flex,
            "sender": "AsobiAgent",
            "text": f"🎉 {res['venue_name']}への電話予約が完了しました！"
        }

        return {
            "status": "success",
            "reservation": res,
            "bot_message": bot_message,
            "session_state": self.get_current_state()
        }

    def get_current_state(self) -> Dict[str, Any]:
        """Returns full session state for the frontend UI."""
        return {
            "chat_history": self.chat_history,
            "schedule_data": self.schedule_data,
            "midpoint_data": self.midpoint_data,
            "venues": self.venues,
            "reservation": self.reservation,
            "agent_logs": self.agent_logs
        }
