// Zenon — Aria, AI loan advisor calling on behalf of Jio Financial. Browser client that talks to the FastAPI server over /ws, which proxies the Gemini Live API.

// DOM
const statusDiv = document.getElementById("status");
const statusText = statusDiv.querySelector(".status-text");
const authSection = document.getElementById("auth-section");
const appSection = document.getElementById("app-section");
const sessionEndSection = document.getElementById("session-end-section");
const connectBtn = document.getElementById("connectBtn");
const micBtn = document.getElementById("micBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const restartBtn = document.getElementById("restartBtn");
const textInput = document.getElementById("textInput");
const sendBtn = document.getElementById("sendBtn");
const chatLog = document.getElementById("chat-log");
const callTimerEl = document.getElementById("call-timer");
const orbCaptionEl = document.getElementById("orb-caption");

// Lead card
const leadCard = document.getElementById("lead-card");
const leadEmoji = document.getElementById("lead-emoji");
const leadTitle = document.getElementById("lead-title");
const leadSub = document.getElementById("lead-sub");
const leadProduct = document.getElementById("lead-product");

// Session-end
const endEmoji = document.getElementById("end-emoji");
const endTitle = document.getElementById("end-title");
const endLine = document.getElementById("end-line");
const outcomeBadge = document.getElementById("outcome-badge");
const callSummary = document.getElementById("call-summary");

// Greeting nudge sent on connect so Aria speaks first.
const GREETING_TRIGGER =
  "[The call has just connected. You were NOT given the customer's name — never invent one: skip the name check, greet warmly in Hindi, introduce yourself as Aria from Jio Financial, and ask if they need funds for their business (STEP 2).]";

// Call-outcome display map (keys match the tool result's outcome values).
const OUTCOME_META = {
  yes: {
    label: "Interested — a senior member will call back",
    emoji: "✅",
    tone: "positive",
    sub: "Interest captured on this call.",
    endTitle: "Great news!",
    endLine: "A senior member from Jio Financial will call back to take this forward.",
  },
  no: {
    label: "Not interested",
    emoji: "🙏",
    tone: "neutral",
    sub: "No follow-up planned — thanks for the time.",
    endTitle: "Thanks for your time",
    endLine: "Aria has marked this lead as not interested.",
  },
  callback: {
    label: "Callback requested",
    emoji: "📞",
    tone: "info",
    sub: "Aria has noted a better time to call.",
    endTitle: "We'll call back",
    endLine: "Aria has scheduled a callback at a better time.",
  },
  voicemail: {
    label: "Voicemail",
    emoji: "📨",
    tone: "neutral",
    sub: "The call reached voicemail.",
    endTitle: "We missed you",
    endLine: "The call went to voicemail — Aria will try again later.",
  },
  do_not_contact: {
    label: "Do not contact",
    emoji: "🚫",
    tone: "negative",
    sub: "This number will not be contacted again.",
    endTitle: "Understood",
    endLine: "This number is marked do-not-contact.",
  },
  wrong_number: {
    label: "Wrong number",
    emoji: "❌",
    tone: "neutral",
    sub: "This number doesn't match the intended customer.",
    endTitle: "Wrong number",
    endLine: "This number was marked as a wrong number.",
  },
};

// State
let callStartTime = null;
let callTimerInterval = null;
let orbRAF = null;
let ariaSpeaking = false;
let micStarting = false;
let sessionEnded = false;
let leadData = null; // { outcome, customer_name, loan_interest, note, offer }
let callTranscript = []; // { role: "user"|"gemini", text, time }
let currentUserMsg = null;
let currentGeminiMsg = null;

const mediaHandler = new MediaHandler();
const geminiClient = new GeminiClient({
  onOpen: () => {
    sessionEnded = false;
    setStatus("connected", "On call");
    authSection.classList.add("hidden");
    appSection.classList.remove("hidden");
    sessionEndSection.classList.add("hidden");

    startTimer();
    startOrb();
    setCaption("Connected", "Aria is greeting you…");

    // Let Aria speak first, then open the mic.
    geminiClient.sendText(GREETING_TRIGGER);
    startMic();
  },
  onMessage: (evt) => {
    if (typeof evt.data === "string") {
      try {
        handleJsonMessage(JSON.parse(evt.data));
      } catch (e) {
        console.error("Parse error:", e);
      }
    } else {
      // Binary = agent audio
      if (!ariaSpeaking) {
        ariaSpeaking = true;
        setCaption("Speaking…", "Aria · Zenon");
      }
      mediaHandler.playAudio(evt.data);
    }
  },
  onClose: () => {
    setStatus("disconnected", "Call ended");
    setTimeout(showSessionEnd, 300);
  },
  onError: (e) => {
    console.error("WS error:", e);
    setStatus("error", "Connection error");
  },
});

// Helpers
function setStatus(cls, text) {
  statusDiv.className = "status-badge " + cls;
  statusText.textContent = text;
  statusDiv.setAttribute("aria-label", "Connection status: " + text);
}

function setCaption(main, sub) {
  orbCaptionEl.innerHTML = `${escapeHtml(main)}<span class="sub">${escapeHtml(sub || "")}</span>`;
}

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = text == null ? "" : String(text);
  return d.innerHTML;
}

function nowTime() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// Timer
function startTimer() {
  stopTimer();
  callStartTime = Date.now();
  callTimerEl.textContent = "00:00";
  callTimerInterval = setInterval(() => {
    callTimerEl.textContent = formatDuration(Date.now() - callStartTime);
  }, 1000);
}
function stopTimer() {
  if (callTimerInterval) {
    clearInterval(callTimerInterval);
    callTimerInterval = null;
  }
}
function formatDuration(ms) {
  const m = Math.floor(ms / 60000).toString().padStart(2, "0");
  const s = Math.floor((ms % 60000) / 1000).toString().padStart(2, "0");
  return `${m}:${s}`;
}
function getCallDuration() {
  return callStartTime ? formatDuration(Date.now() - callStartTime) : "00:00";
}

// Transcript
function appendMessage(role, text) {
  const empty = chatLog.querySelector(".transcript-empty");
  if (empty) empty.remove();
  const div = document.createElement("div");
  div.className = `message ${role}`;
  div.innerHTML = `<span class="msg-text">${escapeHtml(text)}</span>`;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
  return div;
}

function addChunk(role, text) {
  if (!text) return;
  if (role === "user") {
    if (currentUserMsg) {
      currentUserMsg.querySelector(".msg-text").textContent += text;
      const last = callTranscript[callTranscript.length - 1];
      if (last && last.role === "user") last.text += text;
    } else {
      currentUserMsg = appendMessage("user", text);
      callTranscript.push({ role: "user", text, time: nowTime() });
    }
  } else {
    if (currentGeminiMsg) {
      currentGeminiMsg.querySelector(".msg-text").textContent += text;
      const last = callTranscript[callTranscript.length - 1];
      if (last && last.role === "gemini") last.text += text;
    } else {
      currentGeminiMsg = appendMessage("gemini", text);
      callTranscript.push({ role: "gemini", text, time: nowTime() });
    }
  }
  chatLog.scrollTop = chatLog.scrollHeight;
}

function endTurns() {
  currentUserMsg = null;
  currentGeminiMsg = null;
}

// Lead capture
function renderLead(result) {
  const r = result || {};
  // Backend sends the outcome under `outcome_status` (see main.handle_record_rsvp)
  const outcome = String(r.outcome_status || r.outcome || r.status || "").toLowerCase();
  leadData = {
    outcome,
    customer_name: r.customer_name || r.guest_name || "",
    loan_interest: r.loan_interest || "",
    note: r.note || "",
    offer: r.offer || null, // { brand, agent, products }
  };

  const meta = OUTCOME_META[outcome] || {
    label: "Outcome recorded",
    emoji: "📋",
    tone: "neutral",
    sub: "Aria captured an outcome on this call.",
  };

  leadCard.classList.remove("pending", "positive", "info", "neutral", "negative");
  leadCard.classList.add(meta.tone);
  leadEmoji.textContent = meta.emoji;
  leadTitle.textContent = meta.label;
  leadSub.textContent =
    outcome === "yes" && leadData.customer_name
      ? `Noted for ${leadData.customer_name}.`
      : meta.sub;

  if (leadData.loan_interest) {
    leadProduct.textContent = leadData.loan_interest;
    leadProduct.classList.remove("hidden");
  } else {
    leadProduct.textContent = "";
    leadProduct.classList.add("hidden");
  }
}

// Message handling
function handleJsonMessage(msg) {
  switch (msg.type) {
    case "status":
      appendMessage("system", msg.text);
      break;
    case "interrupted":
      mediaHandler.stopAudioPlayback();
      ariaSpeaking = false;
      endTurns();
      setCaption("Listening…", "Go ahead");
      break;
    case "turn_complete":
      ariaSpeaking = false;
      endTurns();
      setCaption("Listening…", "Hindi, English or Gujarati — go ahead");
      break;
    case "user":
      addChunk("user", msg.text);
      break;
    case "gemini":
      addChunk("gemini", msg.text);
      break;
    case "tool_call":
      // "record_rsvp" is the backend tool key — kept as-is for wire compatibility.
      if (msg.name === "record_rsvp") renderLead(msg.result);
      break;
    case "error":
      appendMessage("system", "Error: " + (msg.error || "unknown"));
      break;
  }
}

// Orb visualizer
let orbCtx = null;
let orbDpr = 1;
let orbResizeTimer = null;
const orbCanvas = document.getElementById("zenon-orb");

function resizeOrb() {
  // CSS drives the display size (fluid, clamp/vw based); here we only match
  // the canvas backing store to it, scaled by devicePixelRatio for crispness.
  const rect = orbCanvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return; // hidden — keep last valid buffer
  orbDpr = Math.max(1, window.devicePixelRatio || 1);
  const w = Math.max(1, Math.round(rect.width * orbDpr));
  const h = Math.max(1, Math.round(rect.height * orbDpr));
  if (orbCanvas.width !== w) orbCanvas.width = w;
  if (orbCanvas.height !== h) orbCanvas.height = h;
}

// Debounced so rotation / URL-bar viewport changes don't thrash the canvas
// buffer mid-animation (the rAF loop keeps drawing at the last good size).
function scheduleOrbResize() {
  clearTimeout(orbResizeTimer);
  orbResizeTimer = setTimeout(resizeOrb, 150);
}

function analyserLevel(analyser) {
  if (!analyser) return 0;
  const arr = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(arr);
  let sum = 0;
  for (let i = 0; i < arr.length; i++) sum += arr[i];
  return Math.min(1, sum / arr.length / 128);
}

function startOrb() {
  stopOrb();
  orbCtx = orbCanvas.getContext("2d");
  resizeOrb();
  window.addEventListener("resize", scheduleOrbResize);
  window.addEventListener("orientationchange", scheduleOrbResize);

  const draw = () => {
    orbRAF = requestAnimationFrame(draw);
    const ctx = orbCtx;
    const W = orbCanvas.width / orbDpr;
    const H = orbCanvas.height / orbDpr;
    ctx.setTransform(orbDpr, 0, 0, orbDpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    const cx = W / 2, cy = H / 2;
    const baseR = Math.min(W, H) * 0.3;
    const t = performance.now() / 1000;
    const idle = 0.05 + 0.035 * Math.sin(t * 1.4);
    const out = Math.max(analyserLevel(mediaHandler.getOutputAnalyser()), idle);
    const inp = analyserLevel(mediaHandler.getInputAnalyser());

    // Outer glow — electric violet with a cyan mid-band
    const glowR = baseR * (1.55 + out * 1.1);
    const glow = ctx.createRadialGradient(cx, cy, baseR * 0.35, cx, cy, glowR);
    glow.addColorStop(0, `rgba(124,92,255,${0.3 + out * 0.45})`);
    glow.addColorStop(0.5, `rgba(34,211,238,${0.1 + out * 0.22})`);
    glow.addColorStop(1, "rgba(124,92,255,0)");
    ctx.fillStyle = glow;
    ctx.beginPath(); ctx.arc(cx, cy, glowR, 0, Math.PI * 2); ctx.fill();

    // Customer (mic) ring — cyan
    if (inp > 0.03) {
      ctx.strokeStyle = `rgba(34,211,238,${Math.min(0.7, inp * 1.6)})`;
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(cx, cy, baseR * (1.28 + inp * 0.5), 0, Math.PI * 2); ctx.stroke();
    }

    // Core orb — violet gradient
    const coreR = baseR * (1 + out * 0.16);
    const core = ctx.createRadialGradient(cx - coreR * 0.3, cy - coreR * 0.3, coreR * 0.1, cx, cy, coreR);
    core.addColorStop(0, "#ded2ff");
    core.addColorStop(0.6, "#7c5cff");
    core.addColorStop(1, "#4c2fd6");
    ctx.fillStyle = core;
    ctx.beginPath(); ctx.arc(cx, cy, coreR, 0, Math.PI * 2); ctx.fill();

    // Soft violet rim
    ctx.strokeStyle = `rgba(167,139,250,${0.45 + out * 0.4})`;
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(cx, cy, coreR, 0, Math.PI * 2); ctx.stroke();
  };
  draw();
}

function stopOrb() {
  if (orbRAF) {
    cancelAnimationFrame(orbRAF);
    orbRAF = null;
  }
  clearTimeout(orbResizeTimer);
  window.removeEventListener("resize", scheduleOrbResize);
  window.removeEventListener("orientationchange", scheduleOrbResize);
}

// Connect / mic / end
connectBtn.onclick = async () => {
  setStatus("connecting", "Connecting…");
  connectBtn.disabled = true;
  try {
    await mediaHandler.initializeAudio();
    geminiClient.connect();
  } catch (e) {
    console.error("Connection error:", e);
    setStatus("error", "Failed: " + e.message);
    connectBtn.disabled = false;
  }
};

async function startMic() {
  if (mediaHandler.isRecording || micStarting) return;
  micStarting = true;
  try {
    await mediaHandler.startAudio((data) => {
      if (geminiClient.isConnected()) geminiClient.send(data);
    });
    micBtn.classList.add("active");
    micBtn.dataset.active = "true";
  } catch (e) {
    console.error("Mic error:", e);
    micBtn.classList.remove("active");
    micBtn.dataset.active = "false";
    appendMessage("system", "Microphone unavailable: " + e.message);
  } finally {
    micStarting = false;
  }
}

micBtn.onclick = async () => {
  if (mediaHandler.isRecording) {
    mediaHandler.stopAudio();
    micBtn.classList.remove("active");
    micBtn.dataset.active = "false";
  } else {
    await startMic();
  }
};

disconnectBtn.onclick = () => geminiClient.disconnect();

// Text input (optional)
sendBtn.onclick = sendText;
textInput.onkeypress = (e) => {
  if (e.key === "Enter") sendText();
};
function sendText() {
  const text = textInput.value.trim();
  if (text && geminiClient.isConnected()) {
    geminiClient.sendText(text);
    addChunk("user", text);
    endTurns();
    textInput.value = "";
  }
}

// Session end
function showSessionEnd() {
  if (sessionEnded) return;
  sessionEnded = true;

  appSection.classList.add("hidden");
  sessionEndSection.classList.remove("hidden");
  mediaHandler.stopAudio();
  stopTimer();
  stopOrb();

  const meta = leadData ? OUTCOME_META[leadData.outcome] : null;
  let badgeTone, badgeText, emoji, title, line;
  if (meta) {
    badgeTone = meta.tone; badgeText = meta.label;
    emoji = meta.emoji; title = meta.endTitle; line = meta.endLine;
  } else if (leadData) {
    badgeTone = "neutral"; badgeText = "Outcome recorded";
    emoji = "📋"; title = "Call ended";
    line = "Aria captured an outcome on this call.";
  } else {
    badgeTone = "neutral"; badgeText = "No outcome recorded";
    emoji = "👋"; title = "Call ended";
    line = "No lead outcome was captured on this call.";
  }
  endEmoji.textContent = emoji;
  endTitle.textContent = title;
  endLine.textContent = line;
  outcomeBadge.className = "outcome-badge " + badgeTone;
  outcomeBadge.textContent = badgeText;

  let html = `<div class="summary-title">Call summary</div>`;
  html += summaryItem("Customer", (leadData && leadData.customer_name) || "—");
  html += summaryItem("Outcome", meta ? meta.label : "—");
  if (leadData && leadData.loan_interest) html += summaryItem("Product", leadData.loan_interest);
  html += summaryItem("Duration", getCallDuration());
  html += summaryItem("Exchanges", `${callTranscript.length}`);
  if (leadData && leadData.note) html += summaryItem("Note", leadData.note);

  if (callTranscript.length) {
    html += `<div class="tr-collapse" style="margin-top:16px;">
      <button type="button" class="transcript-toggle" onclick="this.parentElement.classList.toggle('open')">
        <span class="toggle-caret">▶</span> View full transcript (${callTranscript.length})
      </button>
      <div class="tr-full">`;
    for (const e of callTranscript) {
      const roleLabel = e.role === "user" ? "Customer" : "Aria · Zenon";
      html += `<div class="tr-line tr-${e.role}">
        <span class="tr-time">${escapeHtml(e.time)}</span>
        <span class="tr-role">${roleLabel}:</span>
        <span class="tr-text">${escapeHtml(e.text)}</span>
      </div>`;
    }
    html += `</div></div>`;
  }
  callSummary.innerHTML = html;
}

function summaryItem(k, v) {
  return `<div class="summary-item"><span class="k">${escapeHtml(k)}</span><span class="v">${escapeHtml(v)}</span></div>`;
}

// Reset
function resetUI() {
  stopTimer();
  stopOrb();
  mediaHandler.stopAudio();

  callStartTime = null;
  ariaSpeaking = false;
  micStarting = false;
  sessionEnded = false;
  leadData = null;
  callTranscript = [];
  currentUserMsg = null;
  currentGeminiMsg = null;

  chatLog.innerHTML = '<div class="transcript-empty">The conversation will appear here…</div>';
  leadCard.className = "lead-card glass pending";
  leadEmoji.textContent = "📋";
  leadTitle.textContent = "Interest not captured yet";
  leadSub.textContent = "Aria will record the outcome here.";
  leadProduct.textContent = "";
  leadProduct.classList.add("hidden");
  callTimerEl.textContent = "00:00";
  micBtn.classList.add("active");
  micBtn.dataset.active = "true";
  connectBtn.disabled = false;

  setStatus("disconnected", "Not connected");
  appSection.classList.add("hidden");
  sessionEndSection.classList.add("hidden");
  authSection.classList.remove("hidden");
}

restartBtn.onclick = resetUI;

// "Call me on my phone" (Twilio outbound)
const phoneInput = document.getElementById("phoneInput");
const callMeBtn = document.getElementById("callMeBtn");
const callMeStatus = document.getElementById("callMeStatus");

if (callMeBtn) {
  callMeBtn.onclick = async () => {
    let phone = (phoneInput.value || "").trim();
    if (!phone) {
      callMeStatus.textContent = "Enter your phone number";
      callMeStatus.className = "call-me-status error";
      return;
    }
    phone = phone.replace(/[\s\-()]/g, "");
    if (!phone.startsWith("+")) phone = "+91" + phone;

    callMeBtn.disabled = true;
    callMeStatus.textContent = "Calling…";
    callMeStatus.className = "call-me-status loading";
    try {
      const res = await fetch("/call-me", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone }),
      });
      const data = await res.json();
      if (data.success) {
        callMeStatus.textContent = "Calling " + phone + " — pick up your phone! Opening live transcript…";
        callMeStatus.className = "call-me-status success";
        setTimeout(() => window.open("/live", "_blank"), 1000);
      } else {
        callMeStatus.textContent = data.error || "Failed to call";
        callMeStatus.className = "call-me-status error";
      }
    } catch (e) {
      callMeStatus.textContent = "Network error: " + e.message;
      callMeStatus.className = "call-me-status error";
    }
    callMeBtn.disabled = false;
  };

  if (phoneInput) {
    phoneInput.onkeypress = (e) => {
      if (e.key === "Enter") callMeBtn.click();
    };
  }
}
