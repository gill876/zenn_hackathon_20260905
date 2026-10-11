"""
Agent 4 (phone): a call script the organizer reads out themselves.

The bot never places calls. It prepares what to say, and the organizer taps to dial from their own
phone. Built from a template, so it costs no model call.
"""

from typing import Optional


MEALS = {"lunch": "ランチ", "dinner": "夜", "cafe": "お茶の時間", "drinks": "夜"}


def _when(day: Optional[str], time: Optional[str], meal: Optional[str]) -> str:
    slot = f"{time}から" if time else (f"{MEALS[meal]}に" if meal in MEALS else "")
    if day and slot:
        return f"{day}の{slot}"
    if day:
        return f"{day}に"
    return slot or "（日にちと時間）に"


def call_script(venue_name: str, day: Optional[str], time: Optional[str], pax: int, organizer: str,
                meal: Optional[str] = None) -> dict:
    lines = [f"「{_when(day, time, meal)}、{pax}名で予約をお願いしたいのですが、空いていますか？」"]
    if not time:
        lines.append("「何時から空いていますか？」")
    lines.append(f"「名前は{organizer}です。連絡先はこの番号でお願いします。」")
    return {"venue": venue_name, "lines": lines,
            "if_full": "「満席でしたら、前後の時間で空いている枠はありますか？」"}
