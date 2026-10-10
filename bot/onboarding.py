"""
1:1 chat with the bot: getting verified with an invite code, and admin commands.

A verified user is a LINE user who redeemed a single-use invite code. LINE has already authenticated
them (the webhook signature proves the event came from LINE), so the code only decides who is allowed in.
The admin is recognised by their LINE user ID and is always verified.
"""

import datetime as dt
from typing import Any

from bot import texts
from bot.deps import Deps
from services import line_flex
from services.ids import new_invite_code, normalize_invite_code
from services.store import KEEP
from services.usage import JST


async def handle(deps: Deps, ev: dict[str, Any]) -> None:
    user_id = ev.get("source", {}).get("userId")
    if not user_id:
        return
    is_admin = bool(deps.settings.line_admin_user_id) and user_id == deps.settings.line_admin_user_id
    uhash = deps.ids.user(user_id)
    if is_admin:
        await _ensure_admin(deps, uhash)

    if ev["type"] == "follow":
        user = await deps.store.get("users", uhash)
        verified = is_admin or bool(user and user.get("verified"))
        greeting = texts.GREETING_ADMIN if is_admin else texts.GREETING_VERIFIED if verified else texts.GREETING
        await deps.reply(ev, [line_flex.plain(greeting)] + _profile_offer(deps, verified))
        return

    if ev["type"] != "message" or ev.get("message", {}).get("type") != "text":
        return
    text = ev["message"]["text"].strip()
    if text in ("プロフィール", "/profile", "好み"):
        user = await deps.store.get("users", uhash)
        offer = _profile_offer(deps, is_admin or bool(user and user.get("verified")))
        await deps.reply(ev, offer or [line_flex.plain(texts.ASK_FOR_CODE)])
        return
    if is_admin and text.startswith("/"):
        await _admin_command(deps, ev, text)
        return
    code = normalize_invite_code(text)
    if code:
        await _redeem(deps, ev, uhash, code)
        return
    user = await deps.store.get("users", uhash)
    await deps.reply(ev, [line_flex.plain(texts.ALREADY_VERIFIED if user and user.get("verified")
                                          else texts.ASK_FOR_CODE)])


async def _ensure_admin(deps: Deps, uhash: str) -> None:
    def fn(docs):
        user = docs[0]
        if user and user.get("is_admin") and user.get("verified"):
            return [KEEP], None
        user = dict(user or {"groups_activated": 0})
        user.update(verified=True, is_admin=True, via="admin", verified_at=deps.clock())
        return [user], None

    await deps.store.transact([("users", uhash)], fn)


async def _redeem(deps: Deps, ev: dict[str, Any], uhash: str, code: str) -> None:
    now = deps.clock()
    limit = deps.settings.groups_per_user

    def fn(docs):
        invite, user = docs
        if user and user.get("verified"):
            return [KEEP, KEEP], ("already", 0)
        if not invite:
            return [KEEP, KEEP], ("unknown", 0)
        if invite.get("used_by"):
            return [KEEP, KEEP], ("used", 0)
        if invite.get("expires_at", 0) < now:
            return [KEEP, KEEP], ("expired", 0)
        invite = dict(invite, used_by=uhash, used_at=now, expire_at=now + 30 * 86400)
        user = {"verified": True, "verified_at": now, "via": "invite", "groups_activated": 0}
        return [invite, user], ("ok", limit)

    outcome, left = await deps.store.transact([("invites", code), ("users", uhash)], fn)
    message = {
        "ok": texts.verified(left), "already": texts.ALREADY_VERIFIED, "unknown": texts.CODE_UNKNOWN,
        "used": texts.CODE_USED, "expired": texts.CODE_EXPIRED,
    }[outcome]
    await deps.reply(ev, [line_flex.plain(message)] + (_profile_offer(deps, True) if outcome == "ok" else []))


def _profile_offer(deps: Deps, verified: bool) -> list[dict[str, Any]]:
    if not verified or not deps.settings.liff_id:
        return []
    return [line_flex.profile_offer(f"https://liff.line.me/{deps.settings.liff_id}/profile")]


async def create_invites(deps: Deps, count: int) -> list[str]:
    now = deps.clock()
    expires = now + deps.settings.invite_ttl_days * 86400
    codes = []
    while len(codes) < count:
        code = new_invite_code()
        doc = {"created_at": now, "expires_at": expires, "used_by": None, "expire_at": expires + 7 * 86400}
        if await deps.store.create_if_absent("invites", code, doc):
            codes.append(code)
    return codes


async def _admin_command(deps: Deps, ev: dict[str, Any], text: str) -> None:
    parts = text.split()
    command = parts[0].lower()
    s = deps.settings
    if command == "/invite":
        try:
            count = max(1, min(20, int(parts[1]))) if len(parts) > 1 else 1
        except ValueError:
            count = 1
        codes = await create_invites(deps, count)
        until = dt.datetime.fromtimestamp(deps.clock() + s.invite_ttl_days * 86400, JST).strftime("%-m/%-d")
        body = "\n".join(codes)
        await deps.reply(ev, [line_flex.plain(f"招待コード（各1回・{until}まで有効）"), line_flex.plain(body)])
    elif command == "/stats":
        today = await deps.usage.today()
        users = await deps.store.count("users")
        groups = await deps.store.count("groups")
        plans = await deps.store.count("plans")
        lines = [f"今日：検索 {today.get('searches', 0)}/{s.daily_search_limit}・LLM {today.get('llm', 0)}/{s.daily_llm_limit}"
                 f"・Places {today.get('places', 0)}/{s.daily_places_limit}",
                 f"Ekispert {today.get('ekispert', 0)}・HotPepper {today.get('hotpepper', 0)}"
                 f"・シミュレーター {today.get('simulator', 0)}/{s.daily_simulator_limit}",
                 f"認証済みユーザー {users}・グループ {groups}・進行中のプラン {plans}"]
        await deps.reply(ev, [line_flex.plain("\n".join(lines))])
    elif command == "/limits":
        await deps.reply(ev, [line_flex.plain(
            f"1グループ：お店{s.plans_per_group}軒・検索{s.searches_per_group}回・有効{s.group_active_days}日・参加{s.max_participants}人\n"
            f"1ユーザー：有効化{s.groups_per_user}グループ\n"
            f"1日：検索{s.daily_search_limit}・LLM{s.daily_llm_limit}・Places{s.daily_places_limit}")])
    else:
        await deps.reply(ev, [line_flex.plain(texts.ADMIN_HELP)])
