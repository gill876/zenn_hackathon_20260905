"""
Agent 4 (web form, demo): an AI agent that fills in a restaurant's reservation form in a real browser.

It only ever targets the demo venue form this app serves (/demo-venue/...). Real booking sites need the
diner's own login and personal details, so the agent never touches them. The browser runs in a Cloud Run
Job (jobs/form_agent), or in-process locally when Playwright is installed.

How it decides what to type: the date, time, party size and name are worked out without a model; the LLM
only reads the form's labels and says which field gets which value, which is what lets it handle a form
it has never seen.
"""

import asyncio
import datetime as dt
import json
import logging
from typing import Any, Optional

import httpx

from bot.text_parse import resolve_day
from services.llm_client import LLMClient
from services.usage import JST

log = logging.getLogger("form_agent")

SYSTEM = "You fill in web forms for restaurant reservations. Reply with a JSON object only."


def booking_values(run: dict[str, Any], today: Optional[dt.date] = None) -> dict[str, str]:
    today = today or dt.datetime.now(JST).date()
    day = resolve_day(run.get("day"), today) or (today + dt.timedelta(days=7))
    time = run.get("time") or "19:00"
    return {
        "date": day.isoformat(),
        "time": time,
        "party_size": str(run.get("pax") or 2),
        "name": run.get("name") or "AsobiAgent",
        "phone": "",
        "notes": "AsobiAgentのデモ予約です。",
    }


def rule_based_mapping(fields: list[dict[str, Any]]) -> dict[str, str]:
    keys = {"date": ["日", "date"], "time": ["時間", "時刻", "time"], "party_size": ["人数", "party", "people", "guests"],
            "name": ["名前", "氏名", "name"], "phone": ["電話", "tel", "phone"], "notes": ["要望", "備考", "note"]}
    mapping = {}
    for f in fields:
        label = f"{f.get('label', '')} {f.get('name', '')}".lower()
        for value_key, words in keys.items():
            if value_key not in mapping.values() and any(w in label for w in words):
                mapping[f["name"]] = value_key
                break
    return mapping


async def map_fields(llm: LLMClient, fields: list[dict[str, Any]]) -> dict[str, str]:
    """{form field name: one of date|time|party_size|name|phone|notes}"""
    fallback = rule_based_mapping(fields)
    if not llm.available:
        return fallback
    prompt = f"""A reservation form has these fields:
{json.dumps(fields, ensure_ascii=False)}
For each field, say which booking value goes in it. Values: date, time, party_size, name, phone, notes.
Leave out fields that match none. Return {{"mapping": {{"<field name>": "<value>"}}}}"""
    raw = await llm.generate_json(prompt, SYSTEM, max_tokens=300)
    mapping = raw.get("mapping") if isinstance(raw.get("mapping"), dict) else {}
    allowed = {"date", "time", "party_size", "name", "phone", "notes"}
    names = {f["name"] for f in fields}
    clean = {k: v for k, v in mapping.items() if k in names and v in allowed}
    return clean or fallback


class CloudRunJobRunner:
    """Starts one execution of the form-agent Cloud Run Job, passing the run ID as an env override."""

    def __init__(self, project: str, region: str, job: str):
        self.url = f"https://run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/{job}:run"

    async def launch(self, run_id: str) -> bool:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        await asyncio.to_thread(creds.refresh, google.auth.transport.requests.Request())
        body = {"overrides": {"containerOverrides": [{"env": [{"name": "RUN_ID", "value": run_id}]}]}}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(self.url, json=body, headers={"Authorization": f"Bearer {creds.token}"})
        if resp.status_code >= 300:
            log.error("job launch failed: %s %s", resp.status_code, resp.text[:300])
            return False
        return True


class LocalRunner:
    """Runs the browser in this process (development only; needs `pip install playwright`)."""

    def __init__(self, store, llm: LLMClient, base_url: str):
        self.store, self.llm, self.base_url = store, llm, base_url
        self._tasks: set[asyncio.Task] = set()

    async def launch(self, run_id: str) -> bool:
        from jobs.form_agent.main import run_agent

        task = asyncio.create_task(run_agent(run_id, self.store, self.llm, self.base_url))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True
