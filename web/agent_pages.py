"""
Pages for the form agent demo (D4a): the status page a decided group opens from LINE, and the demo
venue's reservation form that the agent fills in. Nothing typed into the demo form is stored.
"""

import html
import secrets
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from bot.deps import Deps
from services.store import KEEP

router = APIRouter()

PAGE_STYLE = """
<style>
:root{--bg:#F4F6F9;--card:#FFFFFF;--ink:#1A2130;--muted:#5C6677;--line:#D9DFE7;--green:#06C755;--warn:#A9590B;--ok:#25704B}
@media (prefers-color-scheme: dark){:root{--bg:#11151B;--card:#1A2029;--ink:#E5E9F0;--muted:#9AA4B4;--line:#2B3340;--warn:#F0A34A;--ok:#6CC79A}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"Hiragino Sans","Noto Sans JP",system-ui,sans-serif;line-height:1.6}
main{max-width:480px;margin:0 auto;padding:20px 16px 48px;display:flex;flex-direction:column;gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}
.kicker{font-size:12px;color:var(--muted);margin:0}h1{font-size:20px;margin:2px 0 6px}
.demo{display:inline-block;font-size:11px;font-weight:700;color:var(--warn);border:1px solid var(--warn);border-radius:999px;padding:1px 8px}
dl{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;margin:8px 0 0;font-size:14px}dt{color:var(--muted)}dd{margin:0}
button,.btn{display:block;width:100%;border:0;border-radius:10px;padding:12px;font-size:15px;font-weight:700;background:var(--green);color:#fff;cursor:pointer;text-align:center;text-decoration:none}
button:disabled{opacity:.5}ol{margin:0;padding-left:1.2em;font-size:14px}li+li{margin-top:4px}
img{width:100%;border-radius:10px;border:1px solid var(--line)}.muted{color:var(--muted);font-size:13px}
label{display:block;font-size:13px;color:var(--muted);margin:10px 0 4px}input,select,textarea{width:100%;font:inherit;padding:9px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink)}
.ok{color:var(--ok);font-weight:700}
</style>"""


def _deps(request: Request) -> Deps:
    return request.app.state.deps


async def _run_for(request: Request, token: str) -> tuple[str, dict[str, Any]]:
    deps = _deps(request)
    payload = deps.ids.verify(token)
    if not payload:
        raise HTTPException(404, "このリンクは無効か、有効期限（24時間）が切れています。")
    run = await deps.store.get("agent_runs", payload["r"])
    if not run:
        raise HTTPException(404, "このリンクは無効か、有効期限（24時間）が切れています。")
    return payload["r"], run


def _public(run: dict[str, Any]) -> dict[str, Any]:
    return {"status": run.get("status"), "steps": run.get("steps", []), "screenshot": run.get("screenshot"),
            "result": run.get("result"), "error": run.get("error")}


@router.get("/agent/{token}", response_class=HTMLResponse)
async def agent_page(request: Request, token: str) -> HTMLResponse:
    _, run = await _run_for(request, token)
    shop = run.get("shop") or {}
    e = html.escape
    when = " ".join(x for x in (run.get("day"), run.get("time")) if x) or "未定"
    body = f"""<title>AI予約エージェント（デモ）</title>{PAGE_STYLE}
<main>
  <section class="card">
    <p class="kicker">AI予約エージェント <span class="demo">デモ</span></p>
    <h1>{e(shop.get('name') or '')}</h1>
    <dl><dt>日時</dt><dd>{e(when)}</dd><dt>人数</dt><dd>{e(str(run.get('pax') or ''))}名</dd><dt>名前</dt><dd>{e(run.get('name') or '')}</dd></dl>
  </section>
  <section class="card">
    <p class="muted">AIがブラウザで予約フォームを開き、入力欄を読み取って記入・送信します。入力先は<strong>デモ用の店舗フォーム</strong>で、実在のお店には何も送信しません。本当に予約するときは、LINEの「ホットペッパーで予約」か電話用の台本を使ってください。</p>
    <button id="start" type="button">AIに入力を任せる</button>
  </section>
  <section class="card" id="progress" hidden>
    <p class="kicker" id="status">待機中</p>
    <ol id="steps"></ol>
    <img id="shot" alt="エージェントが操作しているフォームの画面" hidden>
  </section>
</main>
<script>
const token = {token!r};
const btn = document.getElementById('start');
async function refresh() {{
  const r = await fetch(`/agent/${{token}}/status`);
  if (!r.ok) return;
  const d = await r.json();
  render(d);
  if (d.status === 'queued' || d.status === 'running') setTimeout(refresh, 1500);
}}
function render(d) {{
  const labels = {{ready:'まだ始めていません', queued:'ブラウザを起動しています…', running:'入力しています…', done:'完了しました', failed:'うまくいきませんでした'}};
  document.getElementById('progress').hidden = d.status === 'ready';
  btn.disabled = d.status !== 'ready';
  btn.textContent = d.status === 'ready' ? 'AIに入力を任せる' : (d.status === 'done' ? '入力が終わりました' : '実行中…');
  document.getElementById('status').textContent = labels[d.status] || d.status;
  const ol = document.getElementById('steps'); ol.innerHTML = '';
  (d.steps || []).forEach(s => {{ const li = document.createElement('li'); li.textContent = s.t; ol.appendChild(li); }});
  if (d.result) {{ const li = document.createElement('li'); li.className = 'ok'; li.textContent = d.result; ol.appendChild(li); }}
  if (d.error) {{ const li = document.createElement('li'); li.textContent = 'エラー：' + d.error; ol.appendChild(li); }}
  const img = document.getElementById('shot');
  if (d.screenshot) {{ img.src = d.screenshot; img.hidden = false; }}
}}
btn.addEventListener('click', async () => {{
  btn.disabled = true;
  const r = await fetch(`/agent/${{token}}/start`, {{method: 'POST'}});
  const d = await r.json();
  if (!r.ok) {{ alert(d.detail || '開始できませんでした'); btn.disabled = false; return; }}
  render(d); refresh();
}});
refresh();
</script>"""
    return HTMLResponse(body)


@router.post("/agent/{token}/start")
async def agent_start(request: Request, token: str) -> JSONResponse:
    deps = _deps(request)
    run_id, run = await _run_for(request, token)
    if deps.form_agent is None:
        raise HTTPException(503, "フォーム入力エージェントは現在停止中です。")
    if run.get("status") != "ready":
        return JSONResponse(_public(run))

    def claim(docs):
        doc = docs[0]
        if not doc or doc.get("status") != "ready":
            return [KEEP], False
        return [dict(doc, status="queued", queued_at=deps.clock())], True

    if not await deps.store.transact([("agent_runs", run_id)], claim):
        return JSONResponse(_public(await deps.store.get("agent_runs", run_id) or {}))
    if not await deps.usage.take("agent"):
        await deps.store.set("agent_runs", run_id, dict(run, status="ready"))
        raise HTTPException(429, "本日のデモ実行回数の上限に達しました。明日またお試しください。")
    if not await deps.form_agent.launch(run_id):
        await deps.store.set("agent_runs", run_id, dict(run, status="failed", error="起動に失敗しました"))
    return JSONResponse(_public(await deps.store.get("agent_runs", run_id) or {}))


@router.get("/agent/{token}/status")
async def agent_status(request: Request, token: str) -> JSONResponse:
    _, run = await _run_for(request, token)
    return JSONResponse(_public(run))


def _time_options() -> str:
    slots = [f"{h:02d}:{m:02d}" for h in range(11, 23) for m in (0, 30)]
    return "".join(f'<option value="{s}">{s}</option>' for s in slots)


@router.get("/demo-venue/{shop_id}", response_class=HTMLResponse)
async def demo_venue_form(shop_id: str, n: str = "") -> HTMLResponse:
    e = html.escape
    people = "".join(f'<option value="{i}">{i}名</option>' for i in range(1, 11))
    return HTMLResponse(f"""<title>ご予約フォーム（デモ）</title>{PAGE_STYLE}
<main>
  <section class="card">
    <p class="kicker">ご予約フォーム <span class="demo">デモ店舗</span></p>
    <h1>{e(n or 'デモ店舗')}</h1>
    <p class="muted">AsobiAgentのデモ用フォームです。送信しても実際のお店には届きません。</p>
    <form method="post">
      <label for="f-date">ご来店日</label><input id="f-date" name="visit_date" type="date" required>
      <label for="f-time">ご来店時間</label><select id="f-time" name="visit_time" required>{_time_options()}</select>
      <label for="f-people">人数</label><select id="f-people" name="guests" required>{people}</select>
      <label for="f-name">お名前</label><input id="f-name" name="guest_name" type="text" required>
      <label for="f-tel">電話番号（任意）</label><input id="f-tel" name="tel" type="tel">
      <label for="f-note">ご要望</label><textarea id="f-note" name="request" rows="2"></textarea>
      <p></p><button type="submit">この内容で予約する</button>
    </form>
  </section>
</main>""")


@router.post("/demo-venue/{shop_id}", response_class=HTMLResponse)
async def demo_venue_submit(shop_id: str, n: str = "", visit_date: str = Form(""), visit_time: str = Form(""),
                            guests: str = Form(""), guest_name: str = Form("")) -> HTMLResponse:
    e = html.escape
    ref = "DEMO-" + secrets.token_hex(3).upper()
    return HTMLResponse(f"""<title>受付完了（デモ）</title>{PAGE_STYLE}
<main><section class="card">
  <p class="kicker">ご予約フォーム <span class="demo">デモ店舗</span></p>
  <h1 data-confirmation>デモ予約を受け付けました（{ref}）：{e(visit_date)} {e(visit_time)}・{e(guests)}名・{e(guest_name)}様</h1>
  <p class="muted">これはデモです。実際のお店には届いていません。</p>
</section></main>""")
