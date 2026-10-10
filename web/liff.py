"""
LIFF pages (web pages that open inside LINE) and their API: the taste profile, the station picker, and the
date poll. Every API call carries the LIFF ID token; the person is whoever LINE says signed it.
"""

import os
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from bot import poll as polls
from bot.deps import Deps
from services import taste

router = APIRouter()
PROFILE_DAYS = 180
SHELL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "liff", "index.html")


def _deps(request: Request) -> Deps:
    return request.app.state.deps


async def _user(request: Request, authorization: Optional[str]) -> tuple[str, str, str]:
    """(LINE user ID, hashed ID, display name) for the person using the page."""
    deps = _deps(request)
    token = (authorization or "").removeprefix("Bearer ").strip()
    user = await deps.liff.verify(token) if deps.liff else None
    if not user:
        raise HTTPException(401, "LINEでログインし直してください。")
    return user.user_id, deps.ids.user(user.user_id), user.name


def _poll_ref(deps: Deps, token: str) -> tuple[str, str]:
    data = deps.ids.verify(token or "")
    if not data or data.get("k") != "poll":
        raise HTTPException(404, "このリンクは無効か、有効期限が切れています。")
    return data["g"], data["n"]


@router.get("/liff", response_class=HTMLResponse)
@router.get("/liff/{path:path}", response_class=HTMLResponse)
async def liff_shell(request: Request, path: str = "") -> HTMLResponse:
    with open(SHELL, encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(html.replace("__LIFF_ID__", _deps(request).settings.liff_id),
                        headers={"Cache-Control": "no-store"})


# ---- profile -------------------------------------------------------------------------------------

class ProfileIn(BaseModel):
    likes: list[str] = []
    dislikes: list[str] = []
    station_code: Optional[str] = None


@router.get("/api/liff/taxonomy")
async def get_taxonomy() -> dict[str, Any]:
    return taste.taxonomy()


@router.get("/api/liff/profile")
async def get_profile(request: Request, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _, uhash, name = await _user(request, authorization)
    prof = await _deps(request).store.get("profiles", uhash) or {}
    return {"name": name, "likes": prof.get("likes", []), "dislikes": prof.get("dislikes", []),
            "station": prof.get("station"), "exists": bool(prof)}


@router.put("/api/liff/profile")
async def put_profile(request: Request, body: ProfileIn, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _, uhash, _ = await _user(request, authorization)
    deps = _deps(request)
    likes = taste.clean_choices(body.likes)
    dislikes = [d for d in taste.clean_choices(body.dislikes) if d not in likes]
    station = None
    if body.station_code and body.station_code.isdigit():
        found = await deps.stations.by_code(body.station_code)
        if found:
            station = {"name": found["name"], "code": found["code"]}
    now = deps.clock()
    old = await deps.store.get("profiles", uhash) or {}
    doc = {"likes": likes, "dislikes": dislikes, "station": station or old.get("station"),
           "updated_at": now, "expire_at": now + PROFILE_DAYS * 86400}
    await deps.store.set("profiles", uhash, doc)
    return {"ok": True, "station": doc["station"]}


@router.delete("/api/liff/profile")
async def delete_profile(request: Request, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _, uhash, _ = await _user(request, authorization)
    await _deps(request).store.delete("profiles", uhash)
    return {"ok": True}


class Point(BaseModel):
    lat: float
    lng: float


@router.post("/api/liff/stations/near")
async def stations_near(request: Request, body: Point, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    await _user(request, authorization)
    if not (20 <= body.lat <= 46 and 122 <= body.lng <= 154):
        raise HTTPException(400, "日本国内の位置情報だけに対応しています。")
    found = await _deps(request).ekispert.stations_near(body.lat, body.lng, count=3)
    return {"stations": [{"name": s["name"], "code": s["code"], "distance_m": s.get("distance_m")} for s in found]}


@router.get("/api/liff/stations")
async def stations_search(request: Request, q: str = "", authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    await _user(request, authorization)
    q = q.strip()[:20]
    if not q:
        return {"stations": []}
    found = await _deps(request).ekispert.find_stations(q)
    seen, out = set(), []
    for s in found:
        if s["name"] not in seen:
            seen.add(s["name"])
            out.append({"name": s["name"], "code": s["code"], "pref": s.get("pref")})
    return {"stations": out[:8]}


# ---- date poll -----------------------------------------------------------------------------------

class PollDates(BaseModel):
    t: str
    dates: list[str]
    slot: Optional[str] = None


class PollAnswer(BaseModel):
    t: str
    marks: dict[str, str]


@router.get("/api/liff/poll")
async def get_poll(request: Request, t: str, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _, uhash, _ = await _user(request, authorization)
    deps = _deps(request)
    ghash, nonce = _poll_ref(deps, t)
    poll = await deps.store.get("polls", ghash)
    if not poll or poll.get("nonce") != nonce:
        raise HTTPException(404, "この日程調整は終わっています。")
    return polls.view(poll, uhash)


@router.post("/api/liff/poll/dates")
async def set_poll_dates(request: Request, body: PollDates, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _, uhash, _ = await _user(request, authorization)
    deps = _deps(request)
    ghash, nonce = _poll_ref(deps, body.t)
    outcome, poll = await polls.set_dates(deps.store, ghash, nonce, uhash, body.dates, body.slot, deps.clock())
    if outcome == "not_organizer":
        raise HTTPException(403, f"候補日をえらべるのは幹事（{poll.get('organizer_name')}さん）だけです。")
    if outcome == "no_dates":
        raise HTTPException(400, "今日以降の日付をえらんでください。")
    if outcome != "ok":
        raise HTTPException(404, "この日程調整は終わっています。")
    return {"ok": True, "count": len(poll["dates"])}


@router.post("/api/liff/poll/answer")
async def answer_poll(request: Request, body: PollAnswer, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _, uhash, name = await _user(request, authorization)
    deps = _deps(request)
    ghash, nonce = _poll_ref(deps, body.t)
    outcome, poll, first = await polls.answer(deps.store, ghash, nonce, uhash, name, body.marks)
    if outcome != "ok":
        raise HTTPException(409, "この日程調整は締め切られています。")
    return {"ok": True, "first": first, "poll": polls.view(poll, uhash)}
