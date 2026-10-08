"""
Agent 4 (phone): a call script the organizer reads out themselves.

The bot never places calls. It prepares what to say, and the organizer taps to dial from their own
phone. Built from a template, so it costs no model call.
"""

from typing import Optional


def _when(day: Optional[str], time: Optional[str]) -> str:
    if day and time:
        return f"{day}の{time}から"
    if day:
        return day
    if time:
        return f"{time}から"
    return "（日時）"


def call_script(venue_name: str, day: Optional[str], time: Optional[str], pax: int, organizer: str) -> dict:
    return {
        "venue": venue_name,
        "lines": [
            f"「{_when(day, time)}、{pax}名で予約をお願いしたいのですが、空いていますか？」",
            f"「名前は{organizer}です。連絡先はこの番号でお願いします。」",
        ],
        "if_full": "「満席でしたら、前後の時間で空いている枠はありますか？」",
    }
