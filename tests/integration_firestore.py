"""
Manual integration check: the full group flow against real Firestore, Ekispert and HotPepper, with LINE
replaced by a recorder (nothing is sent). Cleans up its own documents afterwards.

    GOOGLE_CLOUD_QUOTA_PROJECT=asobi-agent-dw9h .venv/bin/python -m tests.integration_firestore asobi-agent-dw9h
"""

import asyncio
import os
import secrets
import sys

os.environ["STORE_BACKEND"] = "firestore"
os.environ["APP_SECRET"] = "integration-" + secrets.token_hex(8)   # test hashes never collide with real ones

from bot.deps import build_deps  # noqa: E402
from bot.handler import handle_event  # noqa: E402
from config import get_settings  # noqa: E402
from services.firestore_store import FirestoreStore  # noqa: E402
from services.line_api import RecordingLineApi  # noqa: E402
from tests.conftest import find_postback, group_message, group_postback, join  # noqa: E402


async def main(project: str) -> None:
    os.environ["GOOGLE_CLOUD_PROJECT"] = project
    settings = get_settings()
    store = FirestoreStore(project=project)
    deps = build_deps(settings, store, RecordingLineApi())
    admin = settings.line_admin_user_id
    group = "Cintegration" + secrets.token_hex(6)
    users = [admin] + [f"U{secrets.token_hex(16)}" for _ in range(2)]

    async def send(ev):
        before = len(deps.line.replies)
        await handle_event(deps, ev)
        new = deps.line.replies[before:]
        return new[0]["messages"] if new else []

    try:
        assert "有効化" in (await send(join(group)))[0]["altText"]
        assert "使えるようになりました" in (await send(group_postback("a=activate", admin, group)))[0]["altText"]
        gathering = await send(group_message("@AsobiAgent 来週土曜19時から飲みたい", admin, group, mention_self=True))
        join_data = find_postback(gathering, "join")
        for u in users[1:]:
            await send(group_postback(join_data, u, group))
        for u, text in zip(users, ["横浜から", "吉祥寺から。焼肉がいい", "柏から向かう"]):
            reply = await send(group_message(text, u, group))
        print("ready card:", reply[0]["altText"])
        ready_data = find_postback(reply, "ready")
        for u in users[1:]:
            assert await send(group_postback(ready_data, u, group)) == []
        results = await send(group_postback(ready_data, admin, group))
        print("search:", results[0]["altText"], "| carousel:", results[1]["contents"]["type"])
        plan = await store.get("plans", deps.ids.chat(group))
        assert plan["phase"] == "voting" and plan["held"] == []
        first = plan["picks"][0]["id"]
        for u in users[:2]:
            out = await send(group_postback(f"a=vote&p={plan['nonce']}&v={first}", u, group))
        print("decision:", [m.get("altText") or m.get("text") for m in out])
        assert await store.get("plans", deps.ids.chat(group)) is None
        g = await store.get("groups", deps.ids.chat(group))
        assert g["state"] == "done" and g["plans_used"] == 1
        print("usage today:", await deps.usage.today())
        print("left groups:", deps.line.left)
        print("INTEGRATION OK")
    finally:
        await store.delete("groups", deps.ids.chat(group))
        await store.delete("plans", deps.ids.chat(group))
        await store.delete("users", deps.ids.user(admin))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
