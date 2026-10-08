# AsobiAgent (アソビ・エージェント)

A LINE bot that helps a group of friends pick **one fair meeting station and one place to eat**, without anyone
having to play organizer. Built for the 5th Agentic AI Hackathon with Google Cloud, now being prepared as a
small invite-only beta.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## How it works in a LINE group

| Phase | What happens | Paid calls |
|---|---|---|
| 0 招待済み | Someone adds the bot. It reads nothing until a **verified member** taps 有効化する. | — |
| 1 待機 | Activated. Ordinary chat is dropped unread. | — |
| 2 募集 | `@AsobiAgent 土曜13時からランチ` (or プランを立てる). People tap 参加する and just chat: 「横浜から行くよ」. Stations are recognised by rules and checked against 駅すぱあと's station list. | station checks, cached |
| 3 確認 | When everyone has a station, a card lists them. The search starts when **everyone taps ✅**, or the organizer taps もう探して. | — |
| 4 検索 | One 駅すぱあと range search finds the station with the shortest worst-case trip (average times, no timetable). HotPepper finds real venues within 1 km, minus any that are closed at the planned time; each page of three also gets one place Time Out has written about, when one fits. | Ekispert ×1, HotPepper ×1, LLM ×2 (optional) |
| 5 投票 | Three venues with votes, ほかの3軒, and refinements: もっと安く / 個室がいい / 駅の近く / 「@AsobiAgent 和食がいい」. | per refinement: HotPepper ×1, LLM ×1 |
| 6 決定 | Majority wins. The bot posts the venue, a HotPepper booking link, a **call script with a one-tap dial button**, and a demo **form agent** link, then leaves the group. | Places ×1 |

The bot **never places calls and never claims a booking is made**. Its 「AIに入力を任せる」 agent fills in a
reservation form in a real browser, but only our own demo venue form.

**Who can use it:** LINE users who redeemed a single-use invite code by DM (the admin issues them with
`/invite 5`). Each verified person can activate 2 groups; each group gets 1 decided venue, 3 searches and 7 days.
Daily caps protect the paid APIs. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#5-limits-environment-variables-on-the-service).

**Privacy:** LINE IDs are stored only as hashes, chat text only while a plan is gathering, and everything personal
is deleted at the decision (details at `/privacy`).

## Code map

| Path | What |
|---|---|
| `server.py` | FastAPI app: `/webhook` (signature-checked), simulator API, form agent pages, `/privacy` |
| `bot/group.py` | Group lifecycle (phases 0–6) |
| `bot/onboarding.py` | 1:1 chat: invite codes, admin commands |
| `bot/text_parse.py` | Rule-based reading of stations, dates and triggers |
| `agents/` | Agent 1 details (LLM, rule fallback) · Agent 2 hub (Ekispert) · Agent 3 venues (HotPepper) · Agent 4 call script and form agent |
| `services/` | Clients (LINE, Ekispert MCP, HotPepper, Places, GMI), Firestore/memory store, daily usage caps, Time Out index, opening-hours parser |
| `jobs/form_agent/` | Cloud Run Job: Playwright browser for the form agent |
| `jobs/timeout_crawl.py` | Builds the "Time Out で紹介" index (facts and links only) |
| `static/` | Web simulator (replays preset chats without the LLM), pitch decks, privacy policy |
| `deploy/` | `deploy.sh` and build configs |

## Run locally

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env     # fill in the keys you have
./run.sh                 # http://localhost:8000
.venv/bin/python -m pytest -q
```

Locally the store is in memory, and without a LINE access token replies are recorded instead of sent. To try the
form agent locally: `pip install playwright && playwright install chromium`, then run with `FORM_AGENT_MODE=local`.

## Data sources and their rules

- **駅すぱあと (Ekispert) MCP:** only timetable-free tools (`get_stations`, `search_ranges` with average waits,
  `search_routes` with `searchType: plain`).
- **ホットペッパーグルメ Webサービス:** the credit 「Powered by ホットペッパーグルメ Webサービス」 is shown on every
  card that uses its data, cached data expires within 24 hours, and the service is free (no revenue from the data).
- **Time Out:** their terms forbid copying, reposting or translating content. The crawler (robots.txt-compliant,
  one request every 2 s) keeps only facts about each place (name, coordinates, address, phone, opening hours) and
  Time Out's URL. The bot uses them to badge matching HotPepper venues, to suggest Time Out places as candidates,
  and to fill in a phone number, always linking to Time Out and never showing their writing or photos. The index
  is git-ignored. Details: [docs/TIMEOUT.md](docs/TIMEOUT.md).
- **Google Places:** phone numbers aren't cached, and lookups are capped per day.

## Deploying

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). In short: `PROJECT_ID=asobi-agent-xxxx ./deploy/deploy.sh all`.
