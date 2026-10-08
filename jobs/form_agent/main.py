"""
Cloud Run Job: the browser half of the form agent (see agents/form_agent.py).

Reads the run from Firestore (RUN_ID), opens the demo venue form, lets the LLM match fields to booking
values, fills and submits it, and writes each step plus a small screenshot back to the run document so
the status page can show progress.
"""

import asyncio
import base64
import logging
import os
import sys
import time
from typing import Any
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.form_agent import booking_values, map_fields  # noqa: E402
from services.llm_client import LLMClient  # noqa: E402

log = logging.getLogger("form_agent_job")

READ_FIELDS_JS = """
() => Array.from(document.querySelectorAll('form [name]')).filter(el => el.type !== 'hidden' && el.type !== 'submit').map(el => {
  const label = el.id ? (document.querySelector(`label[for="${el.id}"]`)?.innerText || '') : '';
  const options = el.tagName === 'SELECT' ? Array.from(el.options).map(o => o.value).slice(0, 40) : undefined;
  return {name: el.name, label: label.trim(), type: el.type || el.tagName.toLowerCase(), required: el.required, options};
})
"""


async def _update(store, run_id: str, **fields: Any) -> None:
    def fn(docs):
        doc = dict(docs[0] or {})
        doc.update(fields)
        return [doc], None

    await store.transact([("agent_runs", run_id)], fn)


async def _step(store, run_id: str, page, text: str) -> None:
    shot = await page.screenshot(type="jpeg", quality=45, full_page=False)
    def fn(docs):
        doc = dict(docs[0] or {})
        doc["steps"] = (doc.get("steps") or []) + [{"t": text, "at": time.time()}]
        doc["screenshot"] = "data:image/jpeg;base64," + base64.b64encode(shot).decode()
        return [doc], None

    await store.transact([("agent_runs", run_id)], fn)


async def run_agent(run_id: str, store, llm: LLMClient, base_url: str) -> None:
    from playwright.async_api import async_playwright

    run = await store.get("agent_runs", run_id)
    if not run:
        log.error("run %s not found", run_id)
        return
    await _update(store, run_id, status="running", started_at=time.time())
    values = booking_values(run)
    shop = run.get("shop") or {}
    url = f"{base_url}/demo-venue/{quote(shop.get('id') or 'demo')}?n={quote(shop.get('name') or '')}"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox"])
            page = await browser.new_page(viewport={"width": 420, "height": 760}, locale="ja-JP")
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await _step(store, run_id, page, "予約ページを開きました")

            fields = await page.evaluate(READ_FIELDS_JS)
            mapping = await map_fields(llm, fields)
            await _step(store, run_id, page, f"入力欄を{len(fields)}個見つけ、{len(mapping)}個に何を書くか決めました")

            labels = {"date": "日付", "time": "時間", "party_size": "人数", "name": "名前", "phone": "電話番号", "notes": "ご要望"}
            for field in fields:
                key = mapping.get(field["name"])
                value = values.get(key or "", "")
                if not key or value == "":
                    continue
                locator = page.locator(f'[name="{field["name"]}"]')
                if field["type"].startswith("select"):
                    await locator.select_option(value)
                else:
                    await locator.fill(value)
                await _step(store, run_id, page, f"{labels.get(key, key)}：{value}")

            await page.locator("form [type=submit]").first.click()
            await page.wait_for_selector("[data-confirmation]", timeout=15000)
            confirmation = (await page.locator("[data-confirmation]").inner_text()).strip()
            await _step(store, run_id, page, "送信しました（デモ店舗）")
            await browser.close()
        await _update(store, run_id, status="done", finished_at=time.time(), result=confirmation[:200])
    except Exception as e:
        log.exception("form agent failed")
        await _update(store, run_id, status="failed", finished_at=time.time(), error=str(e)[:200])


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    from config import get_settings
    from services.firestore_store import FirestoreStore

    s = get_settings()
    run_id = os.environ["RUN_ID"]
    store = FirestoreStore(project=s.gcp_project or None)
    llm = LLMClient(s.gmi_api_key, s.gmi_base_url, s.gmi_model)
    asyncio.run(run_agent(run_id, store, llm, s.public_base_url))


if __name__ == "__main__":
    main()
