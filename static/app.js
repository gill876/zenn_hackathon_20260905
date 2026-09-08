/**
 * AsobiAgent Hackathon Live Demo Application
 * Handles LINE chat simulation, Multi-Agent pipeline orchestration,
 * Ekispert telemetry visualization, and Autonomous Voice Call simulation.
 */

document.addEventListener("DOMContentLoaded", () => {
  // DOM Elements
  const chatBody = document.getElementById("chatBody");
  const chatInput = document.getElementById("chatInput");
  const sendBtn = document.getElementById("sendBtn");
  const senderSelect = document.getElementById("senderSelect");
  const scenarioSelect = document.getElementById("scenarioSelect");
  const runScenarioBtn = document.getElementById("runScenarioBtn");
  const resetBtn = document.getElementById("resetBtn");

  // Tab elements
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabPanes = document.querySelectorAll(".tab-pane");

  // Telemetry elements
  const metricHubStation = document.getElementById("metricHubStation");
  const metricFairnessScore = document.getElementById("metricFairnessScore");
  const metricSpread = document.getElementById("metricSpread");
  const metricAvgTime = document.getElementById("metricAvgTime");
  const ekispertPayloadView = document.getElementById("ekispertPayloadView");
  const fairnessBars = document.getElementById("fairnessBars");
  const llmPayloadView = document.getElementById("llmPayloadView");
  const agentLogStream = document.getElementById("agentLogStream");

  // Pipeline Step Boxes
  const stepBoxes = {
    agent_1: document.getElementById("stepAgent1"),
    agent_2: document.getElementById("stepAgent2"),
    agent_3: document.getElementById("stepAgent3"),
    agent_4: document.getElementById("stepAgent4")
  };

  // Voice Call Modal elements
  const voiceCallModal = document.getElementById("voiceCallModal");
  const callVenueTitle = document.getElementById("callVenueTitle");
  const callVenuePhone = document.getElementById("callVenuePhone");
  const callTimer = document.getElementById("callTimer");
  const callDialogueBox = document.getElementById("callDialogueBox");
  const closeCallModalBtn = document.getElementById("closeCallModalBtn");
  const enableTtsAudio = document.getElementById("enableTtsAudio");

  let callTimerInterval = null;

  // Tab Switching
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetTab = btn.getAttribute("data-tab");
      tabBtns.forEach(b => b.classList.remove("active"));
      tabPanes.forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(targetTab)?.classList.add("active");
    });
  });

  // Reset Session
  resetBtn.addEventListener("click", async () => {
    try {
      await fetch("/api/reset", { method: "POST" });
      chatBody.innerHTML = '<div class="chat-date-separator"><span>今日</span></div>';
      resetTelemetryUI();
      addLogEntry("システムがリセットされました。");
    } catch (e) {
      console.error(e);
    }
  });

  function resetTelemetryUI() {
    metricHubStation.textContent = "-";
    metricFairnessScore.textContent = "-";
    metricSpread.textContent = "-";
    metricAvgTime.textContent = "-";
    ekispertPayloadView.textContent = "// 駅すぱあとAPIの呼出結果がここに表示されます";
    llmPayloadView.textContent = "// GMI LLMの推論結果がここに表示されます";
    fairnessBars.innerHTML = '<p class="empty-hint">中間駅が算出されるとグラフが表示されます</p>';
    Object.values(stepBoxes).forEach(sb => {
      sb.className = "step-box";
      sb.querySelector(".step-status").textContent = "未実行";
    });
    stepBoxes.agent_1.classList.add("active");
    stepBoxes.agent_1.querySelector(".step-status").textContent = "待機中";
  }

  // Send User Message
  sendBtn.addEventListener("click", () => handleSendMessage());
  chatInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") handleSendMessage();
  });

  async function handleSendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;
    const sender = senderSelect.value;
    chatInput.value = "";

    // Append user message immediately
    appendUserBubble(sender, text);

    // Show typing status on Agent 1
    updatePipelineStep("agent_1", "active", "解析実行中...");

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sender, text })
      });
      const data = await res.json();
      renderBackendResponse(data);
    } catch (err) {
      console.error("Chat error:", err);
      appendSystemText("通信エラーが発生しました。");
    }
  }

  // Client-side scenario scripts for instant visual rendering
  const clientScenarios = {
    tokyo_meat_4: [
      { sender: "佐藤", text: "みんな来週土曜日の昼13時くらいから空いてる？ご飯行こうよ！" },
      { sender: "鈴木", text: "土曜13時空いてるよ！最近どこも混んでるから、渋谷や新宿の混雑は避けたいな〜" },
      { sender: "田中", text: "いいね！美味しいお肉かバル系食べたい！ちなみに私「中目黒」から行くよ" },
      { sender: "鈴木", text: "俺は「吉祥寺」から向かう！" },
      { sender: "佐藤", text: "了解！俺は「横浜」から乗るから、みんなが来やすい場所がいいな" },
      { sender: "高橋", text: "参加する！「柏」から向かうから常磐線・上野東京ライン使えると嬉しい" }
    ],
    cafe_girls_3: [
      { sender: "美咲", text: "今度の日曜14時にゆっくりお茶しない？" },
      { sender: "結衣", text: "行きたい！落ち着いておしゃべりできる静かなカフェがいいな。私は「三軒茶屋」から行くよ" },
      { sender: "陽菜", text: "賛成！私は「北千住」から日比谷線で向かうね" },
      { sender: "美咲", text: "私は「恵比寿」！真ん中あたりの穴場探そう" }
    ],
    craft_beer_3: [
      { sender: "健太", text: "金曜日の19時に仕事終わりにクラフトビール飲みに行かない？" },
      { sender: "大輔", text: "最高！俺は「大宮」から京浜東北で向かうよ" },
      { sender: "翔平", text: "俺は「品川」で退勤予定！" },
      { sender: "健太", text: "俺は「立川」の中央線だから、ちょうど真ん中がいいな" }
    ]
  };

  // Run Preset Scenario
  runScenarioBtn.addEventListener("click", async () => {
    const scenarioId = scenarioSelect.value;
    runScenarioBtn.disabled = true;
    runScenarioBtn.textContent = "⏳ 実行中...";
    chatBody.innerHTML = '<div class="chat-date-separator"><span>今日</span></div>';
    resetTelemetryUI();

    const inputMsgs = clientScenarios[scenarioId] || clientScenarios["tokyo_meat_4"];

    // 1. Immediately animate messages into the chat
    for (const msg of inputMsgs) {
      appendUserBubble(msg.sender, msg.text);
      await new Promise(r => setTimeout(r, 220));
    }

    // 2. Show typing indicator and activate pipeline
    updatePipelineStep("agent_1", "active", "会話・出発駅を解析中...");
    const typingRow = document.createElement("div");
    typingRow.id = "typingIndicator";
    typingRow.className = "chat-row other-row";
    typingRow.innerHTML = `
      <div class="chat-avatar" style="background:#06C755; color:#fff;">🤖</div>
      <div class="chat-bubble-container">
        <div class="sender-name" style="color:#06C755;">AsobiAgent</div>
        <div class="chat-bubble other" style="border: 1px dashed #06C755; color: #64748B;">
          ⚡ 駅すぱあと中間駅・混雑回避スポットを自律計算中...
        </div>
      </div>
    `;
    chatBody.appendChild(typingRow);
    scrollChatToBottom();

    try {
      const res = await fetch("/api/scenario", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_id: scenarioId })
      });
      const data = await res.json();

      // Remove typing indicator
      const ti = document.getElementById("typingIndicator");
      if (ti) ti.remove();

      // Render all bot cards and telemetry
      renderBackendResponse(data);
    } catch (err) {
      console.error("Scenario error:", err);
      const ti = document.getElementById("typingIndicator");
      if (ti) ti.remove();
    } finally {
      runScenarioBtn.disabled = false;
      runScenarioBtn.textContent = "▶ シナリオ自動実行";
    }
  });


  // Render Bot Response & Telemetry
  function renderBackendResponse(data) {
    const state = data.session_state || {};
    const botMessages = data.bot_messages || [];

    // Append bot messages into chat
    botMessages.forEach(bm => {
      if (bm.type === "flex") {
        appendFlexMessage(bm.flex);
      } else if (bm.text) {
        appendBotBubble(bm.text);
      }
    });

    // Update Telemetry if Midpoint exists
    if (state.midpoint_data) {
      const mp = state.midpoint_data;
      metricHubStation.textContent = mp.hub_station + "駅";
      metricFairnessScore.textContent = mp.fairness_score + "点";
      metricSpread.textContent = "±" + mp.spread_minutes + "分";
      metricAvgTime.textContent = "約" + mp.avg_travel_time + "分";

      // Render Ekispert Payload
      ekispertPayloadView.textContent = JSON.stringify({
        compliance: "NON_TIMETABLE_AVERAGE_ROUTE",
        hub_station: mp.hub_station,
        fairness_score: mp.fairness_score,
        spread_minutes: mp.spread_minutes,
        avg_travel_time: mp.avg_travel_time,
        member_routes: mp.members,
        alternative_hubs: mp.alternatives
      }, null, 2);

      // Render Fairness Bars
      renderFairnessBars(mp.members);

      updatePipelineStep("agent_1", "completed", "抽出完了");
      updatePipelineStep("agent_2", "completed", `中間駅: ${mp.hub_station}`);
    }

    if (state.venues && state.venues.length > 0) {
      updatePipelineStep("agent_3", "completed", `穴場${state.venues.length}選`);
    }

    // Render LLM Payload
    if (state.schedule_data) {
      llmPayloadView.textContent = JSON.stringify(state.schedule_data, null, 2);
    }

    // Append logs
    if (state.agent_logs) {
      agentLogStream.innerHTML = "";
      state.agent_logs.forEach(log => {
        addLogEntry(`[${log.agent_name}] ${log.step}`);
      });
    }

    scrollChatToBottom();
  }

  // Fairness Bars Visualization
  function renderFairnessBars(members) {
    if (!members) return;
    let html = "";
    Object.entries(members).forEach(([name, info]) => {
      const time = info.travel_time || 25;
      const pct = Math.min(100, Math.round((time / 60) * 100));
      html += `
        <div class="fairness-bar-item">
          <div class="bar-meta">
            <span><strong>${name}</strong>（${info.origin}駅発 / 乗換${info.transfers}回）</span>
            <span style="color: #4ADE80; font-weight: bold;">${time}分</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill" style="width: ${pct}%"></div>
          </div>
        </div>
      `;
    });
    fairnessBars.innerHTML = html;
  }

  // Pipeline Step Updaters
  function updatePipelineStep(agentId, statusClass, statusText) {
    const sb = stepBoxes[agentId];
    if (sb) {
      sb.className = `step-box ${statusClass}`;
      sb.querySelector(".step-status").textContent = statusText;
    }
  }

  function addLogEntry(text) {
    const div = document.createElement("div");
    div.className = "log-entry";
    div.textContent = text;
    agentLogStream.prepend(div);
  }

  // LINE Chat Bubble Renderers
  function appendUserBubble(sender, text) {
    const isMainUser = sender === "佐藤";
    const row = document.createElement("div");
    row.className = `chat-row ${isMainUser ? "user-row" : "other-row"}`;

    const avatarMap = {
      "佐藤": "👨‍💼",
      "鈴木": "🧑‍💻",
      "田中": "👩‍🎨",
      "高橋": "🏃‍♂️",
      "美咲": "👩‍🦰",
      "結衣": "👱‍♀️",
      "陽菜": "👩‍🏫",
      "健太": "👨‍🔧",
      "大輔": "👨‍🔬",
      "翔平": "⚾"
    };
    const avatar = avatarMap[sender] || "👤";

    const timeStr = getCurrentTime();

    if (isMainUser) {
      row.innerHTML = `
        <div class="chat-timestamp">${timeStr}</div>
        <div class="chat-bubble-container">
          <div class="chat-bubble user">${escapeHtml(text)}</div>
        </div>
      `;
    } else {
      row.innerHTML = `
        <div class="chat-avatar">${avatar}</div>
        <div class="chat-bubble-container">
          <div class="sender-name">${sender}</div>
          <div class="chat-bubble other">${escapeHtml(text)}</div>
        </div>
        <div class="chat-timestamp">${timeStr}</div>
      `;
    }

    chatBody.appendChild(row);
    scrollChatToBottom();
  }

  function appendBotBubble(text) {
    const row = document.createElement("div");
    row.className = "chat-row other-row";
    row.innerHTML = `
      <div class="chat-avatar" style="background:#06C755; color:#fff;">🤖</div>
      <div class="chat-bubble-container">
        <div class="sender-name" style="color:#06C755;">AsobiAgent</div>
        <div class="chat-bubble other" style="border: 1px solid #06C755;">${escapeHtml(text)}</div>
      </div>
      <div class="chat-timestamp">${getCurrentTime()}</div>
    `;
    chatBody.appendChild(row);
    scrollChatToBottom();
  }

  // Flex Message Renderer
  function appendFlexMessage(flexObj) {
    const row = document.createElement("div");
    row.className = "chat-row other-row";

    const content = flexObj.contents;
    let cardHtml = "";

    if (content.type === "bubble") {
      cardHtml = renderFlexBubble(content);
    } else if (content.type === "carousel") {
      cardHtml = `<div class="flex-carousel-container">` + 
        content.contents.map(b => `<div class="carousel-slide">${renderFlexBubble(b)}</div>`).join("") + 
        `</div>`;
    }

    row.innerHTML = `
      <div class="chat-avatar" style="background:#06C755; color:#fff;">🤖</div>
      <div class="chat-bubble-container" style="max-width: 90%;">
        <div class="sender-name" style="color:#06C755;">AsobiAgent</div>
        ${cardHtml}
      </div>
    `;

    chatBody.appendChild(row);
    attachCardActionHandlers(row);
    scrollChatToBottom();
  }

  function renderFlexBubble(b) {
    let headerHtml = "";
    if (b.header) {
      const bg = b.header.backgroundColor || "#1E293B";
      headerHtml = `<div class="flex-card-header" style="background: ${bg};">
        ${renderBoxContents(b.header.contents)}
      </div>`;
    }

    let bodyHtml = "";
    if (b.body) {
      bodyHtml = `<div class="flex-card-body">
        ${renderBoxContents(b.body.contents)}
      </div>`;
    }

    let footerHtml = "";
    if (b.footer) {
      footerHtml = `<div class="flex-card-footer">
        ${renderBoxContents(b.footer.contents)}
      </div>`;
    }

    return `
      <div class="flex-bubble-card">
        ${headerHtml}
        ${bodyHtml}
        ${footerHtml}
      </div>
    `;
  }

  function renderBoxContents(contents) {
    if (!contents) return "";
    return contents.map(item => {
      if (item.type === "text") {
        const color = item.color ? `color: ${item.color};` : "";
        const weight = item.weight === "bold" ? "font-weight: bold;" : "";
        const align = item.align ? `text-align: ${item.align};` : "";
        const sizeMap = { xs: "11px", sm: "12px", md: "14px", lg: "16px", xl: "18px", xxs: "9.5px" };
        const size = item.size ? `font-size: ${sizeMap[item.size] || "12px"};` : "";
        return `<p style="${color} ${weight} ${align} ${size} margin: 2px 0;">${escapeHtml(item.text)}</p>`;
      } else if (item.type === "box") {
        const isHoriz = item.layout === "horizontal";
        const bg = item.backgroundColor ? `background: ${item.backgroundColor};` : "";
        const pad = item.paddingAll ? `padding: ${item.paddingAll};` : "";
        const radius = item.cornerRadius ? `border-radius: ${item.cornerRadius};` : "";
        const margin = item.margin ? "margin-top: 6px;" : "";
        const display = isHoriz ? "display: flex; justify-content: space-between; align-items: center;" : "display: flex; flex-direction: column;";
        return `<div style="${display} ${bg} ${pad} ${radius} ${margin}">${renderBoxContents(item.contents)}</div>`;
      } else if (item.type === "button") {
        const actionData = item.action?.data || "";
        const label = item.action?.label || "選択";
        return `<button class="flex-action-btn" data-action="${actionData}">${label}</button>`;
      }
      return "";
    }).join("");
  }

  function attachCardActionHandlers(container) {
    const btns = container.querySelectorAll(".flex-action-btn");
    btns.forEach(btn => {
      btn.addEventListener("click", async () => {
        const dataStr = btn.getAttribute("data-action");
        if (!dataStr) return;

        // Parse query string data
        const params = new URLSearchParams(dataStr);
        const action = params.get("action");

        if (action === "reserve") {
          const venueId = params.get("venue_id");
          const venueName = params.get("venue_name");
          startVoiceCallSimulation(venueId, venueName);
        }
      });
    });
  }

  // Voice Call Modal Simulation (Agent 4)
  async function startVoiceCallSimulation(venueId, venueName) {
    voiceCallModal.classList.add("active");
    callVenueTitle.textContent = venueName || "恵比寿 薪火バル CANTE";
    callVenuePhone.textContent = "📞 03-5792-XXXX に架電中...";
    callDialogueBox.innerHTML = "";
    
    updatePipelineStep("agent_4", "active", "店舗へ自律架電中");

    // Start timer
    let sec = 0;
    callTimer.textContent = "00:00";
    clearInterval(callTimerInterval);
    callTimerInterval = setInterval(() => {
      sec++;
      const m = String(Math.floor(sec / 60)).padStart(2, '0');
      const s = String(sec % 60).padStart(2, '0');
      callTimer.textContent = `${m}:${s}`;
    }, 1000);

    try {
      // Call backend to execute reservation
      const res = await fetch("/api/reserve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ venue_id: venueId, organizer: "佐藤" })
      });
      const data = await res.json();
      const reservation = data.reservation;
      const dialogue = reservation.dialogue || [];

      // Sequentially stream dialogue
      for (let i = 0; i < dialogue.length; i++) {
        const turn = dialogue[i];
        await appendCallTurnWithDelay(turn, 1200);
      }

      // Finish call
      clearInterval(callTimerInterval);
      callVenuePhone.textContent = "✅ 通話完了・予約確定！";
      updatePipelineStep("agent_4", "completed", "予約完了 (発信終了)");

      // Auto-append ticket to chat
      if (data.bot_message) {
        appendFlexMessage(data.bot_message.flex);
      }
    } catch (e) {
      console.error(e);
    }
  }

  async function appendCallTurnWithDelay(turn, delayMs) {
    await new Promise(r => setTimeout(r, delayMs));
    const turnDiv = document.createElement("div");
    const isAi = turn.role === "ai";
    turnDiv.className = `call-turn ${isAi ? "turn-ai" : "turn-staff"}`;
    turnDiv.innerHTML = `
      <span class="turn-speaker">${turn.speaker} [${turn.audio_label || ""}]</span>
      <span>${escapeHtml(turn.text)}</span>
    `;
    callDialogueBox.appendChild(turnDiv);
    callDialogueBox.scrollTop = callDialogueBox.scrollHeight;

    // Browser Speech Synthesis (Web Speech TTS)
    if (enableTtsAudio.checked && 'speechSynthesis' in window) {
      try {
        const utterance = new SpeechSynthesisUtterance(turn.text);
        utterance.lang = "ja-JP";
        utterance.rate = isAi ? 1.05 : 1.0;
        utterance.pitch = isAi ? 1.0 : 0.95;
        window.speechSynthesis.speak(utterance);
      } catch (e) {
        // Audio might require user interaction in some browsers
      }
    }
  }

  closeCallModalBtn.addEventListener("click", () => {
    voiceCallModal.classList.remove("active");
    clearInterval(callTimerInterval);
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  });

  // Helpers
  function scrollChatToBottom() {
    chatBody.scrollTop = chatBody.scrollHeight;
  }

  function getCurrentTime() {
    const now = new Date();
    return `${now.getHours()}:${String(now.getMinutes()).padStart(2, '0')}`;
  }

  function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
});
