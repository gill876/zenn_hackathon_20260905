"""
Group chat lifecycle: phases 0–6 in the AsobiAgent Group Flow wireframe.

  pending ─(verified member taps 有効化)→ active ─(1 venue decided)→ done, bot leaves
  inside active, a plan moves: gathering → ready → searching → voting → (decided)

Rules that keep it cheap and private:
- Nothing is read until a plan is gathering, and then only participants' messages.
- Only phase 4 (search) and refinements call paid APIs; both count toward the group's search limit
  and the service's daily limit.
- Every message is a reply to someone's action, so no LINE push quota is used.
- Chat text is deleted once the search has read it; names and votes are deleted at the decision.
"""

import copy
import datetime as dt
import logging
import math
import secrets
from collections import Counter
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import parse_qs

from agents import schedule_agent, spot_agent, voice_agent
from agents.ekispert_agent import find_hub
from agents.group_picks import group_picks
from bot import poll as polls
from bot import texts
from bot.deps import Deps
from bot.text_parse import JOIN_WORDS, PASS_WORDS, date_hint, hint_text, is_trigger_text, merge_hints
from services import line_flex
from services.ids import new_nonce
from services.store import KEEP
from services.suggest import URL as URL_RE
from services.suggest import SuggestionError
from services.suggest import resolve as resolve_suggestion
from services.taste import group_taste
from services.usage import JST

log = logging.getLogger("group")

PAGE = 6
LABELS = "ABCDEFGHIJKL"
MAX_SUGGESTIONS = 3
POLL_CREATED = "日程調整を作りました"
POLL_ANSWERED = "日程に回答しました"
STALE_SEARCH_SECONDS = 120
DAY = 86400


class SearchProblem(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class Ctx:
    ev: dict[str, Any]
    kind: str
    chat_id: str
    ghash: str
    user_id: Optional[str]
    uhash: Optional[str]
    now: float


def _day(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, JST).strftime("%-m/%-d")


def _people(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(plan["participants"].values(), key=lambda p: p["n"])


def _all_have_stations(plan: dict[str, Any]) -> bool:
    people = list(plan["participants"].values())
    return len(people) >= 2 and all(p.get("station") for p in people)


def _station_rows(plan: dict[str, Any]) -> list[tuple[str, Optional[str]]]:
    return [(p["name"], (p.get("station") or {}).get("name")) for p in _people(plan)]


def _when(plan: dict[str, Any]) -> Optional[str]:
    details = plan.get("details") or {}
    parts = [p for p in (details.get("day"), details.get("time")) if p]
    return " ".join(parts) if parts else hint_text(plan.get("hint"))


def _all_votes(plan: dict[str, Any]) -> Counter:
    return Counter(v for p in plan["participants"].values() for v in p.get("votes", []))


def _labels(plan: dict[str, Any]) -> dict[str, str]:
    """Card label per candidate: A, B, … for the bot's picks, 提案1… for suggestions."""
    out = {p["id"]: LABELS[i] for i, p in enumerate(plan.get("picks", [])[:len(LABELS)])}
    for i, sg in enumerate(plan.get("suggestions", [])):
        out[sg["id"]] = f"提案{i + 1}"
    return out


def _is_suggestion(request: str) -> bool:
    return request.startswith("提案") or bool(URL_RE.search(request))


def _strip_self_mentions(message: dict[str, Any]) -> str:
    text = message.get("text", "")
    mentionees = (message.get("mention") or {}).get("mentionees") or []
    for m in sorted((m for m in mentionees if m.get("isSelf")), key=lambda m: m["index"], reverse=True):
        text = text[:m["index"]] + text[m["index"] + m["length"]:]
    return text.strip()


class GroupBot:
    def __init__(self, deps: Deps):
        self.d = deps
        self.s = deps.settings

    # ---- storage helpers ------------------------------------------------------------------------

    async def _txn(self, ghash: str, fn):
        return await self.d.store.transact([("groups", ghash), ("plans", ghash)], fn)

    def _touch(self, group: dict[str, Any], now: float) -> dict[str, Any]:
        group = dict(group)
        group["updated_at"] = now
        group["expire_at"] = now + self.s.group_retention_days * DAY
        return group

    def _new_group(self, now: float, old: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._touch({"state": "pending", "invited_at": now,
                            "plans_used": (old or {}).get("plans_used", 0),
                            "searches_used": (old or {}).get("searches_used", 0)}, now)

    def _used_up(self, group: Optional[dict[str, Any]]) -> bool:
        return bool(group) and (group.get("plans_used", 0) >= self.s.plans_per_group
                                or group.get("searches_used", 0) >= self.s.searches_per_group)

    def _searches_left(self, group: dict[str, Any]) -> int:
        return max(0, self.s.searches_per_group - group.get("searches_used", 0))

    async def _leave(self, c: Ctx) -> None:
        await self.d.line.leave(c.kind, c.chat_id)

    # ---- entry point ----------------------------------------------------------------------------

    async def handle(self, ev: dict[str, Any], kind: str, chat_id: str, user_id: Optional[str]) -> None:
        c = Ctx(ev, kind, chat_id, self.d.ids.chat(chat_id), user_id,
                self.d.ids.user(user_id) if user_id else None, self.d.clock())
        etype = ev.get("type")
        if etype == "join":
            await self.on_join(c)
        elif etype == "leave":
            await self._txn(c.ghash, lambda docs: ([KEEP, None], None))
        elif etype == "memberLeft":
            await self.on_members_left(c)
        elif etype == "message" and ev.get("message", {}).get("type") == "text":
            await self.on_text(c)
        elif etype == "postback":
            await self.on_postback(c)

    async def on_join(self, c: Ctx) -> None:
        now, s = c.now, self.s

        def fn(docs):
            group, _ = docs
            if self._used_up(group):
                return [self._touch(group, now), None], ("used_up", None)
            if group and group.get("state") == "active" and group.get("active_until", 0) > now:
                return [self._touch(group, now), KEEP], ("still_active", group)
            return [self._new_group(now, group), None], ("welcome", None)

        outcome, group = await self._txn(c.ghash, fn)
        if outcome == "used_up":
            await self.d.reply(c.ev, [line_flex.plain(texts.USED_UP)])
            await self._leave(c)
        elif outcome == "still_active":
            await self.d.reply(c.ev, [line_flex.activated(s.plans_per_group - group.get("plans_used", 0),
                                                          self._searches_left(group), _day(group["active_until"]))])
        else:
            await self.d.reply(c.ev, [line_flex.welcome()])

    async def on_members_left(self, c: Ctx) -> None:
        gone = {self.d.ids.user(m["userId"]) for m in c.ev.get("left", {}).get("members", []) if m.get("userId")}
        if not gone:
            return

        def fn(docs):
            group, plan = docs
            if not plan or plan["phase"] not in ("gathering", "ready", "voting"):
                return [KEEP, KEEP], None
            plan = copy.deepcopy(plan)
            for u in gone:
                plan["participants"].pop(u, None)
            return [KEEP, plan], None

        await self._txn(c.ghash, fn)

    # ---- the gate every message and button goes through ------------------------------------------

    async def _gate(self, c: Ctx) -> Optional[tuple[dict[str, Any], Optional[dict[str, Any]]]]:
        group = await self.d.store.get("groups", c.ghash)
        plan = await self.d.store.get("plans", c.ghash)
        if group is None:
            # The bot was in this group before we kept any record of it: start over as pending.
            group = self._new_group(c.now)
            await self.d.store.set("groups", c.ghash, group)
        state = group.get("state")
        if state in ("done", "expired"):
            await self._leave(c)
            return None
        if state == "pending" and c.now - group["invited_at"] > self.s.activation_window_hours * 3600:
            await self.d.store.set("groups", c.ghash, dict(self._touch(group, c.now), state="expired"))
            await self.d.reply(c.ev, [line_flex.plain(texts.PENDING_TIMEOUT)])
            await self._leave(c)
            return None
        if state == "active" and c.now > group.get("active_until", 0):
            await self._txn(c.ghash, lambda docs: ([dict(self._touch(docs[0], c.now), state="expired"), None], None))
            await self.d.reply(c.ev, [line_flex.plain(texts.ACTIVE_EXPIRED)])
            await self._leave(c)
            return None
        return group, plan

    # ---- messages -------------------------------------------------------------------------------

    async def on_text(self, c: Ctx) -> None:
        message = c.ev["message"]
        text = message.get("text", "")
        mentioned = any(m.get("isSelf") for m in (message.get("mention") or {}).get("mentionees") or [])
        trigger = mentioned or is_trigger_text(text)
        request = _strip_self_mentions(message)
        if is_trigger_text(request):
            request = request.split(maxsplit=1)[1] if len(request.split(maxsplit=1)) > 1 else ""

        gated = await self._gate(c)
        if gated is None:
            return
        group, plan = gated
        if group["state"] == "pending":
            if trigger:
                await self.d.reply(c.ev, [line_flex.welcome()])
            return
        if not c.uhash:
            return
        stripped = text.strip()
        if stripped.startswith(POLL_CREATED):
            await self.announce_poll(c)
            return
        if stripped.startswith(POLL_ANSWERED):
            return
        if trigger and request.startswith("日程"):
            await self.start_poll(c, plan)
            return
        if plan is None:
            if trigger:
                await self.start_plan(c, group, request)
            return

        phase = plan["phase"]
        if phase in ("gathering", "ready"):
            if c.uhash in plan["participants"]:
                if stripped in PASS_WORDS:
                    await self.pass_plan(c, None)
                else:
                    await self.on_participant_message(c, text)
            elif stripped in JOIN_WORDS:
                await self.join(c, None)
            elif trigger:
                missing = [name for name, station in _station_rows(plan) if not station]
                await self.d.reply(c.ev, [line_flex.plain(texts.gathering_status(missing))])
        elif phase == "searching":
            if trigger:
                await self.d.reply(c.ev, [line_flex.plain(texts.SEARCHING)])
        elif phase == "voting":
            if trigger and request and _is_suggestion(request):
                await self.suggest(c, plan, request.removeprefix("提案").strip())
            elif trigger and request:
                await self.refine(c, plan["nonce"], request=request)
            elif trigger:
                await self.d.reply(c.ev, [line_flex.plain(texts.VOTING_HINT)])

    async def on_participant_message(self, c: Ctx, text: str) -> None:
        station = await self.d.stations.from_text(text)
        hint = date_hint(text)
        max_held = self.s.held_messages_max

        def fn(docs):
            group, plan = docs
            if not plan or plan["phase"] not in ("gathering", "ready") or c.uhash not in plan["participants"]:
                return [KEEP, KEEP], (None, None)
            plan = copy.deepcopy(plan)
            me = plan["participants"][c.uhash]
            if len(plan["held"]) < max_held:
                plan["held"].append({"n": me["n"], "t": text[:300]})
            changed = False
            if station and (me.get("station") or {}).get("name") != station["name"]:
                me["station"] = {"name": station["name"], "code": station["code"]}
                changed = True
            before = hint_text(plan.get("hint"))
            plan["hint"] = merge_hints(plan.get("hint"), hint)
            outcome = None
            if _all_have_stations(plan) and (plan["phase"] == "gathering" or changed):
                plan["phase"] = "ready"
                for p in plan["participants"].values():
                    p["ready"] = False
                outcome = "go" if plan.get("auto_search") else "ready_card"
            elif plan["phase"] == "ready" and hint_text(plan["hint"]) != before:
                outcome = "when"
            return [self._touch(group, c.now), plan], (outcome, plan)

        outcome, plan = await self._txn(c.ghash, fn)
        if outcome == "go":
            await self.search(c, plan["nonce"])
        elif outcome == "ready_card":
            await self.d.reply(c.ev, [line_flex.ready_check(plan["nonce"], _station_rows(plan), hint_text(plan.get("hint")))])
        elif outcome == "when":
            await self.d.reply(c.ev, [line_flex.plain(texts.when_noted(hint_text(plan["hint"])))])

    # ---- buttons --------------------------------------------------------------------------------

    async def on_postback(self, c: Ctx) -> None:
        data = {k: v[0] for k, v in parse_qs(c.ev.get("postback", {}).get("data", "")).items()}
        action, nonce = data.get("a"), data.get("p")
        if not c.user_id:
            await self.d.reply(c.ev, [line_flex.plain(texts.USE_PHONE_APP)])
            return
        gated = await self._gate(c)
        if gated is None:
            return
        group, plan = gated
        if group["state"] == "pending":
            if action == "activate":
                await self.activate(c)
            return
        if action == "activate":
            await self.d.reply(c.ev, [line_flex.plain(texts.ALREADY_ACTIVE)])
        elif action == "start":
            if plan is None:
                await self.start_plan(c, group, "")
            else:
                await self.d.reply(c.ev, [line_flex.plain(texts.gathering_status([]) if plan["phase"] in ("gathering", "ready")
                                                          else texts.VOTING_HINT)])
        elif action == "join":
            await self.join(c, nonce)
        elif action == "pass":
            await self.pass_plan(c, nonce)
        elif action == "ready":
            await self.ready(c, nonce)
        elif action == "force":
            await self.force(c, nonce, plan)
        elif action == "fix":
            await self.d.reply(c.ev, [line_flex.plain(texts.FIX_STATION)])
        elif action == "vote":
            await self.vote(c, nonce, data.get("v"), forced=False)
        elif action == "close":
            await self.vote(c, nonce, None, forced=True)
        elif action == "more":
            await self.more(c, nonce)
        elif action == "refine":
            await self.refine(c, nonce, kind=data.get("r"))
        elif action == "results":
            await self.results(c, nonce)
        elif action == "suggest":
            await self.d.reply(c.ev, [line_flex.plain(texts.SUGGEST_HOW)])
        elif action == "poll":
            await self.start_poll(c, plan)
        elif action == "pollres":
            await self.poll_results(c, nonce, close=False)
        elif action == "pollclose":
            await self.poll_results(c, nonce, close=True)
        elif action == "pollplan":
            await self.plan_from_poll(c, group, plan, nonce)

    async def activate(self, c: Ctx) -> None:
        is_admin = bool(self.s.line_admin_user_id) and c.user_id == self.s.line_admin_user_id
        user = await self.d.store.get("users", c.uhash)
        if not is_admin and not (user and user.get("verified")):
            await self.d.reply(c.ev, [line_flex.plain(texts.NOT_VERIFIED)])
            return
        now, s = c.now, self.s

        def fn(docs):
            group, user = docs
            if not group or group.get("state") != "pending":
                return [KEEP, KEEP], ("already", group)
            user = dict(user or {"verified": True, "is_admin": True, "groups_activated": 0})
            if not is_admin and user.get("groups_activated", 0) >= s.groups_per_user:
                return [KEEP, KEEP], ("user_limit", group)
            group = dict(self._touch(group, now), state="active", activated_at=now, activated_by=c.uhash,
                         active_until=now + s.group_active_days * DAY)
            user["groups_activated"] = user.get("groups_activated", 0) + 1
            return [group, user], ("ok", group)

        outcome, group = await self.d.store.transact([("groups", c.ghash), ("users", c.uhash)], fn)
        if outcome == "ok":
            await self.d.reply(c.ev, [line_flex.activated(s.plans_per_group - group.get("plans_used", 0),
                                                          self._searches_left(group), _day(group["active_until"]))])
        elif outcome == "user_limit":
            await self.d.reply(c.ev, [line_flex.plain(texts.USER_GROUP_LIMIT)])
        else:
            await self.d.reply(c.ev, [line_flex.plain(texts.ALREADY_ACTIVE)])

    # ---- phase 2–3: gathering and ready check ---------------------------------------------------

    async def _name(self, c: Ctx) -> str:
        try:
            name = await self.d.line.member_name(c.kind, c.chat_id, c.user_id)
        except Exception:
            name = None
        return (name or "メンバー")[:20]

    async def start_plan(self, c: Ctx, group: dict[str, Any], request: str) -> None:
        if self._used_up(group):
            await self.d.store.set("groups", c.ghash, dict(self._touch(group, c.now), state="done"))
            await self.d.reply(c.ev, [line_flex.plain(texts.SEARCHES_USED_UP)])
            await self._leave(c)
            return
        name = await self._name(c)
        station = await self.d.stations.from_text(request) if request else None
        if not station:
            station = (await self.d.store.get("profiles", c.uhash) or {}).get("station")
        hint = date_hint(request) if request else {}
        now, s = c.now, self.s

        def fn(docs):
            group, plan = docs
            if not group or group.get("state") != "active":
                return [KEEP, KEEP], None
            if plan:
                return [KEEP, KEEP], "exists"
            me = {"name": name, "n": 1, "ready": False, "votes": []}
            if station:
                me["station"] = {"name": station["name"], "code": station["code"]}
            plan = {
                "nonce": new_nonce(), "phase": "gathering", "organizer": c.uhash, "organizer_name": name,
                "started_at": now, "participants": {c.uhash: me}, "next_n": 2, "passed": [],
                "held": [{"n": 1, "t": request[:300]}] if request else [], "hint": hint,
                "expire_at": min(group.get("active_until", now + s.group_active_days * DAY),
                                 now + s.group_active_days * DAY),
            }
            return [self._touch(group, now), plan], plan

        plan = await self._txn(c.ghash, fn)
        if plan == "exists":
            await self.d.reply(c.ev, [line_flex.plain(texts.gathering_status([]))])
        elif plan:
            await self.d.reply(c.ev, [line_flex.gathering(plan["nonce"], s.max_participants)])

    async def join(self, c: Ctx, nonce: Optional[str]) -> None:
        name = await self._name(c)
        station = (await self.d.store.get("profiles", c.uhash) or {}).get("station")
        now, limit = c.now, self.s.max_participants

        def fn(docs):
            group, plan = docs
            if not plan or plan["phase"] not in ("gathering", "ready"):
                return [KEEP, KEEP], "closed"
            if nonce and plan["nonce"] != nonce:
                return [KEEP, KEEP], "stale"
            if c.uhash in plan["participants"]:
                return [KEEP, KEEP], "already"
            if len(plan["participants"]) >= limit:
                return [KEEP, KEEP], "full"
            plan = copy.deepcopy(plan)
            me = {"name": name, "n": plan["next_n"], "ready": False, "votes": []}
            if station:
                me["station"] = {"name": station["name"], "code": station["code"]}   # from their profile
            plan["participants"][c.uhash] = me
            plan["next_n"] += 1
            plan["passed"] = [u for u in plan.get("passed", []) if u != c.uhash]
            if _all_have_stations(plan):
                plan["phase"] = "ready"
                for p in plan["participants"].values():
                    p["ready"] = False
                return [self._touch(group, now), plan], ("go" if plan.get("auto_search") else "ready_card", plan)
            plan["phase"] = "gathering"
            return [self._touch(group, now), plan], ("joined", plan)

        outcome = await self._txn(c.ghash, fn)
        outcome, joined_plan = outcome if isinstance(outcome, tuple) else (outcome, None)
        if outcome == "ready_card":
            await self.d.reply(c.ev, [line_flex.ready_check(joined_plan["nonce"], _station_rows(joined_plan),
                                                            hint_text(joined_plan.get("hint")))])
        elif outcome == "go":
            await self.search(c, joined_plan["nonce"])
        elif outcome == "stale":
            await self.d.reply(c.ev, [line_flex.plain(texts.STALE_BUTTON)])
        elif outcome == "full":
            await self.d.reply(c.ev, [line_flex.plain(texts.full(limit))])

    async def pass_plan(self, c: Ctx, nonce: Optional[str]) -> None:
        now = c.now

        def fn(docs):
            group, plan = docs
            if not plan or plan["phase"] not in ("gathering", "ready"):
                return [KEEP, KEEP], (None, None)
            if nonce and plan["nonce"] != nonce:
                return [KEEP, KEEP], ("stale", None)
            plan = copy.deepcopy(plan)
            me = plan["participants"].pop(c.uhash, None)
            was_in = me is not None
            if c.uhash not in plan["passed"]:
                plan["passed"].append(c.uhash)
            if was_in:   # their messages leave with them
                plan["held"] = [h for h in plan["held"] if h["n"] != me["n"]]
            if _all_have_stations(plan) and was_in:
                plan["phase"] = "ready"
                for p in plan["participants"].values():
                    p["ready"] = False
                return [self._touch(group, now), plan], ("ready_card", plan)
            if not _all_have_stations(plan):
                plan["phase"] = "gathering"
            return [self._touch(group, now), plan], (None, plan)

        outcome, plan = await self._txn(c.ghash, fn)
        if outcome == "stale":
            await self.d.reply(c.ev, [line_flex.plain(texts.STALE_BUTTON)])
        elif outcome == "ready_card":
            await self.d.reply(c.ev, [line_flex.ready_check(plan["nonce"], _station_rows(plan), hint_text(plan.get("hint")))])

    async def ready(self, c: Ctx, nonce: Optional[str]) -> None:
        def fn(docs):
            group, plan = docs
            if not plan or plan["nonce"] != nonce:
                return [KEEP, KEEP], "stale"
            if plan["phase"] != "ready" or c.uhash not in plan["participants"]:
                return [KEEP, KEEP], None
            plan = copy.deepcopy(plan)
            plan["participants"][c.uhash]["ready"] = True
            all_ready = all(p["ready"] for p in plan["participants"].values())
            return [KEEP, plan], "go" if all_ready else None

        outcome = await self._txn(c.ghash, fn)
        if outcome == "stale":
            await self.d.reply(c.ev, [line_flex.plain(texts.STALE_BUTTON)])
        elif outcome == "go":
            await self.search(c, nonce)

    async def force(self, c: Ctx, nonce: Optional[str], plan: Optional[dict[str, Any]]) -> None:
        if not plan or plan["nonce"] != nonce or plan["phase"] not in ("gathering", "ready", "searching"):
            await self.d.reply(c.ev, [line_flex.plain(texts.STALE_BUTTON)])
            return
        if c.uhash != plan["organizer"]:
            await self.d.reply(c.ev, [line_flex.plain(texts.organizer_only(plan["organizer_name"]))])
            return
        if sum(1 for p in plan["participants"].values() if p.get("station")) < 2:
            await self.d.reply(c.ev, [line_flex.plain(texts.NEED_TWO)])
            return
        await self.search(c, nonce)

    # ---- phase 4: search ------------------------------------------------------------------------

    async def _revert_search(self, c: Ctx, nonce: str, back_to: str) -> None:
        def fn(docs):
            group, plan = docs
            if not plan or plan["nonce"] != nonce or plan["phase"] != "searching":
                return [KEEP, KEEP], None
            plan = copy.deepcopy(plan)
            plan["phase"] = back_to
            group = dict(group, searches_used=max(0, group.get("searches_used", 0) - 1))
            return [group, plan], None

        await self._txn(c.ghash, fn)

    async def _claim_search(self, c: Ctx, nonce: str, from_phases: tuple[str, ...]):
        now, limit = c.now, self.s.searches_per_group

        def fn(docs):
            group, plan = docs
            if not plan or plan["nonce"] != nonce:
                return [KEEP, KEEP], ("stale", None, None)
            stale_search = plan["phase"] == "searching" and now - plan.get("search_started_at", 0) > STALE_SEARCH_SECONDS
            if plan["phase"] not in from_phases and not stale_search:
                return [KEEP, KEEP], ("busy", None, None)
            if group.get("searches_used", 0) >= limit:
                return [KEEP, KEEP], ("limit", None, None)
            plan = copy.deepcopy(plan)
            plan["phase"] = "searching"
            plan["search_started_at"] = now
            group = dict(self._touch(group, now), searches_used=group.get("searches_used", 0) + 1)
            return [group, plan], ("ok", group, plan)

        return await self._txn(c.ghash, fn)

    async def _search_refused(self, c: Ctx, outcome: str) -> None:
        message = {"stale": texts.STALE_BUTTON, "busy": texts.SEARCHING, "limit": texts.SEARCHES_USED_UP}[outcome]
        await self.d.reply(c.ev, [line_flex.plain(message)])

    async def search(self, c: Ctx, nonce: str) -> None:
        if not await self.d.usage.take("searches"):
            await self.d.reply(c.ev, [line_flex.plain(texts.DAILY_LIMIT)])
            return
        outcome, group, snap = await self._claim_search(c, nonce, ("gathering", "ready"))
        if outcome != "ok":
            await self._search_refused(c, outcome)
            return
        try:
            people = [p for p in _people(snap) if p.get("station")]
            details = await schedule_agent.extract_details(
                self.d.llm, [(h["n"], h["t"]) for h in snap["held"]], snap.get("hint"))
            hub = await find_hub(self.d.ekispert, [p["station"] for p in people])
            if not hub:
                raise SearchProblem(texts.NO_HUB)
            station = await self.d.stations.by_code(hub["code"])
            if not station or station.get("lat") is None:
                raise SearchProblem(texts.NO_HUB)
            pax = len(snap["participants"])
            picks, taste = await self._choose_picks(snap, station, details, pax, set())
            if not picks:
                raise SearchProblem(texts.NO_VENUES)
        except SearchProblem as e:
            await self._revert_search(c, nonce, "ready" if _all_have_stations(snap) else "gathering")
            await self.d.reply(c.ev, [line_flex.plain(e.message)])
            return
        except Exception:
            log.exception("search failed")
            await self._revert_search(c, nonce, "ready" if _all_have_stations(snap) else "gathering")
            await self.d.reply(c.ev, [line_flex.plain(texts.SEARCH_FAILED)])
            return

        hub_rows = [(p["name"], p["station"]["name"], hub["minutes"].get(p["station"]["name"], 0)) for p in people]

        def finish(docs):
            group, plan = docs
            if not plan or plan["nonce"] != nonce or plan["phase"] != "searching":
                return [KEEP, KEEP], (None, None)
            plan = copy.deepcopy(plan)
            plan.update(phase="voting", details=details, picks=picks, page=0, held=[], suggestions=[],
                        hub={"name": hub["name"], "code": hub["code"], "spread": hub["spread"],
                             "lat": station.get("lat"), "lng": station.get("lng")})
            for p in plan["participants"].values():
                p.pop("station", None)   # no longer needed once the hub is known
                p["ready"] = False
                p["votes"] = []
            return [self._touch(group, c.now), plan], (group, plan)

        group, plan = await self._txn(c.ghash, finish)
        if plan is None:
            return
        carousel = await self._carousel(plan, self._searches_left(group))
        summary = " / ".join(x for x in (schedule_agent.details_text(details), _taste_text(taste)) if x)
        await self.d.reply(c.ev, [line_flex.hub_card(hub, hub_rows, summary), carousel])

    async def _choose_picks(self, plan: dict[str, Any], station: dict[str, Any], details: dict[str, Any],
                            pax: int, exclude: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """With profiles: places covering everyone's tastes. Without: the classic search."""
        people = [{"name": p["name"], "profile": await self.d.store.get("profiles", u)}
                  for u, p in plan["participants"].items()]
        taste = group_taste(people)
        if taste["has_profiles"]:
            picks = await group_picks(self.d.hotpepper, station, details, pax, taste, exclude=exclude,
                                      featured=self.d.featured, timeout=self.d.timeout)
        else:
            picks = await spot_agent.shortlist(self.d.llm, self.d.hotpepper, station, details, pax, exclude=exclude,
                                               featured=self.d.featured, timeout=self.d.timeout)
        return picks, taste

    # ---- phase 5: vote, more, refine ------------------------------------------------------------

    async def _carousel(self, plan: dict[str, Any], searches_left: int) -> dict:
        page = plan["page"]
        chunk = plan["picks"][page * PAGE:(page + 1) * PAGE]
        shops = await self.d.shops([p["id"] for p in chunk])
        chunk = [p for p in chunk if p["id"] in shops]
        labels = [LABELS[page * PAGE + i] for i in range(len(chunk))]
        pages = math.ceil(len(plan["picks"]) / PAGE)
        shown = [shops[p["id"]] for p in chunk]
        return line_flex.venues_carousel(plan["nonce"], shown, chunk, labels, pages - page - 1, searches_left,
                                         [self.d.featured(s) for s in shown], leader=await self._leader(plan),
                                         can_suggest=len(plan.get("suggestions", [])) < MAX_SUGGESTIONS)

    async def _shop_map(self, plan: dict[str, Any], ids: list[str]) -> dict[str, dict[str, Any]]:
        """Shop details for picks (HotPepper / Time Out) and suggestions (stored in the plan)."""
        own = {sg["id"]: sg["shop"] for sg in plan.get("suggestions", []) if sg.get("shop")}
        found = await self.d.shops([i for i in ids if i not in own])
        found.update({i: own[i] for i in ids if i in own})
        return found

    async def _leader(self, plan: dict[str, Any]) -> Optional[str]:
        counts = _all_votes(plan)
        if not counts:
            return None
        top, n = counts.most_common(1)[0]
        shop = (await self._shop_map(plan, [top])).get(top)
        return f"{_labels(plan).get(top, '')} {shop['name'][:14] if shop else ''}（{n}票）".strip()

    async def more(self, c: Ctx, nonce: Optional[str]) -> None:
        def fn(docs):
            group, plan = docs
            if not plan or plan["nonce"] != nonce or plan["phase"] != "voting":
                return [KEEP, KEEP], ("stale", None, None)
            if (plan["page"] + 1) * PAGE >= len(plan["picks"]):
                return [KEEP, KEEP], ("none", None, None)
            plan = copy.deepcopy(plan)
            plan["page"] += 1
            return [KEEP, plan], ("ok", group, plan)

        outcome, group, plan = await self._txn(c.ghash, fn)
        if outcome == "ok":
            await self.d.reply(c.ev, [await self._carousel(plan, self._searches_left(group))])
        else:
            await self.d.reply(c.ev, [line_flex.plain(texts.NO_MORE if outcome == "none" else texts.STALE_BUTTON)])

    async def refine(self, c: Ctx, nonce: Optional[str], kind: Optional[str] = None,
                     request: Optional[str] = None) -> None:
        if not await self.d.usage.take("searches"):
            await self.d.reply(c.ev, [line_flex.plain(texts.DAILY_LIMIT)])
            return
        outcome, group, snap = await self._claim_search(c, nonce, ("voting",))
        if outcome != "ok":
            await self._search_refused(c, outcome)
            return
        try:
            details = dict(snap.get("details") or {})
            shown = [p["id"] for p in snap["picks"][:(snap["page"] + 1) * PAGE]]
            if kind == "cheaper":
                shown_shops = await self.d.shops(shown)
                details["budget"] = spot_agent.cheaper_budget(list(shown_shops.values()), details.get("budget"))
                details["preferences"] = (details.get("preferences") or []) + ["安め"]
            elif kind == "private":
                details["private_room"] = True
                details["preferences"] = (details.get("preferences") or []) + ["個室"]
            elif kind == "near":
                details["near"] = True
                details["preferences"] = (details.get("preferences") or []) + ["駅近"]
            elif request:
                details = await schedule_agent.refine_details(self.d.llm, details, request)
            station = await self.d.stations.by_code(snap["hub"]["code"])
            picks, _ = await self._choose_picks(snap, station, details, len(snap["participants"]), set(shown))
            if not picks:
                raise SearchProblem(texts.NO_VENUES)
        except SearchProblem as e:
            await self._revert_search(c, nonce, "voting")
            await self.d.reply(c.ev, [line_flex.plain(e.message)])
            return
        except Exception:
            log.exception("refine failed")
            await self._revert_search(c, nonce, "voting")
            await self.d.reply(c.ev, [line_flex.plain(texts.SEARCH_FAILED)])
            return

        def finish(docs):
            group, plan = docs
            if not plan or plan["nonce"] != nonce or plan["phase"] != "searching":
                return [KEEP, KEEP], (None, None)
            plan = copy.deepcopy(plan)
            plan.update(phase="voting", details=details, picks=picks, page=0)
            for p in plan["participants"].values():
                p["votes"] = []
            return [self._touch(group, c.now), plan], (group, plan)

        group, plan = await self._txn(c.ghash, finish)
        if plan is None:
            return
        summary = "・".join((details.get("preferences") or [])[-3:])
        await self.d.reply(c.ev, [line_flex.plain(texts.refined(summary)),
                                  await self._carousel(plan, self._searches_left(group))])

    def _winner(self, plan: dict[str, Any], forced: bool) -> Optional[str]:
        """Approval voting: everyone can approve several places.
        Decided when one place is approved by everyone, when everyone has voted (most approvals wins),
        or when the organizer closes the vote. Ties go to the organizer's choice, then the earlier card."""
        people = plan["participants"]
        counts = _all_votes(plan)
        order = [p["id"] for p in plan["picks"]] + [sg["id"] for sg in plan.get("suggestions", [])]
        everyone = [shop for shop, n in counts.items() if n == len(people)]
        if everyone:
            return min(everyone, key=lambda s: order.index(s) if s in order else 99)
        all_voted = bool(people) and all(p.get("votes") for p in people.values())
        if not (forced or all_voted):
            return None
        if not counts:
            return order[plan["page"] * PAGE] if forced and order else None
        best = max(counts.values())
        tied = [s for s, n in counts.items() if n == best]
        organizer_votes = people.get(plan["organizer"], {}).get("votes", [])
        mine = [s for s in tied if s in organizer_votes]
        pool = mine or tied
        return min(pool, key=lambda s: order.index(s) if s in order else 99)

    def _result_rows(self, plan: dict[str, Any], shops: dict[str, dict[str, Any]]) -> list[tuple[str, int]]:
        labels = _labels(plan)
        counts = _all_votes(plan)
        return [(f"{labels.get(s, '')} {shops[s]['name'] if s in shops else ''}".strip(), n)
                for s, n in counts.most_common()]

    async def results(self, c: Ctx, nonce: Optional[str]) -> None:
        plan = await self.d.store.get("plans", c.ghash)
        if not plan or plan["nonce"] != nonce or plan["phase"] != "voting":
            await self.d.reply(c.ev, [line_flex.plain(texts.STALE_BUTTON)])
            return
        counts = _all_votes(plan)
        shops = await self._shop_map(plan, list(counts))
        people = plan["participants"]
        missing = [p["name"] for p in people.values() if not p.get("votes")]
        leader = await self._leader(plan)
        await self.d.reply(c.ev, [line_flex.results_card(
            self._result_rows(plan, shops), len(people) - len(missing), len(people), missing,
            f"いまの1位：{leader}" if leader else "まだ投票がありません", nonce)])

    async def vote(self, c: Ctx, nonce: Optional[str], shop_id: Optional[str], forced: bool) -> None:
        plan_now = await self.d.store.get("plans", c.ghash)
        if not plan_now or plan_now["nonce"] != nonce or plan_now["phase"] != "voting":
            await self.d.reply(c.ev, [line_flex.plain(texts.STALE_BUTTON)])
            return
        if forced and c.uhash != plan_now["organizer"]:
            await self.d.reply(c.ev, [line_flex.plain(texts.organizer_only(plan_now["organizer_name"]))])
            return
        shown = [p["id"] for p in plan_now["picks"][:(plan_now["page"] + 1) * PAGE]] + \
            [sg["id"] for sg in plan_now.get("suggestions", [])]
        shops = await self._shop_map(plan_now, shown)
        now = c.now

        def fn(docs):
            group, plan = docs
            if not plan or plan["nonce"] != nonce or plan["phase"] != "voting":
                return [KEEP, KEEP], ("stale", None, None)
            plan = copy.deepcopy(plan)
            if not forced:
                if c.uhash not in plan["participants"]:
                    return [KEEP, KEEP], ("not_participant", None, None)
                if shop_id not in shown:
                    return [KEEP, KEEP], ("stale", None, None)
                mine = plan["participants"][c.uhash].setdefault("votes", [])
                if shop_id in mine:
                    mine.remove(shop_id)      # tapping again takes the vote back
                else:
                    mine.append(shop_id)
            winner = self._winner(plan, forced)
            if not winner:
                return [KEEP, plan], ("noted", None, None)
            pick = next((p for p in plan["picks"] if p["id"] == winner), None) or \
                next(sg for sg in plan.get("suggestions", []) if sg["id"] == winner)
            decision = {"shop_id": winner, "pick": pick, "when": _when(plan),
                        "day": (plan.get("details") or {}).get("day") or (plan.get("hint") or {}).get("day"),
                        "time": (plan.get("details") or {}).get("time") or (plan.get("hint") or {}).get("time"),
                        "pax": len(plan["participants"]), "organizer_name": plan["organizer_name"],
                        "hub_name": plan["hub"]["name"], "rows": self._result_rows(plan, shops),
                        "voters": sum(1 for p in plan["participants"].values() if p.get("votes")),
                        "label": _labels(plan).get(winner, ""), "shop": pick.get("shop")}
            group = dict(self._touch(group, now), state="done",
                         plans_used=group.get("plans_used", 0) + 1, decided_at=now)
            return [group, None], ("decided", decision, plan)   # the plan (names, votes) is deleted here

        outcome, decision, _ = await self._txn(c.ghash, fn)
        if outcome == "stale":
            await self.d.reply(c.ev, [line_flex.plain(texts.STALE_BUTTON)])
        elif outcome == "not_participant":
            await self.d.reply(c.ev, [line_flex.plain(texts.NOT_PARTICIPANT)])
        elif outcome == "decided":
            await self._announce(c, decision, shops)

    # ---- suggestions ---------------------------------------------------------------------------

    async def suggest(self, c: Ctx, plan: dict[str, Any], request: str) -> None:
        if c.uhash not in plan["participants"]:
            await self.d.reply(c.ev, [line_flex.plain(texts.NOT_PARTICIPANT)])
            return
        if len(plan.get("suggestions", [])) >= MAX_SUGGESTIONS:
            await self.d.reply(c.ev, [line_flex.plain(texts.SUGGEST_FULL)])
            return
        try:
            shop = await resolve_suggestion(self.d, request, plan["hub"])
        except SuggestionError as e:
            await self.d.reply(c.ev, [line_flex.plain(e.message)])
            return
        except Exception:
            log.exception("suggestion failed")
            await self.d.reply(c.ev, [line_flex.plain(texts.SUGGEST_FAILED)])
            return
        name = plan["participants"][c.uhash]["name"]
        walk = spot_agent.walk_minutes(shop, plan["hub"]) if plan["hub"].get("lat") else None
        nonce = plan["nonce"]

        def fn(docs):
            group, current = docs
            if not current or current["nonce"] != nonce or current["phase"] != "voting":
                return [KEEP, KEEP], ("stale", None)
            current = copy.deepcopy(current)
            suggestions = current.setdefault("suggestions", [])
            if any(sg["id"] == shop["id"] for sg in suggestions) or any(p["id"] == shop["id"] for p in current["picks"]):
                return [KEEP, KEEP], ("dup", None)
            if len(suggestions) >= MAX_SUGGESTIONS:
                return [KEEP, KEEP], ("full", None)
            entry = {"id": shop["id"], "suggested_by": name, "walk_min": walk, "reason": f"{name}さんの提案"}
            if not shop["id"].startswith(("J", "TO")):
                entry["shop"] = shop          # Places results can't be looked up again, so keep them
            suggestions.append(entry)
            return [KEEP, current], ("ok", (current, entry))

        outcome, result = await self._txn(c.ghash, fn)
        if outcome == "ok":
            current, entry = result
            await self.d.reply(c.ev, [line_flex.suggestion_card(nonce, _labels(current)[entry["id"]], shop, entry)])
        elif outcome == "dup":
            await self.d.reply(c.ev, [line_flex.plain(texts.SUGGEST_DUP)])
        elif outcome == "full":
            await self.d.reply(c.ev, [line_flex.plain(texts.SUGGEST_FULL)])
        else:
            await self.d.reply(c.ev, [line_flex.plain(texts.STALE_BUTTON)])

    # ---- date poll -----------------------------------------------------------------------------

    def _poll_token(self, ghash: str, nonce: str) -> str:
        return self.d.ids.sign({"k": "poll", "g": ghash, "n": nonce}, polls.POLL_DAYS * DAY)

    def _liff_url(self, path: str, token: str) -> str:
        return f"https://liff.line.me/{self.s.liff_id}/{path}?t={token}"

    async def start_poll(self, c: Ctx, plan: Optional[dict[str, Any]]) -> None:
        if plan is not None:
            await self.d.reply(c.ev, [line_flex.plain(texts.POLL_PLAN_RUNNING)])
            return
        if not self.s.liff_id:
            await self.d.reply(c.ev, [line_flex.plain(texts.POLL_UNAVAILABLE)])
            return
        name = await self._name(c)
        poll = await polls.start(self.d.store, c.ghash, c.uhash, name, c.now)
        token = self._poll_token(c.ghash, poll["nonce"])
        if poll["status"] == "open":
            await self.d.reply(c.ev, [self._poll_card(poll, token)])
        else:
            await self.d.reply(c.ev, [line_flex.poll_start(self._liff_url("calendar", token), poll["organizer_name"])])

    def _poll_card(self, poll: dict[str, Any], token: str) -> dict:
        return line_flex.poll_card(poll["nonce"], [polls.date_label(d) for d in poll["dates"]],
                                   polls.slot_label(poll.get("slot")), self._liff_url("poll", token),
                                   len(poll.get("answers", {})))

    async def announce_poll(self, c: Ctx) -> None:
        """The calendar page posted 「日程調整を作りました」 as the organizer: reply with the poll card."""
        def fn(docs):
            poll = docs[0]
            if not poll or poll.get("status") != "open" or poll.get("announced"):
                return [KEEP], None
            return [dict(poll, announced=True)], poll

        poll = await self.d.store.transact([("polls", c.ghash)], fn)
        if poll:
            await self.d.reply(c.ev, [self._poll_card(poll, self._poll_token(c.ghash, poll["nonce"]))])

    async def poll_results(self, c: Ctx, nonce: Optional[str], close: bool) -> None:
        poll = await self.d.store.get("polls", c.ghash)
        if not poll or poll.get("nonce") != nonce or poll.get("status") not in ("open", "closed"):
            await self.d.reply(c.ev, [line_flex.plain(texts.STALE_BUTTON)])
            return
        if close and c.uhash != poll["organizer"]:
            await self.d.reply(c.ev, [line_flex.plain(texts.organizer_only(poll["organizer_name"]))])
            return
        ranked = polls.tally(poll)
        best = ranked[0][0] if ranked and (ranked[0][1] + ranked[0][2]) > 0 else None
        if close:
            if not best:
                await self.d.reply(c.ev, [line_flex.plain(texts.POLL_NO_ANSWERS)])
                return
            await self.d.store.set("polls", c.ghash, dict(poll, status="closed", best=best))
        yes, maybe = polls.people_for(poll, best) if best else ([], [])
        runner = next((polls.date_label(d) for d, o, t, x in ranked[1:2] if o + t > 0), None)
        await self.d.reply(c.ev, [line_flex.poll_result(
            nonce, polls.date_label(best) if best else None, [n for _, n in yes], [n for _, n in maybe], runner,
            [(polls.date_label(d), o, t, x) for d, o, t, x in ranked], closed=close)])

    async def plan_from_poll(self, c: Ctx, group: dict[str, Any], plan: Optional[dict[str, Any]],
                             nonce: Optional[str]) -> None:
        poll = await self.d.store.get("polls", c.ghash)
        if not poll or poll.get("nonce") != nonce or poll.get("status") != "closed" or not poll.get("best"):
            await self.d.reply(c.ev, [line_flex.plain(texts.STALE_BUTTON)])
            return
        if plan is not None:
            await self.d.reply(c.ev, [line_flex.plain(texts.POLL_PLAN_RUNNING)])
            return
        if self._used_up(group):
            await self.d.reply(c.ev, [line_flex.plain(texts.SEARCHES_USED_UP)])
            return
        yes, maybe = polls.people_for(poll, poll["best"])
        people = (yes + maybe)[:self.s.max_participants]
        day = dt.date.fromisoformat(poll["best"])
        hint = {"day": f"{day.month}/{day.day}"}
        slot = poll.get("slot")
        if slot in ("lunch", "dinner"):
            hint["meal"] = slot
        elif slot:
            hint["time"] = slot
        participants = {}
        for n, (u, name) in enumerate(people, start=1):
            me = {"name": name, "n": n, "ready": False, "votes": []}
            st = (await self.d.store.get("profiles", u) or {}).get("station")
            if st:
                me["station"] = {"name": st["name"], "code": st["code"]}
            participants[u] = me
        organizer = c.uhash if c.uhash in participants else (people[0][0] if people else c.uhash)
        now, s = c.now, self.s

        def fn(docs):
            grp, existing = docs
            if existing or not grp or grp.get("state") != "active":
                return [KEEP, KEEP], None
            new_plan = {
                "nonce": new_nonce(), "phase": "gathering", "organizer": organizer,
                "organizer_name": participants.get(organizer, {}).get("name", "幹事"), "started_at": now,
                "participants": participants, "next_n": len(participants) + 1, "passed": [], "held": [],
                "hint": hint, "auto_search": True,
                "expire_at": min(grp.get("active_until", now + s.group_active_days * DAY), now + s.group_active_days * DAY),
            }
            return [self._touch(grp, now), new_plan], new_plan

        new_plan = await self._txn(c.ghash, fn)
        if not new_plan:
            await self.d.reply(c.ev, [line_flex.plain(texts.STALE_BUTTON)])
            return
        await self.d.store.delete("polls", c.ghash)     # the answers have done their job
        if _all_have_stations(new_plan):
            await self.search(c, new_plan["nonce"])
            return
        missing = [p["name"] for p in _people(new_plan) if not p.get("station")]
        await self.d.reply(c.ev, [line_flex.gathering(new_plan["nonce"], s.max_participants),
                                  line_flex.plain(texts.need_stations(missing))])

    # ---- phase 6: decided -----------------------------------------------------------------------

    async def _announce(self, c: Ctx, decision: dict[str, Any], shops: dict[str, dict[str, Any]]) -> None:
        shop = shops.get(decision["shop_id"]) or decision.get("shop")
        if shop is None:
            shop = (await self.d.shops([decision["shop_id"]])).get(decision["shop_id"])
        messages: list[dict] = []
        if decision.get("rows"):
            messages.append(line_flex.results_card(decision["rows"], decision["voters"], decision["pax"], [],
                                                   f"{decision['label']} {shop['name'] if shop else ''} に決まりました".strip()))
        if shop:
            known = shop.get("telephone") or (self.d.featured(shop) or {}).get("telephone")
            phone = known if shop.get("source") in ("timeout", "places") else (
                await self.d.places.phone_number(shop["name"], shop.get("address") or "", shop.get("lat"), shop.get("lng"))
                or known)
            agent_url = await self._agent_link(decision, shop)
            script = voice_agent.call_script(shop["name"], decision.get("day"), decision.get("time"),
                                             decision["pax"], decision["organizer_name"])
            messages += [line_flex.decision_card(shop, decision["when"], decision["pax"],
                                                 decision["pick"].get("walk_min"), decision["hub_name"], agent_url),
                         line_flex.script_card(script, phone, shop.get("url"))]
        messages.append(line_flex.plain(texts.GOODBYE))
        await self.d.reply(c.ev, messages)
        await self._leave(c)

    async def _agent_link(self, decision: dict[str, Any], shop: dict[str, Any]) -> Optional[str]:
        if self.s.form_agent_mode == "off":
            return None
        run_id = secrets.token_hex(8)
        now = self.d.clock()
        await self.d.store.set("agent_runs", run_id, {
            "status": "ready", "created_at": now, "expire_at": now + DAY, "steps": [],
            "shop": {"id": shop["id"], "name": shop["name"], "url": shop.get("url")},
            "day": decision.get("day"), "time": decision.get("time"), "pax": decision["pax"],
            "name": decision["organizer_name"],
        })
        token = self.d.ids.sign({"r": run_id}, DAY)
        return f"{self.d.base_url()}/agent/{token}"


def _taste_text(taste: dict[str, Any]) -> str:
    if not taste.get("has_profiles"):
        return ""
    liked = "・".join(f"{k['label']}♡{len(k['likers'])}" for k in taste["kinds"][:3])
    from services.taste import label as taste_label
    dropped = "・".join(taste_label(d) for d in taste.get("dropped", [])[:3])
    return "みんなの好み " + liked + (f"（のぞく：{dropped}）" if dropped else "")
