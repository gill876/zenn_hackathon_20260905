"""
Hashed identifiers and signed links.

LINE user and group IDs never reach the database in the clear: they are stored as an HMAC keyed with a
secret only the server knows. LINE sends the raw ID with every webhook, so the bot can still talk to the
group; it just can't list who it has talked to.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Optional

# Invite codes avoid characters that are easy to misread (0/O, 1/I/L).
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Ids:
    def __init__(self, app_secret: str):
        key = app_secret.encode()
        self._pepper = hmac.new(key, b"asobi:id-hash:v1", hashlib.sha256).digest()
        self._sign_key = hmac.new(key, b"asobi:link-sign:v1", hashlib.sha256).digest()

    def _hash(self, prefix: str, raw: str) -> str:
        return hmac.new(self._pepper, f"{prefix}:{raw}".encode(), hashlib.sha256).hexdigest()[:32]

    def user(self, line_user_id: str) -> str:
        return "u_" + self._hash("u", line_user_id)

    def chat(self, line_chat_id: str) -> str:
        return "g_" + self._hash("g", line_chat_id)

    def sign(self, payload: dict[str, Any], ttl_seconds: int) -> str:
        body = dict(payload, exp=int(time.time()) + ttl_seconds)
        raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        mac = hmac.new(self._sign_key, raw, hashlib.sha256).digest()[:16]
        return f"{_b64(raw)}.{_b64(mac)}"

    def verify(self, token: str) -> Optional[dict[str, Any]]:
        try:
            raw_b64, mac_b64 = token.split(".", 1)
            raw = _unb64(raw_b64)
            expected = hmac.new(self._sign_key, raw, hashlib.sha256).digest()[:16]
            if not hmac.compare_digest(expected, _unb64(mac_b64)):
                return None
            body = json.loads(raw)
        except Exception:
            return None
        if body.get("exp", 0) < time.time():
            return None
        return body


def new_invite_code() -> str:
    chars = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    return f"ASBI-{chars[:4]}-{chars[4:]}"


def normalize_invite_code(text: str) -> Optional[str]:
    """Accept 'asbi-7kq2-m9xd', 'ASBI 7KQ2 M9XD' or 'ASBI7KQ2M9XD'; return the canonical form or None."""
    cleaned = "".join(ch for ch in text.upper() if ch.isalnum())
    if not cleaned.startswith("ASBI") or len(cleaned) != 12:
        return None
    body = cleaned[4:]
    if any(ch not in _CODE_ALPHABET for ch in body):
        return None
    return f"ASBI-{body[:4]}-{body[4:]}"


def new_nonce() -> str:
    return secrets.token_hex(4)
