"""
Agent 1: Natural Schedule & Intent Synchronizer
Listens to natural language LINE group chats, extracts member availability,
departure stations, and dining/activity preferences using GMI Qwen LLM.
"""

from typing import Dict, Any, List
from services.llm_client import LLMClient

class ScheduleAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def extract_intent_and_schedule(self, chat_messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Parses list of chat messages: [{"sender": "佐藤", "text": "来週土曜13時〜 横浜から行くよ"}]
        Returns structured info:
        {
            "members": ["佐藤", "鈴木", "田中"],
            "origins": {"佐藤": "横浜", "鈴木": "吉祥寺", "田中": "中目黒"},
            "date_time": "来週土曜日 13:00",
            "preferences": "お肉かエスニック、混雑しない場所",
            "pax": 3,
            "ready_for_midpoint": True
        }
        """
        chat_text = "\n".join([f"{m.get('sender')}: {m.get('text')}" for m in chat_messages])
        
        prompt = f"""
Analyze this Japanese LINE group chat where friends are trying to arrange a meetup.
Extract:
1. "members": list of names who are participating.
2. "origins": dictionary mapping member name -> their departure station (駅名 only, e.g. "横浜", "中目黒", "吉祥寺", "柏", "品川"). If unknown, leave empty or infer from context.
3. "date_time": agreed or suggested date & time in clean Japanese string (e.g. "来週土曜日 13:00").
4. "preferences": food, atmosphere, or budget preferences mentioned (e.g. "お肉・落ち着いた場所").
5. "pax": total number of participants (integer).
6. "ready_for_midpoint": boolean (true if at least 2 member departure stations are known).

Group Chat:
{chat_text}
"""
        system_prompt = "You are an expert NLP information extraction agent for Japanese conversations. Output strict JSON only."
        data = await self.llm.generate_json(prompt, system_prompt)
        
        # Guard rails and fallbacks
        if not data.get("members") and chat_messages:
            senders = list(set([m.get("sender", "参加者") for m in chat_messages]))
            data["members"] = senders
        if not data.get("origins"):
            data["origins"] = {}
        if not data.get("date_time"):
            data["date_time"] = "今週末 13:00"
        if not data.get("preferences"):
            data["preferences"] = "落ち着いて話せる穴場スポット"
        if not data.get("pax"):
            data["pax"] = len(data.get("members", [])) or 3
            
        data["ready_for_midpoint"] = len(data["origins"]) >= 2
        return data
