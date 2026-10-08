"""
Small document store used by the bot: a dict in memory for local runs and tests, Firestore in production.

Documents are plain dicts. A top-level `expire_at` (epoch seconds) marks when a document may be deleted:
the memory store hides expired documents, and Firestore's TTL policy deletes them for real.
"""

import asyncio
import copy
import time
from typing import Any, Callable, Optional, Protocol

# Returned by a transaction function to leave a document untouched.
KEEP = object()

Doc = Optional[dict[str, Any]]
TxnFn = Callable[[list[Doc]], tuple[list[Any], Any]]


class Store(Protocol):
    async def get(self, coll: str, doc_id: str) -> Doc: ...
    async def set(self, coll: str, doc_id: str, data: dict[str, Any]) -> None: ...
    async def delete(self, coll: str, doc_id: str) -> None: ...
    async def create_if_absent(self, coll: str, doc_id: str, data: dict[str, Any]) -> bool: ...
    async def transact(self, refs: list[tuple[str, str]], fn: TxnFn) -> Any: ...
    async def count(self, coll: str) -> int: ...


def _expired(doc: Doc, now: float) -> bool:
    return bool(doc) and doc.get("expire_at") is not None and doc["expire_at"] < now


class MemoryStore:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._data: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._clock = clock

    def _read(self, coll: str, doc_id: str) -> Doc:
        doc = self._data.get((coll, doc_id))
        if doc is None or _expired(doc, self._clock()):
            return None
        return copy.deepcopy(doc)

    async def get(self, coll: str, doc_id: str) -> Doc:
        return self._read(coll, doc_id)

    async def set(self, coll: str, doc_id: str, data: dict[str, Any]) -> None:
        self._data[(coll, doc_id)] = copy.deepcopy(data)

    async def delete(self, coll: str, doc_id: str) -> None:
        self._data.pop((coll, doc_id), None)

    async def create_if_absent(self, coll: str, doc_id: str, data: dict[str, Any]) -> bool:
        async with self._lock:
            if self._read(coll, doc_id) is not None:
                return False
            self._data[(coll, doc_id)] = copy.deepcopy(data)
            return True

    async def transact(self, refs: list[tuple[str, str]], fn: TxnFn) -> Any:
        async with self._lock:
            current = [self._read(c, d) for c, d in refs]
            new_docs, result = fn(current)
            for (c, d), new in zip(refs, new_docs):
                if new is KEEP:
                    continue
                if new is None:
                    self._data.pop((c, d), None)
                else:
                    self._data[(c, d)] = copy.deepcopy(new)
            return result

    async def count(self, coll: str) -> int:
        now = self._clock()
        return sum(1 for (c, _), doc in self._data.items() if c == coll and not _expired(doc, now))

    def all_docs(self, coll: str) -> dict[str, dict[str, Any]]:
        """Test helper: every live document in a collection."""
        now = self._clock()
        return {d: copy.deepcopy(doc) for (c, d), doc in self._data.items() if c == coll and not _expired(doc, now)}


async def increment(store: Store, coll: str, doc_id: str, field: str, amount: int = 1,
                    limit: Optional[int] = None, expire_at: Optional[float] = None) -> bool:
    """Atomically add `amount` to a counter. Refuses (returns False) when that would pass `limit`."""

    def fn(docs: list[Doc]):
        doc = docs[0] or {}
        current = int(doc.get(field, 0))
        if limit is not None and current + amount > limit:
            return [KEEP], False
        doc[field] = current + amount
        if expire_at is not None:
            doc["expire_at"] = expire_at
        return [doc], True

    return await store.transact([(coll, doc_id)], fn)
