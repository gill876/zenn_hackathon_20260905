"""
Webhook event dispatch. The server has already checked LINE's signature before anything here runs.

Each event is handled once (LINE may redeliver; webhookEventId is recorded for a day) and in isolation,
so one failing event doesn't stop the rest of the batch.
"""

import logging
from typing import Any

from bot import onboarding
from bot.deps import Deps
from bot.group import GroupBot

log = logging.getLogger("handler")


async def handle_payload(deps: Deps, payload: dict[str, Any]) -> None:
    for ev in payload.get("events", []):
        try:
            await handle_event(deps, ev)
        except Exception:
            log.exception("event %s failed", ev.get("type"))


async def handle_event(deps: Deps, ev: dict[str, Any]) -> None:
    event_id = ev.get("webhookEventId")
    if event_id:
        first_time = await deps.store.create_if_absent("events", event_id, {"expire_at": deps.clock() + 86400})
        if not first_time:
            return
    source = ev.get("source", {})
    kind = source.get("type")
    if kind == "user":
        await onboarding.handle(deps, ev)
    elif kind in ("group", "room"):
        chat_id = source.get("groupId") or source.get("roomId")
        if chat_id:
            await GroupBot(deps).handle(ev, kind, chat_id, source.get("userId"))
