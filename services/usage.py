"""
Daily usage counters (Japan time), used as a circuit breaker so a busy day can't run up a bill.

`take` reserves one unit and refuses once the day's limit is reached; `note` just counts.
"""

import datetime as dt
import time
from typing import Callable, Optional

from services.store import Store, increment

JST = dt.timezone(dt.timedelta(hours=9))


def jst_day(now: float) -> str:
    return dt.datetime.fromtimestamp(now, JST).strftime("%Y%m%d")


class Usage:
    def __init__(self, store: Store, limits: dict[str, int], clock: Callable[[], float] = time.time):
        self._store = store
        self._limits = limits
        self._clock = clock

    async def take(self, kind: str, amount: int = 1) -> bool:
        now = self._clock()
        return await increment(self._store, "daily", jst_day(now), kind, amount,
                               limit=self._limits.get(kind), expire_at=now + 3 * 86400)

    async def note(self, kind: str, amount: int = 1) -> None:
        now = self._clock()
        await increment(self._store, "daily", jst_day(now), kind, amount, expire_at=now + 3 * 86400)

    async def today(self) -> dict[str, int]:
        doc = await self._store.get("daily", jst_day(self._clock())) or {}
        return {k: v for k, v in doc.items() if k != "expire_at"}

    def limit(self, kind: str) -> Optional[int]:
        return self._limits.get(kind)
