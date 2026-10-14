"""Everything the bot needs, wired once at startup (or with fakes in tests)."""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from config import Settings
from services.ekispert_client import EkispertClient
from services.hotpepper_client import HotPepperClient
from services.ids import Ids
from services.llm_client import LLMClient
from services.places_client import PlacesClient
from services.stations import StationResolver
from services.timeout_index import TimeOutIndex
from services.store import Store
from services.usage import Usage

log = logging.getLogger("bot")


@dataclass
class Deps:
    settings: Settings
    store: Store
    line: Any
    ids: Ids
    usage: Usage
    llm: LLMClient
    ekispert: EkispertClient
    stations: StationResolver
    hotpepper: HotPepperClient
    places: PlacesClient
    form_agent: Optional[Any] = None
    timeout: Optional[TimeOutIndex] = None
    liff: Optional[Any] = None           # verifies LIFF ID tokens (services/liff_auth.py)
    clock: Callable[[], float] = field(default=time.time)

    async def reply(self, ev: dict[str, Any], messages: list[dict[str, Any]]) -> None:
        token = ev.get("replyToken")
        if token and messages:
            ok = await self.line.reply(token, messages)
            if not ok:
                log.warning("reply failed for event type %s", ev.get("type"))

    async def shops(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """Shop details for HotPepper IDs (J…) and Time Out place IDs (TO…)."""
        from services.timeout_index import as_shop
        found: dict[str, dict[str, Any]] = {}
        hp = [i for i in ids if not i.startswith("TO")]
        if hp:
            found.update(await self.hotpepper.shops_by_ids(hp))
        for i in ids:
            if i.startswith("TO") and self.timeout and (place := self.timeout.get(i)):
                found[i] = as_shop(place)
        return found

    def featured(self, shop: dict[str, Any]) -> Optional[dict[str, Any]]:
        if shop.get("source") == "timeout":
            return {"id": shop["id"], "url": shop["url"], "name": shop["name"], "telephone": shop.get("telephone")}
        """Time Out's page about this shop, if they've written about it."""
        return self.timeout.match(shop) if self.timeout else None

    def base_url(self) -> str:
        return self.settings.public_base_url or "http://localhost:8000"


def build_deps(settings: Settings, store: Store, line: Any, clock: Callable[[], float] = time.time,
               form_agent: Optional[Any] = None) -> Deps:
    usage = Usage(store, {
        "searches": settings.daily_search_limit,
        "llm": settings.daily_llm_limit,
        "places": settings.daily_places_limit,
        "simulator": settings.daily_simulator_limit,
        "agent": settings.daily_agent_limit,
    }, clock=clock)
    ekispert = EkispertClient(settings.ekispert_api_key, settings.ekispert_mcp_url, usage=usage)
    return Deps(
        settings=settings,
        store=store,
        line=line,
        ids=Ids(settings.app_secret),
        usage=usage,
        llm=LLMClient.from_settings(settings, usage=usage),
        ekispert=ekispert,
        stations=StationResolver(ekispert, store, clock=clock),
        hotpepper=HotPepperClient(settings.hotpepper_api_key, store=store, usage=usage, clock=clock),
        places=PlacesClient(settings.places_api_key, usage=usage),
        form_agent=form_agent,
        timeout=TimeOutIndex.load(),
        clock=clock,
    )
