"""
Agent 1: reads the messages held during 募集 and works out when, how many, and what kind of place.

One LLM call per search. Names never reach the model: participants appear as 参加者1, 参加者2, …
If the model is unavailable, a keyword table and the rule-based date hint fill in instead.
"""

from typing import Any, Optional

from bot.text_parse import _normalize_day
from services.hotpepper_client import BUDGETS, GENRES
from services.llm_client import LLMClient

# Rule-based fallback: words people use → HotPepper genre code or search keyword.
KEYWORD_GENRES = [
    ("焼肉", "G008"), ("ホルモン", "G008"), ("カフェ", "G014"), ("お茶", "G014"), ("スイーツ", "G014"),
    ("ラーメン", "G013"), ("イタリアン", "G006"), ("フレンチ", "G006"), ("パスタ", "G006"),
    ("中華", "G007"), ("韓国", "G017"), ("居酒屋", "G001"), ("バル", "G002"), ("和食", "G004"),
    ("寿司", "G004"), ("エスニック", "G009"), ("タイ料理", "G009"), ("お好み焼き", "G016"), ("もんじゃ", "G016"),
]
KEYWORDS = ["肉", "クラフトビール", "ビール", "ワイン", "日本酒", "海鮮", "鍋"]
QUIET_WORDS = ["混", "静か", "落ち着", "ゆっくり", "穴場"]

SYSTEM = "You extract outing plans from Japanese group chats. Answer in Japanese inside a JSON object."


def rule_based_details(messages: list[str], hint: Optional[dict[str, str]]) -> dict[str, Any]:
    text = "\n".join(messages)
    genre = next((code for word, code in KEYWORD_GENRES if word in text), None)
    keyword = next((w for w in KEYWORDS if w in text), None) if genre is None else None
    prefs = []
    if genre:
        prefs.append(GENRES[genre])
    if keyword:
        prefs.append(keyword)
    quiet = any(w in text for w in QUIET_WORDS)
    if quiet:
        prefs.append("混雑を避けたい")
    hint = hint or {}
    return {
        "day": hint.get("day"), "time": hint.get("time"), "meal": hint.get("meal"),
        "preferences": prefs, "genre": genre, "budget": None, "keyword": keyword,
        "private_room": False, "quiet": quiet, "source": "rules",
    }


def _clean(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    out = dict(fallback)
    for key in ("day", "time", "meal", "keyword"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip() and value.strip().lower() not in {"null", "none", "不明"}:
            out[key] = value.strip()[:20]
    if out.get("day") and out["day"] != fallback.get("day"):
        out["day"] = _normalize_day(out["day"])          # 来週土曜日 → 来週土曜, so dates resolve
    if out.get("meal") not in {None, "lunch", "dinner", "cafe", "drinks"}:
        out["meal"] = fallback.get("meal")
    if raw.get("genre") in GENRES:
        out["genre"] = raw["genre"]
    if raw.get("budget") in BUDGETS:
        out["budget"] = raw["budget"]
    if isinstance(raw.get("preferences"), list):
        out["preferences"] = [str(p)[:20] for p in raw["preferences"] if str(p).strip()][:5]
    for key in ("private_room", "quiet"):
        if isinstance(raw.get(key), bool):
            out[key] = raw[key]
    out["source"] = "llm"
    return out


async def extract_details(llm: LLMClient, messages_by_person: list[tuple[int, str]],
                          hint: Optional[dict[str, str]]) -> dict[str, Any]:
    texts = [t for _, t in messages_by_person]
    fallback = rule_based_details(texts, hint)
    if not llm.available or not messages_by_person:
        return fallback
    chat = "\n".join(f"参加者{n}: {t}" for n, t in messages_by_person)
    genres = ", ".join(f"{k}={v}" for k, v in GENRES.items())
    budgets = ", ".join(f"{k}={v}" for k, v in BUDGETS.items())
    prompt = f"""Friends are planning to meet. Read their messages and fill this JSON:
{{
  "day": "day they agreed on, as written (e.g. 来週土曜, 10/18) or null",
  "time": "HH:MM or null",
  "meal": "lunch | dinner | cafe | drinks | null",
  "preferences": ["short Japanese phrases for food/atmosphere wishes, max 5"],
  "genre": "one HotPepper genre code that fits best, or null",
  "budget": "one HotPepper budget code per person, or null if nobody mentioned money",
  "keyword": "one short search word for a specific wish (e.g. 肉, クラフトビール) or null",
  "private_room": true/false (someone asked for a private room),
  "quiet": true/false (someone wants to avoid crowds or noise)
}}
Genre codes: {genres}
Budget codes: {budgets}
A rule-based reading found: {fallback.get('day')} {fallback.get('time')} (may be incomplete).

Messages:
{chat}"""
    raw = await llm.generate_json(prompt, SYSTEM, max_tokens=500)
    return _clean(raw, fallback) if raw else fallback


async def refine_details(llm: LLMClient, details: dict[str, Any], request: str) -> dict[str, Any]:
    """Apply a free-text change like 「和食がいい」 or 「もっと安く」 to the search details."""
    fallback = dict(details)
    rules = rule_based_details([request], None)
    if rules["genre"]:
        fallback["genre"], fallback["keyword"] = rules["genre"], None
    elif rules["keyword"]:
        fallback["keyword"] = rules["keyword"]
    if "個室" in request:
        fallback["private_room"] = True
    if not llm.available:
        return fallback
    genres = ", ".join(f"{k}={v}" for k, v in GENRES.items())
    budgets = ", ".join(f"{k}={v}" for k, v in BUDGETS.items())
    prompt = f"""Current restaurant search (JSON): {details}
The group now says: 「{request}」
Return the updated search as the same JSON keys (day, time, meal, preferences, genre, budget, keyword,
private_room, quiet). Change only what the request asks for.
Genre codes: {genres}
Budget codes: {budgets}"""
    raw = await llm.generate_json(prompt, SYSTEM, max_tokens=400)
    return _clean(raw, fallback) if raw else fallback


def details_text(details: dict[str, Any]) -> str:
    parts = []
    when = " ".join(p for p in (details.get("day"), details.get("time")) if p)
    if when:
        parts.append(when)
    if details.get("preferences"):
        parts.append("・".join(details["preferences"][:3]))
    return " / ".join(parts)
