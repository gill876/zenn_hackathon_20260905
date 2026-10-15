/**
 * AsobiAgent web simulator.
 *
 * Public visitors can replay the preset group chats: the server runs the real pipeline (Ekispert hub,
 * HotPepper venues) with rule-based reading instead of the LLM. Free-text chat runs the full LLM
 * pipeline and needs the admin token (open the page once with ?admin=<token>) or the judges' shared code.
 * Choosing a venue opens 予約の準備: a call script, the HotPepper page, and the demo form agent.
 * As in LINE, "別の候補を見る" pages through the shortlist and "💡 お店を提案する" adds a place by name.
 * Nothing here places a phone call or claims a booking was made.
 */

document.addEventListener("DOMContentLoaded", () => {
  const $ = (id) => document.getElementById(id);
  const chatBody = $("chatBody");
  const chatInput = $("chatInput");
  const sendBtn = $("sendBtn");
  const senderSelect = $("senderSelect");
  const scenarioSelect = $("scenarioSelect");
  const runScenarioBtn = $("runScenarioBtn");
  const resetBtn = $("resetBtn");
  const metricHubStation = $("metricHubStation");
  const metricMaxTime = $("metricFairnessScore");
  const metricSpread = $("metricSpread");
  const metricAvgTime = $("metricAvgTime");
  const ekispertPayloadView = $("ekispertPayloadView");
  const fairnessBars = $("fairnessBars");
  const llmPayloadView = $("llmPayloadView");
  const agentLogStream = $("agentLogStream");
  const stepBoxes = { agent_1: $("stepAgent1"), agent_2: $("stepAgent2"), agent_3: $("stepAgent3"), agent_4: $("stepAgent4") };
  const modal = $("voiceCallModal");
  const modalTitle = $("callVenueTitle");
  const modalSub = $("callVenuePhone");
  const modalBody = $("callDialogueBox");
  const closeModalBtn = $("closeCallModalBtn");
  const readAloud = $("enableTtsAudio");

  // Admin token for live free-text chat: ?admin=<token> once, then kept for this tab only.
  try {
    const fromUrl = new URLSearchParams(location.search).get("admin");
    if (fromUrl) {
      sessionStorage.setItem("asobiAdminToken", fromUrl);
      history.replaceState(null, "", location.pathname);
    }
  } catch (e) { /* storage blocked: free text stays locked */ }
  const adminToken = () => { try { return sessionStorage.getItem("asobiAdminToken") || ""; } catch (e) { return ""; } };

  // Judges' shared code for live free-text chat, typed into the input bar; kept for this tab only.
  const accessInput = $("accessCode");
  try { accessInput.value = sessionStorage.getItem("asobiAccessCode") || ""; } catch (e) { /* storage blocked */ }
  accessInput.addEventListener("change", () => {
    try { sessionStorage.setItem("asobiAccessCode", accessInput.value.trim()); } catch (e) { /* storage blocked */ }
  });

  let history_ = [];   // messages in the current simulated chat
  let lastPlan = null; // day/time/pax/organizer/hub/page from the last pipeline run
  let lastRun = null;  // {scenario_id} or {messages}: what to re-run for the next page of venues
  let suggestMode = false;
  let suggestCount = 0;
  const MAX_SUGGESTIONS = 3;
  const inputPlaceholder = chatInput.placeholder;

  function endSuggestMode() {
    suggestMode = false;
    chatInput.placeholder = inputPlaceholder;
    chatInput.classList.remove("suggest-mode");
  }

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $(btn.getAttribute("data-tab"))?.classList.add("active");
    });
  });

  resetBtn.addEventListener("click", () => {
    history_ = [];
    lastPlan = null;
    lastRun = null;
    suggestCount = 0;
    endSuggestMode();
    chatBody.innerHTML = '<div class="chat-date-separator"><span>今日</span></div>';
    resetTelemetryUI();
    addLogEntry("リセットしました。");
  });

  function resetTelemetryUI() {
    metricHubStation.textContent = "-";
    metricMaxTime.textContent = "-";
    metricSpread.textContent = "-";
    metricAvgTime.textContent = "-";
    ekispertPayloadView.textContent = "// 駅すぱあとの探索結果がここに表示されます";
    llmPayloadView.textContent = "// 読み取った日時・希望がここに表示されます";
    fairnessBars.innerHTML = '<p class="empty-hint">集合駅が決まるとグラフが表示されます</p>';
    Object.values(stepBoxes).forEach((sb) => {
      sb.className = "step-box";
      sb.querySelector(".step-status").textContent = "未実行";
    });
    stepBoxes.agent_1.classList.add("active");
    stepBoxes.agent_1.querySelector(".step-status").textContent = "待機中";
  }

  // ---- free-text chat (admin or judges' code) ---------------------------------------------------------------
  sendBtn.addEventListener("click", () => handleSendMessage());
  chatInput.addEventListener("keypress", (e) => { if (e.key === "Enter") handleSendMessage(); });

  async function handleSendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;
    if (suggestMode) return handleSuggest(text);
    const sender = senderSelect.value;
    chatInput.value = "";
    appendUserBubble(sender, text);
    history_.push({ sender, text });
    updatePipelineStep("agent_1", "active", "解析中…");
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Admin-Token": adminToken(), "X-Access-Code": accessInput.value.trim() },
        body: JSON.stringify({ messages: history_ }),
      });
      const data = await res.json();
      if (!res.ok) {
        appendSystemText(data.detail || "送信できませんでした。");
        updatePipelineStep("agent_1", "", "未実行");
        return;
      }
      lastRun = { messages: [...history_] };
      suggestCount = 0;
      renderBackendResponse(data);
    } catch (err) {
      appendSystemText("通信エラーが発生しました。");
    }
  }

  // ---- "💡 お店を提案する": a place by name, looked up near the meeting station ------------------------------
  async function handleSuggest(text) {
    chatInput.value = "";
    endSuggestMode();
    appendUserBubble(senderSelect.value, `提案 ${text}`);
    const typing = appendBotBubble("集合駅の近くでお店を探しています…", true);
    try {
      const res = await fetch("/api/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, hub: (lastPlan && lastPlan.hub) || {}, n: suggestCount + 1, sender: senderSelect.value }),
      });
      const data = await res.json();
      typing.remove();
      if (!res.ok) {
        appendSystemText(data.detail || "見つかりませんでした。");
        return;
      }
      suggestCount += 1;
      if (lastPlan) lastPlan.walk = { ...(lastPlan.walk || {}), [data.venue.id]: data.venue.walk_min };
      (data.bot_messages || []).forEach((bm) => appendFlexMessage(bm.flex));
      addLogEntry(`[Agent 3] 提案「${data.venue.name}」を集合駅の近くで照合し、候補に追加`);
    } catch (err) {
      typing.remove();
      appendSystemText("通信エラーが発生しました。");
    }
  }

  // ---- "別の候補を見る": the next page of the same shortlist -------------------------------------------------
  async function showMoreVenues() {
    if (!lastRun || !lastPlan) return;
    if ((lastPlan.page || 0) + 1 >= (lastPlan.pages || 1)) {
      appendSystemText("ほかの候補はもうありません。");
      return;
    }
    appendUserBubble(senderSelect.value, "別の候補を見る");
    const typing = appendBotBubble("ほかの候補を出しています…", true);
    try {
      const res = await fetch("/api/more", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Admin-Token": adminToken(), "X-Access-Code": accessInput.value.trim() },
        body: JSON.stringify({ ...lastRun, page: (lastPlan.page || 0) + 1 }),
      });
      const data = await res.json();
      typing.remove();
      if (!res.ok) {
        appendSystemText(data.detail || "表示できませんでした。");
        return;
      }
      (data.bot_messages || []).forEach((bm) => {
        if (bm.type === "flex") appendFlexMessage(bm.flex);
        else if (bm.text) appendBotBubble(bm.text);
      });
      if (data.plan) {
        lastPlan = { ...lastPlan, page: data.plan.page, pages: data.plan.pages,
                     walk: { ...(lastPlan.walk || {}), ...(data.plan.walk || {}) } };
        addLogEntry(`[Agent 3] 同じ候補リストの${data.plan.page + 1}/${data.plan.pages}ページ目を表示`);
      }
    } catch (err) {
      typing.remove();
      appendSystemText("通信エラーが発生しました。");
    }
  }

  // ---- preset scenarios (public) -----------------------------------------------------------------
  const clientScenarios = {
    tokyo_meat_4: [
      { sender: "佐藤", text: "みんな来週土曜日の昼13時くらいから空いてる？ご飯行こうよ！" },
      { sender: "鈴木", text: "土曜13時空いてるよ！最近どこも混んでるから、渋谷や新宿の混雑は避けたいな〜" },
      { sender: "田中", text: "いいね！美味しいお肉かバル系食べたい！ちなみに私「中目黒」から行くよ" },
      { sender: "鈴木", text: "俺は「吉祥寺」から向かう！" },
      { sender: "佐藤", text: "了解！俺は「横浜」から乗るから、みんなが来やすい場所がいいな" },
      { sender: "高橋", text: "参加する！「柏」から向かうから常磐線・上野東京ライン使えると嬉しい" },
    ],
    cafe_girls_3: [
      { sender: "美咲", text: "今度の日曜14時にゆっくりお茶しない？" },
      { sender: "結衣", text: "行きたい！落ち着いておしゃべりできる静かなカフェがいいな。私は「三軒茶屋」から行くよ" },
      { sender: "陽菜", text: "賛成！私は「北千住」から日比谷線で向かうね" },
      { sender: "美咲", text: "私は「恵比寿」！真ん中あたりの穴場探そう" },
    ],
    craft_beer_3: [
      { sender: "健太", text: "金曜日の19時に仕事終わりにクラフトビール飲みに行かない？" },
      { sender: "大輔", text: "最高！俺は「大宮」から京浜東北で向かうよ" },
      { sender: "翔平", text: "俺は「品川」で退勤予定！" },
      { sender: "健太", text: "俺は「立川」の中央線だから、ちょうど真ん中がいいな" },
    ],
  };

  runScenarioBtn.addEventListener("click", async () => {
    const scenarioId = scenarioSelect.value;
    runScenarioBtn.disabled = true;
    runScenarioBtn.textContent = "⏳ 実行中...";
    chatBody.innerHTML = '<div class="chat-date-separator"><span>今日</span></div>';
    resetTelemetryUI();
    history_ = [...(clientScenarios[scenarioId] || [])];
    lastRun = { scenario_id: scenarioId };
    suggestCount = 0;
    endSuggestMode();
    for (const msg of history_) {
      appendUserBubble(msg.sender, msg.text);
      await new Promise((r) => setTimeout(r, 200));
    }
    updatePipelineStep("agent_1", "active", "出発駅・日時を読み取り中…");
    const typing = appendBotBubble("駅すぱあとで集合駅を計算して、近くのお店を探しています…", true);
    try {
      const res = await fetch("/api/scenario", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_id: scenarioId }),
      });
      const data = await res.json();
      typing.remove();
      if (!res.ok) {
        appendSystemText(data.detail || "実行できませんでした。");
        return;
      }
      renderBackendResponse(data);
    } catch (err) {
      typing.remove();
      appendSystemText("通信エラーが発生しました。");
    } finally {
      runScenarioBtn.disabled = false;
      runScenarioBtn.textContent = "▶ シナリオ自動実行";
    }
  });

  // ---- rendering the pipeline result -------------------------------------------------------------
  function renderBackendResponse(data) {
    const state = data.session_state || {};
    lastPlan = data.plan || lastPlan;
    (data.bot_messages || []).forEach((bm) => {
      if (bm.type === "flex") appendFlexMessage(bm.flex);
      else if (bm.text) appendBotBubble(bm.text);
    });

    const sd = state.schedule_data;
    if (sd) {
      const d = sd.details || {};
      llmPayloadView.textContent = JSON.stringify({
        reading: d.source === "llm" ? "LLM（Gemini on Vertex AI。障害時は GMI Cloud）" : "ルールベース（このページではLLMを使いません）",
        members: sd.members, origins: sd.origins, day: d.day, time: d.time, meal: d.meal,
        preferences: d.preferences, hotpepper_genre: d.genre, keyword: d.keyword,
      }, null, 2);
      updatePipelineStep("agent_1", "completed", `${Object.keys(sd.origins || {}).length}人の出発駅`);
    }

    const mp = state.midpoint_data;
    if (mp) {
      metricHubStation.textContent = mp.hub_station + "駅";
      metricMaxTime.textContent = mp.max_travel_time + "分";
      metricSpread.textContent = mp.spread_minutes + "分";
      metricAvgTime.textContent = "約" + mp.avg_travel_time + "分";
      ekispertPayloadView.textContent = JSON.stringify({
        method: "ekispert_api_search_ranges（平均所要時間・時刻表不使用）",
        hub_station: mp.hub_station, max_minutes: mp.max_travel_time, spread_minutes: mp.spread_minutes,
        average_minutes: mp.avg_travel_time, members: mp.members, runners_up: mp.alternatives,
      }, null, 2);
      renderFairnessBars(mp.members);
      updatePipelineStep("agent_2", "completed", `集合駅: ${mp.hub_station}`);
    }
    if (state.venues && state.venues.length) {
      updatePipelineStep("agent_3", "completed", `候補${state.venues.length}軒`);
      updatePipelineStep("agent_4", "active", "お店を選んでください");
    }
    if (state.agent_logs) {
      agentLogStream.innerHTML = "";
      state.agent_logs.forEach((log) => addLogEntry(`[${log.agent_name}] ${log.step}`));
    }
    scrollChatToBottom();
  }

  function renderFairnessBars(members) {
    if (!members) return;
    const max = Math.max(10, ...Object.values(members).map((m) => m.travel_time || 0));
    const scale = Math.ceil(max / 10) * 10;
    fairnessBars.innerHTML = Object.entries(members).map(([name, info]) => {
      const pct = Math.round(((info.travel_time || 0) / scale) * 100);
      return `
        <div class="fairness-bar-item">
          <div class="bar-meta">
            <span><strong>${escapeHtml(name)}</strong>（${escapeHtml(info.origin)}駅発・乗換${info.transfers}回）</span>
            <span style="color:#4ADE80;font-weight:bold;">${info.travel_time}分</span>
          </div>
          <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
        </div>`;
    }).join("") + `<p class="empty-hint">目盛り：0〜${scale}分（駅すぱあとの平均所要時間）</p>`;
  }

  function updatePipelineStep(agentId, statusClass, statusText) {
    const sb = stepBoxes[agentId];
    if (!sb) return;
    sb.className = `step-box ${statusClass}`;
    sb.querySelector(".step-status").textContent = statusText;
  }

  function addLogEntry(text) {
    const div = document.createElement("div");
    div.className = "log-entry";
    div.textContent = text;
    agentLogStream.prepend(div);
  }

  // ---- chat bubbles ------------------------------------------------------------------------------
  const avatars = { "佐藤": "👨‍💼", "鈴木": "🧑‍💻", "田中": "👩‍🎨", "高橋": "🏃‍♂️", "美咲": "👩‍🦰", "結衣": "👱‍♀️",
                    "陽菜": "👩‍🏫", "健太": "👨‍🔧", "大輔": "👨‍🔬", "翔平": "⚾" };

  function appendUserBubble(sender, text) {
    const isMain = sender === "佐藤";
    const row = document.createElement("div");
    row.className = `chat-row ${isMain ? "user-row" : "other-row"}`;
    const time = getCurrentTime();
    row.innerHTML = isMain
      ? `<div class="chat-timestamp">${time}</div>
         <div class="chat-bubble-container"><div class="chat-bubble user">${escapeHtml(text)}</div></div>`
      : `<div class="chat-avatar">${avatars[sender] || "👤"}</div>
         <div class="chat-bubble-container"><div class="sender-name">${escapeHtml(sender)}</div>
         <div class="chat-bubble other">${escapeHtml(text)}</div></div>
         <div class="chat-timestamp">${time}</div>`;
    chatBody.appendChild(row);
    scrollChatToBottom();
  }

  function appendBotBubble(text, pending = false) {
    const row = document.createElement("div");
    row.className = "chat-row other-row";
    row.innerHTML = `
      <div class="chat-avatar" style="background:#06C755;color:#fff;">🤖</div>
      <div class="chat-bubble-container">
        <div class="sender-name" style="color:#06C755;">AsobiAgent</div>
        <div class="chat-bubble other" style="border:1px ${pending ? "dashed" : "solid"} #06C755;">${escapeHtml(text)}</div>
      </div>
      <div class="chat-timestamp">${getCurrentTime()}</div>`;
    chatBody.appendChild(row);
    scrollChatToBottom();
    return row;
  }

  function appendSystemText(text) {
    const row = document.createElement("div");
    row.className = "chat-date-separator";
    row.innerHTML = `<span>${escapeHtml(text)}</span>`;
    chatBody.appendChild(row);
    scrollChatToBottom();
  }

  // ---- LINE Flex renderer (the subset the bot uses) ----------------------------------------------
  function appendFlexMessage(flexObj) {
    const row = document.createElement("div");
    row.className = "chat-row other-row";
    const content = flexObj.contents;
    const cardHtml = content.type === "carousel"
      ? `<div class="flex-carousel-container">${content.contents.map((b) => `<div class="carousel-slide">${renderBubble(b)}</div>`).join("")}</div>`
      : renderBubble(content);
    row.innerHTML = `
      <div class="chat-avatar" style="background:#06C755;color:#fff;">🤖</div>
      <div class="chat-bubble-container" style="max-width:90%;">
        <div class="sender-name" style="color:#06C755;">AsobiAgent</div>${cardHtml}
      </div>`;
    chatBody.appendChild(row);
    row.querySelectorAll(".flex-action-btn").forEach((btn) => btn.addEventListener("click", () => onCardButton(btn)));
    scrollChatToBottom();
  }

  function renderBubble(b) {
    const hero = b.hero && b.hero.type === "image"
      ? `<img src="${escapeAttr(b.hero.url)}" alt="" style="width:100%;aspect-ratio:20/13;object-fit:cover;display:block;">` : "";
    const part = (box, cls) => box ? `<div class="${cls}">${renderContents(box.contents)}</div>` : "";
    return `<div class="flex-bubble-card">${hero}${part(b.header, "flex-card-header")}${part(b.body, "flex-card-body")}${part(b.footer, "flex-card-footer")}</div>`;
  }

  const sizes = { xxs: "10px", xs: "11px", sm: "12px", md: "14px", lg: "16px", xl: "19px", xxl: "24px" };

  function renderContents(contents) {
    if (!contents) return "";
    return contents.map((item) => {
      if (item.type === "text") {
        const style = [
          item.color ? `color:${item.color}` : "", item.weight === "bold" ? "font-weight:bold" : "",
          item.align ? `text-align:${item.align}` : "", `font-size:${sizes[item.size] || "12px"}`,
          item.flex !== undefined ? `flex:${item.flex}` : "", "margin:2px 0",
        ].filter(Boolean).join(";");
        return `<p style="${style}">${escapeHtml(item.text)}</p>`;
      }
      if (item.type === "box") {
        const horizontal = item.layout === "horizontal";
        const style = [
          horizontal ? "display:flex;gap:6px;align-items:center" : "display:flex;flex-direction:column",
          item.backgroundColor ? `background:${item.backgroundColor}` : "",
          item.width ? `width:${item.width}` : "", item.height ? `height:${item.height}` : "",
          item.cornerRadius ? `border-radius:${item.cornerRadius}` : "",
          item.flex !== undefined ? `flex:${item.flex}` : "", item.margin ? "margin-top:6px" : "",
          item.justifyContent === "center" ? "justify-content:center" : "",
        ].filter(Boolean).join(";");
        return `<div style="${style}">${renderContents(item.contents)}</div>`;
      }
      if (item.type === "button") {
        const a = item.action || {};
        if (a.type === "uri") {
          return `<a class="flex-action-btn" href="${escapeAttr(a.uri)}" target="_blank" rel="noopener">${escapeHtml(a.label)}</a>`;
        }
        return `<button class="flex-action-btn" data-action="${escapeAttr(a.data || "")}">${escapeHtml(a.label || "選択")}</button>`;
      }
      return "";
    }).join("");
  }

  function onCardButton(btn) {
    if (btn.tagName === "A") return; // links open on their own
    const params = new URLSearchParams(btn.getAttribute("data-action") || "");
    const action = params.get("a");
    if (action === "vote") {
      showReservationPrep(params.get("v"));
    } else if (action === "more") {
      showMoreVenues();
    } else if (action === "suggest") {
      if (suggestCount >= MAX_SUGGESTIONS) {
        appendSystemText(`お店の提案は${MAX_SUGGESTIONS}件までです。`);
        return;
      }
      suggestMode = true;
      chatInput.placeholder = "行きたいお店の名前（例：肉ごこち 秋葉原）";
      chatInput.classList.add("suggest-mode");
      appendSystemText("💡 行きたいお店の名前を送ってください。集合駅の近くで探して、候補に加えます。");
      chatInput.focus();
    } else {
      appendSystemText("この操作はLINE版で使えます（このページでは投票・別の候補・お店の提案が使えます）。");
    }
  }

  // ---- 予約の準備 (replaces the old simulated AI phone call) ----------------------------------------
  async function showReservationPrep(venueId) {
    updatePipelineStep("agent_4", "active", "予約の準備中…");
    try {
      const res = await fetch("/api/reserve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ venue_id: venueId, plan: lastPlan || {} }),
      });
      const data = await res.json();
      if (!res.ok) {
        appendSystemText(data.detail || "準備できませんでした。");
        return;
      }
      (data.bot_messages || []).forEach((bm) => appendFlexMessage(bm.flex));
      modalTitle.textContent = data.shop.name;
      modalSub.textContent = "まだ予約は完了していません。下のどれかで予約してください。";
      const lines = data.script.lines.map((l) => `<div class="call-turn turn-ai"><span>${escapeHtml(l)}</span></div>`).join("");
      const links = [
        data.shop.url ? `<a class="btn btn-primary" href="${escapeAttr(data.shop.url)}" target="_blank" rel="noopener">ホットペッパーで予約</a>` : "",
        data.agent_url ? `<a class="btn btn-secondary" href="${escapeAttr(data.agent_url)}" target="_blank" rel="noopener">AIに入力を任せる（デモ）</a>` : "",
      ].join("");
      modalBody.innerHTML = `
        <p class="turn-speaker">電話で予約する場合の台本（幹事が読み上げます）</p>${lines}
        <div class="call-turn turn-staff"><span>満席なら：${escapeHtml(data.script.if_full)}</span></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;">${links}</div>`;
      modal.classList.add("active");
      updatePipelineStep("agent_4", "completed", "台本とリンクを用意");
      if (readAloud.checked && "speechSynthesis" in window) {
        data.script.lines.forEach((l) => {
          const u = new SpeechSynthesisUtterance(l.replace(/[「」]/g, ""));
          u.lang = "ja-JP";
          window.speechSynthesis.speak(u);
        });
      }
    } catch (e) {
      appendSystemText("通信エラーが発生しました。");
    }
  }

  closeModalBtn.addEventListener("click", () => {
    modal.classList.remove("active");
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  });

  function scrollChatToBottom() { chatBody.scrollTop = chatBody.scrollHeight; }
  function getCurrentTime() {
    const now = new Date();
    return `${now.getHours()}:${String(now.getMinutes()).padStart(2, "0")}`;
  }
  function escapeHtml(str) {
    return String(str ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function escapeAttr(str) {
    return escapeHtml(str).replace(/"/g, "&quot;");
  }
});
