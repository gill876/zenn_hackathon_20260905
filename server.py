"""
AsobiAgent Backend Server (FastAPI)
Provides:
- Webhook for real LINE Messaging API
- Interactive REST API for the Hackathon Live Simulator UI
- Multi-Agent state & telemetry streams
"""

import os
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from agents.orchestrator import AsobiOrchestrator

load_dotenv()

app = FastAPI(title="AsobiAgent - Autonomous Multi-Agent Concierge")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = AsobiOrchestrator()

# Request models
class ChatMessageRequest(BaseModel):
    sender: str
    text: str

class ReservationRequest(BaseModel):
    venue_id: str
    organizer: Optional[str] = "佐藤"

class ScenarioRequest(BaseModel):
    scenario_id: str

# API Endpoints
@app.get("/api/session")
async def get_session():
    """Retrieve full agent pipeline state."""
    return orchestrator.get_current_state()

@app.post("/api/reset")
async def reset_session():
    """Reset current demo session."""
    orchestrator.reset_session()
    return {"status": "reset", "state": orchestrator.get_current_state()}

@app.post("/api/chat")
async def send_chat_message(req: ChatMessageRequest):
    """Process message through Agent 1 -> Agent 2 -> Agent 3."""
    result = await orchestrator.process_chat_message(req.sender, req.text)
    return result

@app.post("/api/reserve")
async def execute_reservation(req: ReservationRequest):
    """Trigger Agent 4: Autonomous Voice Reservation."""
    result = await orchestrator.execute_reservation(req.venue_id, req.organizer or "佐藤")
    return result

@app.post("/api/scenario")
async def run_preset_scenario(req: ScenarioRequest):
    """Executes a pre-scripted multi-member conversation for 1-click live demo."""
    orchestrator.reset_session()
    
    scenarios = {
        "tokyo_meat_4": [
            {"sender": "佐藤", "text": "みんな来週土曜日の昼13時くらいから空いてる？ご飯行こうよ！"},
            {"sender": "鈴木", "text": "土曜13時空いてるよ！最近どこも混んでるから、渋谷や新宿の混雑は避けたいな〜"},
            {"sender": "田中", "text": "いいね！美味しいお肉かバル系食べたい！ちなみに私「中目黒」から行くよ"},
            {"sender": "鈴木", "text": "俺は「吉祥寺」から向かう！"},
            {"sender": "佐藤", "text": "了解！俺は「横浜」から乗るから、みんなが来やすい場所がいいな"},
            {"sender": "高橋", "text": "参加する！「柏」から向かうから常磐線・上野東京ライン使えると嬉しい"}
        ],
        "cafe_girls_3": [
            {"sender": "美咲", "text": "今度の日曜14時にゆっくりお茶しない？"},
            {"sender": "結衣", "text": "行きたい！落ち着いておしゃべりできる静かなカフェがいいな。私は「三軒茶屋」から行くよ"},
            {"sender": "陽菜", "text": "賛成！私は「北千住」から日比谷線で向かうね"},
            {"sender": "美咲", "text": "私は「恵比寿」！真ん中あたりの穴場探そう"}
        ],
        "craft_beer_3": [
            {"sender": "健太", "text": "金曜日の19時に仕事終わりにクラフトビール飲みに行かない？"},
            {"sender": "大輔", "text": "最高！俺は「大宮」から京浜東北で向かうよ"},
            {"sender": "翔平", "text": "俺は「品川」で退勤予定！"},
            {"sender": "健太", "text": "俺は「立川」の中央線だから、ちょうど真ん中がいいな"}
        ]
    }

    selected = scenarios.get(req.scenario_id, scenarios["tokyo_meat_4"])
    
    # Process all scenario messages in one optimized pipeline pass
    result = await orchestrator.process_scenario_fast(selected)

    return {
        "status": "scenario_loaded",
        "scenario_id": req.scenario_id,
        "input_messages": selected,
        "bot_messages": result.get("bot_messages", []),
        "session_state": orchestrator.get_current_state()
    }

@app.post("/webhook")
async def line_webhook(request: Request):
    """
    Official LINE Messaging API Webhook endpoint.
    Processes real Webhook events when connected to a LINE Official Account.
    """
    body = await request.body()
    # If LINE credentials exist, can verify signature and reply via LINE Messaging API
    logger_msg = f"Received LINE Webhook payload: {len(body)} bytes"
    return {"status": "ok", "message": logger_msg}

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>AsobiAgent Backend Running</h1>")

@app.get("/presentation")
@app.get("/presentation_ja.html")
async def presentation_ja():
    path = os.path.join(static_dir, "presentation_ja.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("Not Found", status_code=404)

@app.get("/presentation_en")
@app.get("/presentation_en.html")
async def presentation_en():
    path = os.path.join(static_dir, "presentation_en.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("Not Found", status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
