"""
Agent 4: Autonomous Voice & Web Reservation Agent
Handles venue booking by executing an autonomous Japanese phone call
dialogue between the AI agent and the venue staff.
Generates structured dialogue turns and speech scripts for demo playback.
"""

import uuid
from typing import Dict, Any, List
from services.llm_client import LLMClient

class VoiceAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def execute_phone_reservation(
        self,
        venue: Dict[str, Any],
        date_time: str,
        pax: int,
        organizer: str = "佐藤"
    ) -> Dict[str, Any]:
        """
        Executes autonomous phone reservation simulation with full conversational dialogue.
        """
        venue_name = venue.get("name", "予約店舗")
        phone = venue.get("phone", "03-5792-XXXX")
        booking_id = f"ASOBI-{uuid.uuid4().hex[:6].upper()}"

        dialogue = [
            {
                "speaker": "AIエージェント (AsobiAgent)",
                "role": "ai",
                "text": f"お忙しいところ恐れ入ります。AI自動予約コンシェルジュのAsobiAgentと申します。{date_time}に{pax}名でお席の予約をお願いしたくご連絡いたしました。空きはございますでしょうか？",
                "audio_label": "架電・要件伝達"
            },
            {
                "speaker": "店舗スタッフ",
                "role": "staff",
                "text": f"お電話ありがとうございます！{venue_name}でございます。{date_time}、{pax}名様ですね。少々お待ちください……はい、テーブル席でご案内可能です！",
                "audio_label": "店舗空席確認"
            },
            {
                "speaker": "AIエージェント (AsobiAgent)",
                "role": "ai",
                "text": f"ありがとうございます！代表者名は「{organizer}（サトウ）」様、禁煙のテーブル席を希望いたします。",
                "audio_label": "代表者・席指定"
            },
            {
                "speaker": "店舗スタッフ",
                "role": "staff",
                "text": f"かしこまりました。{organizer}様、禁煙テーブル席で承りました。ご連絡先番号はお控えの番号でよろしいでしょうか？",
                "audio_label": "店舗受付確認"
            },
            {
                "speaker": "AIエージェント (AsobiAgent)",
                "role": "ai",
                "text": "はい、そちらの番号でお願いいたします。アレルギー等の特別な要望はございません。",
                "audio_label": "情報確定"
            },
            {
                "speaker": "店舗スタッフ",
                "role": "staff",
                "text": f"承知いたしました。それでは{date_time}、{pax}名様、{organizer}様でご予約完了とさせていただきます。ご来店お待ちしております！",
                "audio_label": "予約成立"
            },
            {
                "speaker": "AIエージェント (AsobiAgent)",
                "role": "ai",
                "text": "丁寧なご対応、誠にありがとうございました。当日伺わせていただきます。失礼いたします。",
                "audio_label": "通話終了"
            }
        ]

        return {
            "status": "confirmed",
            "booking_id": booking_id,
            "venue_name": venue_name,
            "phone_called": phone,
            "date_time": date_time,
            "pax": pax,
            "organizer": organizer,
            "dialogue": dialogue,
            "summary": f"店舗「{venue_name}」への自律AI架電が完了し、{date_time}（{pax}名様・代表{organizer}様）で予約が確定しました。"
        }
