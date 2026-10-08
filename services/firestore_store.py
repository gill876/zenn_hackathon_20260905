"""Firestore implementation of the Store protocol (see services/store.py)."""

import datetime as dt
from typing import Any

from google.cloud import firestore

from services.store import KEEP, Doc, TxnFn


def _to_fs(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    if isinstance(out.get("expire_at"), (int, float)):
        out["expire_at"] = dt.datetime.fromtimestamp(out["expire_at"], tz=dt.timezone.utc)
    return out


def _from_fs(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    if isinstance(out.get("expire_at"), dt.datetime):
        out["expire_at"] = out["expire_at"].timestamp()
    return out


class FirestoreStore:
    def __init__(self, project: str | None = None, database: str = "(default)"):
        self._db = firestore.AsyncClient(project=project or None, database=database)

    def _ref(self, coll: str, doc_id: str):
        return self._db.collection(coll).document(doc_id)

    async def get(self, coll: str, doc_id: str) -> Doc:
        snap = await self._ref(coll, doc_id).get()
        if not snap.exists:
            return None
        doc = _from_fs(snap.to_dict())
        # TTL deletion can lag by up to a day, so treat expired documents as gone right away.
        if doc.get("expire_at") is not None and doc["expire_at"] < dt.datetime.now(dt.timezone.utc).timestamp():
            return None
        return doc

    async def set(self, coll: str, doc_id: str, data: dict[str, Any]) -> None:
        await self._ref(coll, doc_id).set(_to_fs(data))

    async def delete(self, coll: str, doc_id: str) -> None:
        await self._ref(coll, doc_id).delete()

    async def create_if_absent(self, coll: str, doc_id: str, data: dict[str, Any]) -> bool:
        def fn(docs: list[Doc]):
            if docs[0] is not None:
                return [KEEP], False
            return [data], True

        return await self.transact([(coll, doc_id)], fn)

    async def transact(self, refs: list[tuple[str, str]], fn: TxnFn) -> Any:
        doc_refs = [self._ref(c, d) for c, d in refs]
        now = dt.datetime.now(dt.timezone.utc).timestamp()

        @firestore.async_transactional
        async def run(transaction):
            current: list[Doc] = []
            for ref in doc_refs:
                snap = await ref.get(transaction=transaction)
                doc = _from_fs(snap.to_dict()) if snap.exists else None
                if doc is not None and doc.get("expire_at") is not None and doc["expire_at"] < now:
                    doc = None
                current.append(doc)
            new_docs, result = fn(current)
            for ref, new in zip(doc_refs, new_docs):
                if new is KEEP:
                    continue
                if new is None:
                    transaction.delete(ref)
                else:
                    transaction.set(ref, _to_fs(new))
            return result

        return await run(self._db.transaction())

    async def count(self, coll: str) -> int:
        result = await self._db.collection(coll).count().get()
        return int(result[0][0].value)
