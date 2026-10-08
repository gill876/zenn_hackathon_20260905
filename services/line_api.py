"""
LINE Messaging API client.

Only what the bot needs: verify webhook signatures, reply, leave a group, look up a member's display name,
and set the webhook URL. The bot never pushes on its own; every message it sends is a reply, which LINE
does not count against the monthly message allowance.
"""

import base64
import hashlib
import hmac
import logging
from typing import Any, Optional, Protocol

import httpx

log = logging.getLogger("line_api")

API = "https://api.line.me"


def verify_signature(channel_secret: str, body: bytes, signature: Optional[str]) -> bool:
    if not channel_secret or not signature:
        return False
    digest = hmac.new(channel_secret.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


class LineApi(Protocol):
    async def reply(self, reply_token: str, messages: list[dict[str, Any]]) -> bool: ...
    async def leave(self, chat_kind: str, chat_id: str) -> bool: ...
    async def member_name(self, chat_kind: str, chat_id: str, user_id: str) -> Optional[str]: ...
    async def profile_name(self, user_id: str) -> Optional[str]: ...


class HttpLineApi:
    def __init__(self, access_token: str, timeout: float = 10.0):
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._client = httpx.AsyncClient(base_url=API, timeout=timeout, headers=self._headers)

    async def _post(self, path: str, json: Optional[dict] = None) -> httpx.Response:
        resp = await self._client.post(path, json=json if json is not None else {})
        if resp.status_code >= 300:
            log.warning("LINE %s -> %s %s", path, resp.status_code, resp.text[:500])
        return resp

    async def reply(self, reply_token: str, messages: list[dict[str, Any]]) -> bool:
        if not messages:
            return True
        resp = await self._post("/v2/bot/message/reply", {"replyToken": reply_token, "messages": messages[:5]})
        return resp.status_code < 300

    async def validate_reply(self, messages: list[dict[str, Any]]) -> tuple[bool, str]:
        """Ask LINE whether these message objects are valid, without sending anything."""
        resp = await self._post("/v2/bot/message/validate/reply", {"messages": messages[:5]})
        return resp.status_code < 300, resp.text

    async def leave(self, chat_kind: str, chat_id: str) -> bool:
        path = f"/v2/bot/group/{chat_id}/leave" if chat_kind == "group" else f"/v2/bot/room/{chat_id}/leave"
        resp = await self._post(path)
        return resp.status_code < 300

    async def member_name(self, chat_kind: str, chat_id: str, user_id: str) -> Optional[str]:
        kind = "group" if chat_kind == "group" else "room"
        resp = await self._client.get(f"/v2/bot/{kind}/{chat_id}/member/{user_id}")
        if resp.status_code >= 300:
            return None
        return resp.json().get("displayName")

    async def profile_name(self, user_id: str) -> Optional[str]:
        resp = await self._client.get(f"/v2/bot/profile/{user_id}")
        if resp.status_code >= 300:
            return None
        return resp.json().get("displayName")

    async def bot_info(self) -> dict[str, Any]:
        resp = await self._client.get("/v2/bot/info")
        resp.raise_for_status()
        return resp.json()

    async def set_webhook(self, url: str) -> bool:
        resp = await self._client.put("/v2/bot/channel/webhook/endpoint", json={"endpoint": url})
        if resp.status_code >= 300:
            log.warning("set webhook -> %s %s", resp.status_code, resp.text[:300])
        return resp.status_code < 300

    async def test_webhook(self) -> dict[str, Any]:
        resp = await self._post("/v2/bot/channel/webhook/test")
        return resp.json() if resp.content else {}


class RecordingLineApi:
    """Stands in for LINE in tests and local runs: remembers every call instead of sending it."""

    def __init__(self, names: Optional[dict[str, str]] = None):
        self.replies: list[dict[str, Any]] = []
        self.left: list[tuple[str, str]] = []
        self.names = names or {}

    async def reply(self, reply_token: str, messages: list[dict[str, Any]]) -> bool:
        assert len(messages) <= 5, "LINE accepts at most 5 messages per reply"
        self.replies.append({"token": reply_token, "messages": messages})
        return True

    async def leave(self, chat_kind: str, chat_id: str) -> bool:
        self.left.append((chat_kind, chat_id))
        return True

    async def member_name(self, chat_kind: str, chat_id: str, user_id: str) -> Optional[str]:
        return self.names.get(user_id)

    async def profile_name(self, user_id: str) -> Optional[str]:
        return self.names.get(user_id)

    def last_messages(self) -> list[dict[str, Any]]:
        return self.replies[-1]["messages"] if self.replies else []
