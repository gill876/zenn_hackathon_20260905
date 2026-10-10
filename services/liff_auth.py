"""
Who is using a LIFF page (a web page that opens inside LINE)?

The page gets a LINE-signed ID token from the LIFF SDK and sends it with every API call. The server asks
LINE to verify it for our LINE Login channel; the `sub` claim is the person's LINE user ID (the same one the
bot sees, because both channels are under one provider). Verified tokens are remembered until they expire.
"""

import time
from dataclasses import dataclass
from typing import Optional, Protocol

import httpx

VERIFY_URL = "https://api.line.me/oauth2/v2.1/verify"


@dataclass
class LiffUser:
    user_id: str
    name: str


class LiffVerifier(Protocol):
    async def verify(self, id_token: str) -> Optional[LiffUser]: ...


class LineIdTokenVerifier:
    def __init__(self, channel_id: str):
        self.channel_id = channel_id
        self._cache: dict[str, tuple[float, LiffUser]] = {}

    async def verify(self, id_token: str) -> Optional[LiffUser]:
        if not id_token or not self.channel_id:
            return None
        now = time.time()
        hit = self._cache.get(id_token)
        if hit and hit[0] > now:
            return hit[1]
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(VERIFY_URL, data={"id_token": id_token, "client_id": self.channel_id})
        if resp.status_code != 200:
            return None
        claims = resp.json()
        user = LiffUser(user_id=claims["sub"], name=(claims.get("name") or "メンバー")[:20])
        if len(self._cache) > 5000:
            self._cache.clear()
        self._cache[id_token] = (min(claims.get("exp", now + 300), now + 3600), user)
        return user


class FakeVerifier:
    """Tests: tokens look like 'user:<id>:<name>'."""

    async def verify(self, id_token: str) -> Optional[LiffUser]:
        if not id_token.startswith("user:"):
            return None
        from urllib.parse import unquote
        _, uid, name = id_token.split(":", 2)
        return LiffUser(uid, unquote(name))
