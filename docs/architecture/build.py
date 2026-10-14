"""
Draws the architecture diagram (docs/architecture/architecture_{ja,en}.svg) for the submission and the decks.

    python docs/architecture/build.py            # writes the SVGs
    python docs/architecture/build.py --png      # and renders PNGs with headless Chrome (macOS path)

Plain SVG on a fixed 1920x1080 grid, colours from the pitch deck.
"""

import pathlib
import subprocess
import sys
from html import escape

HERE = pathlib.Path(__file__).resolve().parent
W, H = 1920, 1080
BG, CARD, BORDER = "#0B0F19", "#161F30", "#23324A"
GREEN, BLUE, GOLD, RED, PURPLE = "#06C755", "#38BDF8", "#FBBF24", "#F87171", "#A78BFA"
INK, SUB = "#F8FAFC", "#94A3B8"
FONT = "'Hiragino Sans','Hiragino Kaku Gothic ProN','Noto Sans JP',system-ui,sans-serif"

TEXT = {
    "ja": {
        "title": "AsobiAgent システム構成",
        "subtitle": "LINEグループに入れるだけ。AIが段取りして、決めるのはみんな。",
        "event": "第5回 Agentic AI Hackathon with Google Cloud",
        "users": [
            ("👥 LINEグループ", ["友だち2〜10人（ひとりでも可）", "ボタンとクイックリプライで進む"]),
            ("📱 LIFF（LINE内の画面）", ["プロフィール：好み・最寄り駅", "日程調整：カレンダーと○△×", "LINEのIDトークンで本人確認"]),
            ("🖥 Webデモ（審査用）", ["シナリオ再生はコード不要", "自由入力は審査用コード"]),
        ],
        "line": ("LINE Platform", [("Messaging API", "Webhook・返信のみ"), ("Flex Message", "カード・投票ボタン"),
                                   ("LIFF・LINEログイン", "IDトークンを発行")]),
        "arrows_users": ["メッセージ・ボタン", "IDトークン"],
        "webhook": "Webhook", "reply": "返信",
        "liff_api": "LIFF API（IDトークン検証）", "web_api": "/api（審査用コード）",
        "gcp": "Google Cloud · asia-northeast1（東京）",
        "run": "Cloud Run · asobi-agent（FastAPI・使わないときは0台）",
        "gate_label": "入口",
        "gate": ["署名検証", "重複イベント排除", "招待コード認証", "グループ・1日の上限", "古いボタンは無効（nonce）"],
        "flow": ["有効化", "日程調整", "出発駅", "集合駅", "6候補", "投票", "決定・退出"],
        "agents": [
            ("① 日程・希望", "Gemini", PURPLE, ["チャットから日時と希望", "全員回答で自動締切", "最有力の日で開始", "落ちてもルールで続行"]),
            ("② 集合駅", "駅すぱあと", BLUE, ["範囲探索1回で全員分", "最遠の人が最短の駅", "ダイヤ探索は不使用", "駅は90日キャッシュ"]),
            ("③ お店選び", "Gemini", PURPLE, ["全員の好みを重ねる", "苦手・営業時間外は除外", "理由はGeminiが一言 ✨", "提案されたお店も投票へ"]),
            ("④ 予約の準備", "人が決める", GREEN, ["電話の台本と発信ボタン", "予約ページへのリンク", "電話・確定は人が行う", "フォーム入力はデモのみ"]),
        ],
        "services": [
            ("Vertex AI", PURPLE, ["Gemini 3.5 Flash-Lite", "日時の読み取り・理由づけ", "1日300回まで"]),
            ("Cloud Run Jobs", BLUE, ["フォーム入力エージェント", "Playwright ＋ Gemini", "デモ用フォームのみ"]),
            ("Firestore（東京）", GOLD, ["TTLで自動削除", "LINE IDはHMACで匿名化", "会話は検索後に削除"]),
            ("運用", SUB, ["Secret Manager", "Cloud Build", "Artifact Registry", "Cloud Logging", "予算アラート"]),
        ],
        "start_job": "起動",
        "external": "外部API",
        "apis": [
            ("駅すぱあと API（MCP）", "駅の照合・範囲探索"),
            ("ホットペッパー グルメ", "実在のお店・24時間キャッシュ"),
            ("Google Places API", "電話番号・提案されたお店"),
            ("Time Out 東京", "事実とリンクのみ・ビルド時に索引"),
            ("GMI Cloud", "Gemini の予備（Vertex が落ちたら）"),
        ],
        "guard": "ガードレール",
        "guards": ["予約・電話は人が行う", "招待制（審査用コードあり）", "1グループ1軒・検索3回・7日",
                   "1日の上限：LLM 300・検索 100", "呼ばれるまでトークを読まない", "決まったら名前・投票を消して退出",
                   "LLMの出力は候補IDと決まった項目だけ", "Vertex → GMI → ルールの3段構え"],
    },
    "en": {
        "title": "AsobiAgent architecture",
        "subtitle": "Add it to a LINE group. The AI does the legwork; the friends decide.",
        "event": "5th Agentic AI Hackathon with Google Cloud",
        "users": [
            ("👥 LINE group", ["2–10 friends (or just one)", "Buttons and quick replies"]),
            ("📱 LIFF pages in LINE", ["Profile: tastes, home station", "Date poll: calendar and ○△×", "LINE ID token proves who"]),
            ("🖥 Web demo (judges)", ["Scenario replay: no code", "Free text: judges' code"]),
        ],
        "line": ("LINE Platform", [("Messaging API", "Signed webhook · replies only"), ("Flex Message", "Cards and vote buttons"),
                                   ("LIFF · LINE Login", "Issues ID tokens")]),
        "arrows_users": ["Messages, buttons", "ID token"],
        "webhook": "Webhook", "reply": "Reply",
        "liff_api": "LIFF API (ID token checked)", "web_api": "/api (judges' code)",
        "gcp": "Google Cloud · asia-northeast1 (Tokyo)",
        "run": "Cloud Run · asobi-agent (FastAPI, scales to zero)",
        "gate_label": "Gate",
        "gate": ["Signed webhook", "Dedupe events", "Invite-only users", "Group + daily caps", "Stale buttons refused"],
        "flow": ["Activate", "Date poll", "Stations", "Meeting point", "6 places", "Vote", "Decide, leave"],
        "agents": [
            ("① Dates & wishes", "Gemini", PURPLE, ["Reads date and wishes", "Closes the poll itself", "Plans on the best day", "Rules if the LLM is down"]),
            ("② Meeting point", "Ekispert", BLUE, ["One range search", "Farthest person first", "No timetable search", "Stations cached 90 days"]),
            ("③ Places", "Gemini", PURPLE, ["Everyone's tastes", "Drops dislikes, closed", "Gemini's one-line why ✨", "Members can suggest"]),
            ("④ Booking prep", "Humans decide", GREEN, ["Call script, tap to call", "Booking page link", "People call and book", "Form filling: demo only"]),
        ],
        "services": [
            ("Vertex AI", PURPLE, ["Gemini 3.5 Flash-Lite", "Reads dates, writes reasons", "Max 300 calls a day"]),
            ("Cloud Run Jobs", BLUE, ["Form-filling agent", "Playwright + Gemini", "Demo form only"]),
            ("Firestore (Tokyo)", GOLD, ["TTL auto-delete", "LINE IDs HMAC-hashed", "Chat deleted after search"]),
            ("Operations", SUB, ["Secret Manager", "Cloud Build", "Artifact Registry", "Cloud Logging", "Budget alerts"]),
        ],
        "start_job": "starts",
        "external": "External APIs",
        "apis": [
            ("Ekispert API (MCP)", "Stations, range search"),
            ("HotPepper Gourmet", "Real places, 24 h cache"),
            ("Google Places API", "Phone numbers, suggestions"),
            ("Time Out Tokyo", "Facts and links, indexed at build"),
            ("GMI Cloud", "Gemini fallback"),
        ],
        "guard": "Guardrails",
        "guards": ["People make the call and book", "Invite only (judges' code)", "1 place, 3 searches, 7 days per group",
                   "Daily caps: LLM 300, searches 100", "Doesn't read chat until called", "Names and votes deleted at the end",
                   "LLM output limited to known ids, fields", "Vertex → GMI → rules fallback"],
    },
}


def t(x, y, s, size=15, color=INK, weight=400, anchor="start"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" '
            f'text-anchor="{anchor}">{escape(s)}</text>')


def box(x, y, w, h, stroke=BORDER, fill=CARD, r=14, dash=None, width=1.5):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"{d}/>'


def chip(x, y, label, color, size=13, pad=12, h=30):
    w = int(len(label) * size * 0.98 + pad * 2) if any(ord(c) > 0x2000 for c in label) else int(len(label) * size * 0.58 + pad * 2)
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h // 2}" fill="{color}22" stroke="{color}66"/>'
            + t(x + w / 2, y + h / 2 + size * 0.36, label, size, INK, 500, "middle")), w


def arrow(x1, y1, x2, y2, color=SUB, label=None, dash=None, lx=None, ly=None, both=False):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    start = ' marker-start="url(#head-start)"' if both else ""
    out = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="2"{d} marker-end="url(#head)"{start}/>'
    if label:
        out += t(lx if lx is not None else (x1 + x2) / 2, ly if ly is not None else (y1 + y2) / 2 - 8, label, 12, SUB, 400, "middle")
    return out


def build(lang: str) -> str:
    L = TEXT[lang]
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">',
         '<defs><marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
         f'<path d="M0,0 L10,5 L0,10 z" fill="{SUB}"/></marker>'
         '<marker id="head-start" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
         f'<path d="M10,0 L0,5 L10,10 z" fill="{SUB}"/></marker></defs>',
         f'<rect width="{W}" height="{H}" fill="{BG}"/>']

    # title
    o.append(t(48, 66, L["title"], 34, INK, 700))
    o.append(t(48, 100, L["subtitle"], 17, SUB))
    o.append(t(W - 48, 66, L["event"], 15, SUB, 400, "end"))

    # users
    ys = [(150, 140), (316, 170), (512, 130)]
    for (title, lines), (y, h) in zip(L["users"], ys):
        o.append(box(48, y, 252, h, GREEN if "LINE" in title else BORDER))
        o.append(t(68, y + 34, title, 18, INK, 700))
        for i, line in enumerate(lines):
            o.append(t(68, y + 66 + i * 26, line, 14, SUB))

    # LINE platform
    name, items = L["line"]
    o.append(box(352, 150, 220, 300, GREEN))
    o.append(t(370, 184, name, 18, GREEN, 700))
    for i, (head, sub) in enumerate(items):
        y = 200 + i * 82
        o.append(box(366, y, 192, 72, BORDER, "#0F1726", 10))
        o.append(t(380, y + 28, head, 15, INK, 700))
        o.append(t(380, y + 52, sub, 12, SUB))
    o.append(arrow(300, 220, 352, 220, both=True))
    o.append(arrow(300, 400, 352, 400, both=True))

    # Google Cloud boundary
    o.append(box(640, 128, 900, 744, BLUE, "none", 18, "8 6", 2))
    o.append(t(664, 156, L["gcp"], 15, BLUE, 700))

    # Cloud Run service
    o.append(box(664, 172, 852, 440, GREEN, CARD, 14, None, 2))
    o.append(t(688, 206, L["run"], 18, INK, 700))
    x = 688
    o.append(t(x, 248, L["gate_label"], 13, SUB, 700))
    x += 44
    for g in L["gate"]:
        c, w = chip(x, 228, g, RED)
        o.append(c)
        x += w + 8
    x = 688
    for i, step in enumerate(L["flow"]):
        c, w = chip(x, 276, step, GOLD)
        o.append(c)
        x += w
        if i < len(L["flow"]) - 1:
            o.append(t(x + 10, 296, "→", 14, SUB, 700, "middle"))
            x += 20
    aw, gap, ax = 189, 16, 688
    for i, (head, tag, color, lines) in enumerate(L["agents"]):
        bx = ax + i * (aw + gap)
        o.append(box(bx, 328, aw, 264, color, "#0F1726", 12))
        o.append(t(bx + 14, 360, head, 17, INK, 700))
        c, _ = chip(bx + 14, 374, tag, color, 12, 10, 26)
        o.append(c)
        for j, line in enumerate(lines):
            o.append(t(bx + 12, 436 + j * 36, ("・" if lang == "ja" else "• ") + line, 13, INK if j < 3 else SUB))

    # services row
    sx = [(664, 220), (898, 200), (1112, 200), (1326, 190)]
    for (head, color, lines), (bx, bw) in zip(L["services"], sx):
        o.append(box(bx, 640, bw, 210, color))
        o.append(t(bx + 14, 672, head, 16, color if color != SUB else INK, 700))
        small = len(lines) > 3
        for j, line in enumerate(lines):
            o.append(t(bx + 14, (700 if small else 704) + j * (28 if small else 30), line, 13 if small else 14,
                       INK if j == 0 else SUB))
    o.append(arrow(774, 612, 774, 640))
    o.append(arrow(998, 612, 998, 640, label=L["start_job"], lx=1022, ly=631))
    o.append(arrow(1212, 612, 1212, 640))
    o.append(arrow(898, 745, 884, 745))

    # LINE <-> Cloud Run, LIFF and web -> Cloud Run
    o.append(arrow(572, 268, 664, 268, label=L["webhook"], lx=606, ly=258))
    o.append(arrow(664, 318, 572, 318, label=L["reply"], lx=606, ly=340))
    o.append(arrow(300, 476, 664, 476, label=L["liff_api"], lx=470, ly=466))
    o.append(arrow(300, 577, 664, 577, label=L["web_api"], lx=470, ly=567))

    # external APIs
    o.append(t(1580, 140, L["external"], 15, SUB, 700))
    for i, (head, sub) in enumerate(L["apis"]):
        y = 156 + i * 112
        color = PURPLE if "GMI" in head else (BLUE if i == 0 else BORDER)
        o.append(box(1580, y, 292, 96, color))
        o.append(t(1598, y + 38, head, 16, INK, 700))
        o.append(t(1598, y + 66, sub, 13, SUB))
    for y in (204, 316, 428):
        o.append(arrow(1516, y, 1580, y))
    o.append(arrow(1580, 540, 1516, 540, dash="6 5"))
    o.append(arrow(1516, 600, 1580, 646, dash="6 5"))

    # guardrails
    o.append(box(48, 900, 1824, 128, RED, "#1A1420"))
    o.append(t(72, 952, L["guard"], 17, RED, 700))
    per_row = 4
    for i, g in enumerate(L["guards"]):
        row, col = divmod(i, per_row)
        o.append(t(232 + col * 410, 948 + row * 46, "✓ " + g, 15, INK))
    o.append("</svg>")
    return "\n".join(o)


def main() -> None:
    for lang in TEXT:
        (HERE / f"architecture_{lang}.svg").write_text(build(lang), encoding="utf-8")
    if "--png" in sys.argv:
        chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        for lang in TEXT:
            svg = HERE / f"architecture_{lang}.svg"
            page = HERE / f".render_{lang}.html"
            page.write_text(f'<html><body style="margin:0;background:{BG}">{svg.read_text(encoding="utf-8")}</body></html>',
                            encoding="utf-8")
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                            f"--window-size={W},{H}", f"--screenshot={HERE / f'architecture_{lang}.png'}", page.as_uri()],
                           check=True, capture_output=True)
            page.unlink()


if __name__ == "__main__":
    main()
