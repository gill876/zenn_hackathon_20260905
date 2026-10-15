"""
Web simulator API (the hackathon demo page at /).

Public mode replays the three preset group chats through the real pipeline, but without the LLM: stations
and dates are read by rules, the hub comes from Ekispert (cached for 30 days), and venues come from
HotPepper (cached for 24 hours). So a visitor costs no model credits, and a daily cap bounds the rest.
Free-text chat runs the full LLM pipeline and needs the admin token or the judges' shared code.
Like the LINE bot, the venues come six to a page ("別の候補を見る"), and a visitor can add a place by name
("💡 お店を提案する"), looked up near the meeting station.
"""

import hmac
import math
import re
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from agents import schedule_agent, spot_agent, voice_agent
from agents.ekispert_agent import find_hub
from bot.deps import Deps
from bot.text_parse import date_hint, hint_text, merge_hints
from services import line_flex
from services.ids import normalize_invite_code
from services.suggest import URL as URL_RE
from services.suggest import SuggestionError
from services.suggest import resolve as resolve_suggestion

router = APIRouter(prefix="/api")

SCENARIOS: dict[str, list[dict[str, str]]] = {
    "tokyo_meat_4": [
        {"sender": "佐藤", "text": "みんな来週土曜日の昼13時くらいから空いてる？ご飯行こうよ！"},
        {"sender": "鈴木", "text": "土曜13時空いてるよ！最近どこも混んでるから、渋谷や新宿の混雑は避けたいな〜"},
        {"sender": "田中", "text": "いいね！美味しいお肉かバル系食べたい！ちなみに私「中目黒」から行くよ"},
        {"sender": "鈴木", "text": "俺は「吉祥寺」から向かう！"},
        {"sender": "佐藤", "text": "了解！俺は「横浜」から乗るから、みんなが来やすい場所がいいな"},
        {"sender": "高橋", "text": "参加する！「柏」から向かうから常磐線・上野東京ライン使えると嬉しい"},
    ],
    "cafe_girls_3": [
        {"sender": "美咲", "text": "今度の日曜14時にゆっくりお茶しない？"},
        {"sender": "結衣", "text": "行きたい！落ち着いておしゃべりできる静かなカフェがいいな。私は「三軒茶屋」から行くよ"},
        {"sender": "陽菜", "text": "賛成！私は「北千住」から日比谷線で向かうね"},
        {"sender": "美咲", "text": "私は「恵比寿」！真ん中あたりの穴場探そう"},
    ],
    "craft_beer_3": [
        {"sender": "健太", "text": "金曜日の19時に仕事終わりにクラフトビール飲みに行かない？"},
        {"sender": "大輔", "text": "最高！俺は「大宮」から京浜東北で向かうよ"},
        {"sender": "翔平", "text": "俺は「品川」で退勤予定！"},
        {"sender": "健太", "text": "俺は「立川」の中央線だから、ちょうど真ん中がいいな"},
    ],
}
HUB_CACHE_SECONDS = 30 * 86400
_SHOP_ID = re.compile(r"^(J\d{6,12}|TO[0-9a-f]{12})$")
PAGE = 6                 # cards per carousel, as in the LINE bot (bot/group.py)
LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_SUGGESTIONS = 3      # as in the LINE bot
DEMO_HINT = "このページでは、投票・別の候補・お店の提案が使えます。"


class ScenarioRequest(BaseModel):
    scenario_id: str


class ChatRequest(BaseModel):
    messages: list[dict[str, str]]


class MoreRequest(BaseModel):
    scenario_id: Optional[str] = None
    messages: Optional[list[dict[str, str]]] = None
    page: int = 1


class SuggestRequest(BaseModel):
    text: str
    hub: dict[str, Any]
    n: int = 1
    sender: str = "メンバー"


class ReserveRequest(BaseModel):
    venue_id: str
    plan: dict[str, Any] = {}


def _deps(request: Request) -> Deps:
    return request.app.state.deps


def _is_admin(deps: Deps, token: Optional[str]) -> bool:
    expected = deps.settings.admin_api_token
    return bool(expected) and bool(token) and hmac.compare_digest(expected, token)


async def _is_judge(deps: Deps, code: Optional[str]) -> bool:
    """The shared judges' code (made with /judge) also unlocks free text here; single-use invites don't."""
    code = normalize_invite_code(code or "")
    invite = await deps.store.get("invites", code) if code else None
    return bool(invite) and (invite.get("max_uses") or 1) > 1 and invite.get("expires_at", 0) >= deps.clock()


async def _cached_hub(deps: Deps, stations: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    key = "|".join(sorted({s["name"] for s in stations}))
    cached = await deps.store.get("cache_hub", key.replace("/", "／")[:400])
    if cached:
        return cached["hub"]
    hub = await find_hub(deps.ekispert, stations)
    if hub:
        await deps.store.set("cache_hub", key.replace("/", "／")[:400],
                             {"hub": hub, "expire_at": deps.clock() + HUB_CACHE_SECONDS})
    return hub


async def run_pipeline(deps: Deps, messages: list[dict[str, str]], use_llm: bool, page: int = 0) -> dict[str, Any]:
    logs: list[dict[str, str]] = []
    senders: list[str] = []
    origins: dict[str, dict[str, Any]] = {}
    hint: dict[str, str] = {}
    for m in messages:
        sender, text = m.get("sender", "メンバー")[:20], m.get("text", "")[:300]
        if sender not in senders:
            senders.append(sender)
        hint = merge_hints(hint, date_hint(text))
        if sender not in origins:
            station = await deps.stations.from_text(text)
            if station:
                origins[sender] = station
    logs.append({"agent_name": "Agent 1", "step": f"出発駅を{len(origins)}人分、駅すぱあとの駅データで確認"})

    numbered = [(senders.index(m.get("sender", "メンバー")[:20]) + 1, m.get("text", "")[:300]) for m in messages]
    if use_llm:
        details = await schedule_agent.extract_details(deps.llm, numbered, hint)
    else:
        details = schedule_agent.rule_based_details([t for _, t in numbered], hint)
    logs.append({"agent_name": "Agent 1", "step": f"日時と希望を読み取り（{'LLM' if details.get('source') == 'llm' else 'ルール'}）"})

    result: dict[str, Any] = {"bot_messages": [], "session_state": {
        "schedule_data": {"members": senders, "origins": {k: v["name"] for k, v in origins.items()},
                          "date_time": hint_text(hint), "details": details},
        "midpoint_data": None, "venues": [], "agent_logs": logs}, "plan": None}
    if len(origins) < 2:
        result["bot_messages"].append({"type": "text", "text": "出発駅が2人分以上わかると、集合駅を探せます。"})
        return result

    hub = await _cached_hub(deps, list(origins.values()))
    if not hub:
        result["bot_messages"].append({"type": "text", "text": "全員が行きやすい駅が見つかりませんでした。"})
        return result
    logs.append({"agent_name": "Agent 2", "step": f"駅すぱあと範囲探索で集合駅を算出：{hub['name']}"})
    station = await deps.stations.by_code(hub["code"])
    pax = len(senders)
    picks = await spot_agent.shortlist(deps.llm, deps.hotpepper, station, details, pax, use_llm=use_llm,
                                       featured=deps.featured, timeout=deps.timeout)
    pages = max(1, math.ceil(len(picks) / PAGE))
    page = min(max(page, 0), pages - 1)
    chunk = picks[page * PAGE:(page + 1) * PAGE]
    shops = await deps.shops([p["id"] for p in chunk])
    chunk = [p for p in chunk if p["id"] in shops]
    labels = [LABELS[page * PAGE + i] for i in range(len(chunk))]
    logs.append({"agent_name": "Agent 3", "step": f"ホットペッパーで{hub['name']}駅周辺のお店を{len(picks)}軒選定（{page + 1}/{pages}ページ目を表示）"})

    people = [(name, origins[name]["name"], hub["minutes"].get(origins[name]["name"], 0)) for name in senders if name in origins]
    carousel = line_flex.venues_carousel(
        "sim", [shops[p["id"]] for p in chunk], chunk, labels, pages - page - 1, 0,
        [deps.featured(shops[p["id"]]) for p in chunk], hint=DEMO_HINT)
    result["bot_messages"] = [
        {"type": "flex", "flex": line_flex.hub_card(hub, people, schedule_agent.details_text(details))},
        {"type": "flex", "flex": carousel},
    ]
    result["session_state"]["midpoint_data"] = {
        "hub_station": hub["name"], "max_travel_time": hub["max"], "spread_minutes": hub["spread"],
        "avg_travel_time": hub["avg"], "alternatives": hub["alternatives"],
        "members": {name: {"origin": st, "travel_time": mins,
                           "transfers": hub["transfers"].get(st, 0)} for name, st, mins in people},
    }
    result["session_state"]["venues"] = [
        {"id": p["id"], "name": shops[p["id"]]["name"], "reason": p["reason"], "crowd": p["crowd"]} for p in chunk]
    result["plan"] = {"day": details.get("day"), "time": details.get("time"), "pax": pax,
                      "organizer": senders[0], "hub_name": hub["name"],
                      "hub": {"name": hub["name"], "lat": station.get("lat"), "lng": station.get("lng")},
                      "page": page, "pages": pages,
                      "walk": {p["id"]: p.get("walk_min") for p in chunk}}
    return result


@router.post("/scenario")
async def scenario(request: Request, req: ScenarioRequest) -> dict[str, Any]:
    deps = _deps(request)
    messages = SCENARIOS.get(req.scenario_id)
    if messages is None:
        raise HTTPException(404, "unknown scenario")
    if not await deps.usage.take("simulator"):
        raise HTTPException(429, "本日のデモ実行回数の上限に達しました。LINE版をお試しください。")
    result = await run_pipeline(deps, messages, use_llm=False)
    return {"status": "ok", "scenario_id": req.scenario_id, "input_messages": messages, **result}


@router.post("/chat")
async def chat(request: Request, req: ChatRequest, x_admin_token: Optional[str] = Header(default=None),
               x_access_code: Optional[str] = Header(default=None)) -> dict[str, Any]:
    deps = _deps(request)
    if not (_is_admin(deps, x_admin_token) or await _is_judge(deps, x_access_code)):
        raise HTTPException(403, "自由入力には審査用コードが必要です。メッセージ欄のすぐ上の「審査用コード」に入れてから送ってください（シナリオ再生はコードなしで使えます）。")
    if not await deps.usage.take("simulator"):
        raise HTTPException(429, "本日のデモ実行回数の上限に達しました。")
    return {"status": "ok", **await run_pipeline(deps, req.messages[-30:], use_llm=True)}


async def _authorized(deps: Deps, admin: Optional[str], code: Optional[str]) -> bool:
    return _is_admin(deps, admin) or await _is_judge(deps, code)


@router.post("/more")
async def more(request: Request, req: MoreRequest, x_admin_token: Optional[str] = Header(default=None),
               x_access_code: Optional[str] = Header(default=None)) -> dict[str, Any]:
    """"別の候補を見る": the next page of the same shortlist (the same chat gives the same hub and venues)."""
    deps = _deps(request)
    if req.scenario_id is not None:
        messages, use_llm = SCENARIOS.get(req.scenario_id), False
        if messages is None:
            raise HTTPException(404, "unknown scenario")
    elif req.messages and await _authorized(deps, x_admin_token, x_access_code):
        messages, use_llm = req.messages[-30:], True
    else:
        raise HTTPException(403, "自由入力の続きには審査用コードが必要です。")
    if not 1 <= req.page <= 10:
        raise HTTPException(400, "invalid page")
    if not await deps.usage.take("simulator"):
        raise HTTPException(429, "本日のデモ実行回数の上限に達しました。LINE版をお試しください。")
    result = await run_pipeline(deps, messages, use_llm=use_llm, page=req.page)
    if not result["plan"] or result["plan"]["page"] != req.page:
        return {"status": "none", "bot_messages": [{"type": "text", "text": "ほかの候補はもうありません。"}]}
    result["bot_messages"] = result["bot_messages"][1:]   # the hub card was already shown
    return {"status": "ok", **result}


def _valid_hub(hub: dict[str, Any]) -> Optional[dict[str, Any]]:
    try:
        lat, lng = float(hub["lat"]), float(hub["lng"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (20 <= lat <= 46 and 122 <= lng <= 154):
        return None
    return {"name": str(hub.get("name") or "")[:20], "lat": lat, "lng": lng}


@router.post("/suggest")
async def suggest(request: Request, req: SuggestRequest) -> dict[str, Any]:
    """"💡 お店を提案する": a place by name, looked up near the meeting station (HotPepper first, then Places)."""
    deps = _deps(request)
    text = req.text.strip()[:60]
    if not text or URL_RE.search(text):
        raise HTTPException(400, "Webデモでは、お店の名前で提案してください（例：肉ごこち 秋葉原）。")
    hub = _valid_hub(req.hub)
    if hub is None:
        raise HTTPException(400, "先にシナリオを実行して、集合駅を決めてください。")
    if not 1 <= req.n <= MAX_SUGGESTIONS:
        raise HTTPException(400, f"お店の提案は{MAX_SUGGESTIONS}件までです。")
    if not await deps.usage.take("simulator"):
        raise HTTPException(429, "本日のデモ実行回数の上限に達しました。LINE版をお試しください。")
    try:
        shop = await resolve_suggestion(deps, text, hub)
    except SuggestionError as e:
        raise HTTPException(404, e.message)
    walk = spot_agent.walk_minutes(shop, hub)
    name = req.sender.strip()[:20] or "メンバー"
    entry = {"id": shop["id"], "suggested_by": name, "walk_min": walk, "reason": f"{name}さんの提案"}
    return {"status": "ok", "venue": {"id": shop["id"], "name": shop["name"], "walk_min": walk},
            "bot_messages": [{"type": "flex", "flex": line_flex.suggestion_card("sim", f"提案{req.n}", shop, entry)}]}


@router.post("/reserve")
async def reserve(request: Request, req: ReserveRequest) -> dict[str, Any]:
    deps = _deps(request)
    if not _SHOP_ID.match(req.venue_id):
        raise HTTPException(400, "invalid venue id")
    if not await deps.usage.take("simulator"):
        raise HTTPException(429, "本日のデモ実行回数の上限に達しました。LINE版をお試しください。")
    shop = (await deps.shops([req.venue_id])).get(req.venue_id)
    if not shop:
        raise HTTPException(404, "venue not found")
    plan = req.plan or {}
    pax = int(plan.get("pax") or 2)
    day, time = plan.get("day"), plan.get("time")
    organizer = str(plan.get("organizer") or "幹事")[:20]
    when = " ".join(x for x in (day, time) if x) or None
    script = voice_agent.call_script(shop["name"], day, time, pax, organizer)
    agent_url = None
    if deps.form_agent is not None:
        from bot.group import GroupBot
        agent_url = await GroupBot(deps)._agent_link(
            {"day": day, "time": time, "pax": pax, "organizer_name": organizer}, shop)
    walk = (plan.get("walk") or {}).get(req.venue_id)
    return {
        "status": "ok",
        "shop": {"name": shop["name"], "url": shop.get("url")},
        "script": script,
        "agent_url": agent_url,
        "bot_messages": [
            {"type": "flex", "flex": line_flex.decision_card(shop, when, pax, walk, plan.get("hub_name") or "", agent_url)},
            {"type": "flex", "flex": line_flex.script_card(script, shop.get("telephone"), shop.get("url"))},
        ],
    }


@router.get("/session")
async def session() -> dict[str, Any]:
    return {"mode": "replay", "scenarios": list(SCENARIOS)}


@router.post("/reset")
async def reset() -> dict[str, str]:
    return {"status": "reset"}
