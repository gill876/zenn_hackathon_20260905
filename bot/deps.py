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
    clock: Callable[[], float] = field(default=time.time)

    async def reply(self, ev: dict[str, Any], messages: list[dict[str, Any]]) -> None:
        token = ev.get("replyToken")
        if token and messages:
            ok = await self.line.reply(token, messages)
            if not ok:
                log.warning("reply failed for event type %s", ev.get("type"))

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
        llm=LLMClient(settings.gmi_api_key, settings.gmi_base_url, settings.gmi_model, usage=usage),
        ekispert=ekispert,
        stations=StationResolver(ekispert, store, clock=clock),
        hotpepper=HotPepperClient(settings.hotpepper_api_key, store=store, usage=usage, clock=clock),
        places=PlacesClient(settings.places_api_key, usage=usage),
        form_agent=form_agent,
        clock=clock,
    )
