# 🤖 AsobiAgent (アソビ・エージェント)

> **Autonomous Multi-Agent Concierge for Group Outings in High-Density Urban Cities**  
> *Developed for the 5th Agentic AI Hackathon with Google Cloud (第5回 Agentic AI Hackathon with Google Cloud)*

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Google Cloud Run](https://img.shields.io/badge/Google%20Cloud-Run%20Ready-4285F4.svg)](https://cloud.google.com/run)
[![Ekispert MCP](https://img.shields.io/badge/Ekispert-MCP%20Server-FF6B6B.svg)](https://docs.ekispert.com/)
[![GMI Cloud](https://img.shields.io/badge/GMI%20Cloud-Qwen3.8--Flash-8A2BE2.svg)](https://gmicloud.ai/)

---

## 📖 Overview

Planning weekend outings with 4–6 friends in Tokyo is notorious for **"Kanji Fatigue" (幹事疲れ)** and severe weekend overcrowding. A single lunch plan often requires over 30 scattered LINE messages, creates unspoken friction over unbalanced travel times, and ends in a 45-minute wait outside a packed Shibuya cafe.

**AsobiAgent** solves this natively inside **LINE group chats**. Just invite the bot to your group: it passively synchronizes member availability, uses the **駅すぱあと (Ekispert) API MCP Server** to calculate the most equal midpoint station, curates low-crowd hidden gems (穴場), and autonomously calls traditional Japanese venues to reserve tables over the phone.

---

## ⚡ Key Highlights

* **Zero App Downloads / Native LINE UX:** Runs directly inside LINE using rich **LINE Flex Messages** (poll cards, fairness charts, venue carousels, reservation tickets).
* **Ekispert Non-Timetable Compliance (`ダイヤ情報不使用`):** Strictly follows hackathon guidelines by using topological range search (`multipleRange`) and average travel durations (`searchType: plain`) to achieve travel equality ($\le \pm 5$ mins) without relying on specific timetables.
* **Crowd Avoidance Intelligence:** Identifies calm back-alley venues, spacious bistros, and reservation-only spots away from tourist choke points.
* **Autonomous Voice Reservation Agent:** Capable of generating dynamic Japanese telephone booking dialogues and autonomously calling non-tech venues.
* **Dual-Language Pitch Deck Included:** Interactive HTML presentation slides in Japanese (`presentation_ja.html`) and English (`presentation_en.html`) with phonetic speaker notes.

---

## 🏗️ Architecture & Multi-Agent Pipeline

AsobiAgent coordinates 4 specialized autonomous agents sequentially:

```mermaid
flowchart TD
    User["👥 LINE Group Chat (Users)"] -->|Webhook / Messages| Orch["⚡ AsobiAgent Orchestrator"]
    
    subgraph MultiAgentPipeline ["🤖 4-Step Multi-Agent Pipeline"]
        direction TB
        A1["📅 Agent 1: Schedule & Intent Synchronizer<br/><i>(GMI Cloud / Qwen3.8-Flash)</i><br/>Extracts attendees, departure stations, preferences"]
        A2["🚇 Agent 2: Station Hub Balancer<br/><i>(駅すぱあと Ekispert MCP)</i><br/>Calculates equal-distance midpoint station"]
        A3["🌿 Agent 3: Crowd-Avoidance Spot Finder<br/><i>(Local Curated DB + GMI LLM)</i><br/>Filters 3 hidden gems away from tourist crowds"]
        A4["📞 Agent 4: Autonomous Voice Booking<br/><i>(Speech Synthesis & Dialogue Engine)</i><br/>Calls venue & confirms table reservation"]
        
        A1 -->|Member Origins & Time| A2
        A2 -->|Optimal Midpoint Station| A3
        A3 -->|Selected Venue Choice| A4
    end

    Orch --> A1
    A4 -->|Booking Confirmation Ticket| User
```

---

### Multi-Agent Interaction Sequence

```mermaid
sequenceDiagram
    autonumber
    actor Friends as 👥 Group Members
    participant LINE as 💬 LINE Group UI
    participant Orch as ⚡ Orchestrator
    participant Ekispert as 🚇 Ekispert MCP Server
    participant GMI as 🧠 GMI Cloud (LLM)
    actor Venue as 🍽️ Venue Staff

    Friends->>LINE: "Let's meet Sat 1PM! Yokohama, Nakameguro, Kichijoji, Kashiwa"
    LINE->>Orch: Ingest chat messages
    Orch->>GMI: Agent 1: Extract members, origins & tastes
    GMI-->>Orch: {origins: [Yokohama, Nakameguro, Kichijoji, Kashiwa]}
    
    Orch->>Ekispert: Agent 2: search_ranges(baseList, upperMinutes=45)
    Ekispert-->>Orch: Common reachable station candidates
    Orch->>Ekispert: search_routes (searchType: plain) in parallel
    Ekispert-->>Orch: Travel times (All within ±4 mins) ➔ Hub: "Okachimachi / Ueno"
    
    Orch->>GMI: Agent 3: Find 3 low-crowd venues near Hub
    GMI-->>Orch: Curated venues with crowd avoidance rationale
    Orch->>LINE: Render Midpoint Fairness Card & Venue Carousel
    
    Friends->>LINE: Tap "🤖 AI電話で予約を依頼する"
    LINE->>Orch: Trigger Agent 4 Voice Reservation
    Orch->>Venue: Autonomous phone call (Japanese speech dialogue)
    Venue-->>Orch: "Confirmed! Table for 4 at 1:00 PM"
    Orch->>LINE: Issue Reservation Ticket Card (#ASOBI-XXXXXX)
```

---

## 🛠️ Tech Stack

| Component | Technology | Description |
|---|---|---|
| **Backend** | Python 3.11+, FastAPI, Uvicorn | High-performance asynchronous API server |
| **Transit Intelligence** | **駅すぱあと (Ekispert) API MCP Server** | Official MCP endpoint (`https://api-mcp.ekispert.jp/mcp`) |
| **LLM Inference** | **GMI Cloud (`Qwen/Qwen3.8-Flash`)** | High-speed 1M context open-source model inference |
| **Cloud Hosting** | **Google Cloud (Cloud Run)** | Serverless containerized deployment with auto-scaling |
| **Messaging UI** | **LINE Messaging API (Flex Messages)** | Authentic cards, carousels, action postbacks |
| **Frontend / Simulator**| Vanilla JS, CSS3, Web Speech API | Dual-view LINE chat mockup + telemetry inspector |

---

## 🚀 Quickstart & Local Setup

### 1. Clone Repository & Setup Environment

```bash
git clone https://github.com/<your-username>/asobi-agent.git
cd asobi-agent

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` with your API keys:

```env
# GMI Cloud Credentials (or OpenAI-compatible endpoint)
GMI_API_KEY=your_gmi_api_key_here
GMI_BASE_URL=https://api.gmi-serving.com/v1
GMI_MODEL=Qwen/Qwen3.8-Flash

# 駅すぱあと (Ekispert) API MCP Server Credentials
EKISPERT_API_ACCESS_KEY=your_ekispert_access_key_here
EKISPERT_MCP_URL=https://api-mcp.ekispert.jp/mcp
```

### 3. Run the Application

```bash
./run.sh
```
*(or manually with `.venv/bin/python server.py`)*

Open **`http://localhost:8000`** in your browser:
* **Interactive Live Demo:** `http://localhost:8000`
* **Japanese Slide Deck:** `http://localhost:8000/presentation_ja.html`
* **English Pitch Deck & Notes:** `http://localhost:8000/presentation_en.html`

---

## ☁️ Google Cloud Deployment (Cloud Run)

AsobiAgent is fully containerized and ready for **Google Cloud Run**.

### Step 1: Authenticate Google Cloud CLI
```bash
gcloud auth login
gcloud config set project <YOUR_GCP_PROJECT_ID>
```

### Step 2: Build & Deploy to Cloud Run
Deploy directly from source using Google Cloud Build:

```bash
gcloud run deploy asobi-agent \
  --source . \
  --region asia-northeast1 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars GMI_API_KEY="YOUR_GMI_KEY" \
  --set-env-vars EKISPERT_API_ACCESS_KEY="YOUR_EKISPERT_KEY"
```

Once deployed, Cloud Run will output your live HTTPS URL:
```text
Service URL: https://asobi-agent-xxxxxx-an.a.run.app
```

You can point your **LINE Messaging API Webhook URL** directly to `https://asobi-agent-xxxxxx-an.a.run.app/webhook`.

---

## 🛡️ Hackathon Rule Compliance Note

> **ダイヤ情報の利用制限への対応策 (Non-Timetable Compliance Statement):**  
> 本リポジトリのコードは「駅すぱあと」APIの時刻指定ダイヤ探索機能を使用していません。`ekispert_api_search_ranges` による到達可能駅探索および `searchType: "plain"`（平均乗車時間探索）による相対的な移動コスト比較のみに限定して使用しており、時間調整・スケジューリングはLLMオーケストレーター側で自律処理しています。

---

## 📑 Presentation Slides

The project includes standalone slide decks for pitching:
* **[`presentation_ja.html`](presentation_ja.html):** Japanese slides formatted for projection to judges.
* **[`presentation_en.html`](presentation_en.html):** English slides with Romanized Japanese pronunciation cheatsheets.

To present, open either HTML file in any browser and navigate using the arrow keys `[←]` / `[→]`.

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
