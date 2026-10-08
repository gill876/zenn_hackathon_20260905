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
from bot import texts
from bot.deps import Deps
from bot.text_parse import JOIN_WORDS, PASS_WORDS, date_hint, hint_text, is_trigger_text, merge_hints
from services import line_flex
from services.ids import new_nonce
from services.store import KEEP
from services.usage import JST

log = logging.getLogger("group")

PAGE = 3
LABELS = "ABCDEFGHI"
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
        if plan is None:
            if trigger:
                await self.start_plan(c, group, request)
            return

        phase = plan["phase"]
        stripped = text.strip()
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
            if trigger and request:
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
                outcome = "ready_card"
            elif plan["phase"] == "ready" and hint_text(plan["hint"]) != before:
                outcome = "when"
            return [self._touch(group, c.now), plan], (outcome, plan)

        outcome, plan = await self._txn(c.ghash, fn)
        if outcome == "ready_card":
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
        hint = date_hint(request) if request else {}
        now, s = c.now, self.s

        def fn(docs):
            group, plan = docs
            if not group or group.get("state") != "active":
                return [KEEP, KEEP], None
            if plan:
                return [KEEP, KEEP], "exists"
            me = {"name": name, "n": 1, "ready": False, "vote": None}
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
            plan["participants"][c.uhash] = {"name": name, "n": plan["next_n"], "ready": False, "vote": None}
            plan["next_n"] += 1
            plan["passed"] = [u for u in plan.get("passed", []) if u != c.uhash]
            plan["phase"] = "gathering"   # the newcomer has no station yet
            return [self._touch(group, now), plan], "joined"

        outcome = await self._txn(c.ghash, fn)
        if outcome == "stale":
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
            picks = await spot_agent.shortlist(self.d.llm, self.d.hotpepper, station, details, pax)
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
            plan.update(phase="voting", details=details, picks=picks, page=0, held=[],
                        hub={"name": hub["name"], "code": hub["code"], "spread": hub["spread"]})
            for p in plan["participants"].values():
                p.pop("station", None)   # no longer needed once the hub is known
                p["ready"] = False
                p["vote"] = None
            return [self._touch(group, c.now), plan], (group, plan)

        group, plan = await self._txn(c.ghash, finish)
        if plan is None:
            return
        carousel = await self._carousel(plan, self._searches_left(group))
        await self.d.reply(c.ev, [line_flex.hub_card(hub, hub_rows, schedule_agent.details_text(details)), carousel])

    # ---- phase 5: vote, more, refine ------------------------------------------------------------

    async def _carousel(self, plan: dict[str, Any], searches_left: int) -> dict:
        page = plan["page"]
        chunk = plan["picks"][page * PAGE:(page + 1) * PAGE]
        shops = await self.d.hotpepper.shops_by_ids([p["id"] for p in chunk])
        chunk = [p for p in chunk if p["id"] in shops]
        labels = [LABELS[page * PAGE + i] for i in range(len(chunk))]
        pages = math.ceil(len(plan["picks"]) / PAGE)
        return line_flex.venues_carousel(plan["nonce"], [shops[p["id"]] for p in chunk], chunk, labels,
                                         pages - page - 1, searches_left)

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
                shown_shops = await self.d.hotpepper.shops_by_ids(shown)
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
            picks = await spot_agent.shortlist(self.d.llm, self.d.hotpepper, station, details,
                                               len(snap["participants"]), exclude=set(shown))
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
                p["vote"] = None
            return [self._touch(group, c.now), plan], (group, plan)

        group, plan = await self._txn(c.ghash, finish)
        if plan is None:
            return
        summary = "・".join((details.get("preferences") or [])[-3:])
        await self.d.reply(c.ev, [line_flex.plain(texts.refined(summary)),
                                  await self._carousel(plan, self._searches_left(group))])

    def _winner(self, plan: dict[str, Any], forced: bool) -> Optional[str]:
        people = plan["participants"]
        votes = [p["vote"] for p in people.values() if p.get("vote")]
        counts = Counter(votes)
        for shop_id, n in counts.items():
            if n * 2 > len(people):
                return shop_id
        if not (forced or (people and len(votes) == len(people))):
            return None
        order = [p["id"] for p in plan["picks"]]
        if not counts:
            return order[plan["page"] * PAGE] if forced and order else None
        best = max(counts.values())
        tied = [s for s, n in counts.items() if n == best]
        organizer_vote = people.get(plan["organizer"], {}).get("vote")
        if organizer_vote in tied:
            return organizer_vote
        return min(tied, key=lambda s: order.index(s) if s in order else 99)

    async def vote(self, c: Ctx, nonce: Optional[str], shop_id: Optional[str], forced: bool) -> None:
        plan_now = await self.d.store.get("plans", c.ghash)
        if not plan_now or plan_now["nonce"] != nonce or plan_now["phase"] != "voting":
            await self.d.reply(c.ev, [line_flex.plain(texts.STALE_BUTTON)])
            return
        if forced and c.uhash != plan_now["organizer"]:
            await self.d.reply(c.ev, [line_flex.plain(texts.organizer_only(plan_now["organizer_name"]))])
            return
        shown = [p["id"] for p in plan_now["picks"][:(plan_now["page"] + 1) * PAGE]]
        shops = await self.d.hotpepper.shops_by_ids(shown)
        now, s = c.now, self.s

        def fn(docs):
            group, plan = docs
            if not plan or plan["nonce"] != nonce or plan["phase"] != "voting":
                return [KEEP, KEEP], ("stale", None)
            plan = copy.deepcopy(plan)
            if not forced:
                if c.uhash not in plan["participants"]:
                    return [KEEP, KEEP], ("not_participant", None)
                if shop_id not in shown:
                    return [KEEP, KEEP], ("stale", None)
                plan["participants"][c.uhash]["vote"] = shop_id
            winner = self._winner(plan, forced)
            if not winner:
                return [KEEP, plan], ("noted", None)
            pick = next(p for p in plan["picks"] if p["id"] == winner)
            decision = {"shop_id": winner, "pick": pick, "when": _when(plan),
                        "day": (plan.get("details") or {}).get("day") or (plan.get("hint") or {}).get("day"),
                        "time": (plan.get("details") or {}).get("time") or (plan.get("hint") or {}).get("time"),
                        "pax": len(plan["participants"]), "organizer_name": plan["organizer_name"],
                        "hub_name": plan["hub"]["name"]}
            group = dict(self._touch(group, now), state="done",
                         plans_used=group.get("plans_used", 0) + 1, decided_at=now)
            return [group, None], ("decided", decision)   # the plan (names, votes) is deleted here

        outcome, decision = await self._txn(c.ghash, fn)
        if outcome == "stale":
            await self.d.reply(c.ev, [line_flex.plain(texts.STALE_BUTTON)])
        elif outcome == "not_participant":
            await self.d.reply(c.ev, [line_flex.plain(texts.NOT_PARTICIPANT)])
        elif outcome == "decided":
            await self._announce(c, decision, shops)

    # ---- phase 6: decided -----------------------------------------------------------------------

    async def _announce(self, c: Ctx, decision: dict[str, Any], shops: dict[str, dict[str, Any]]) -> None:
        shop = shops.get(decision["shop_id"])
        if shop is None:
            shop = (await self.d.hotpepper.shops_by_ids([decision["shop_id"]])).get(decision["shop_id"])
        messages: list[dict] = []
        if shop:
            phone = await self.d.places.phone_number(shop["name"], shop.get("address") or "", shop.get("lat"), shop.get("lng"))
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
