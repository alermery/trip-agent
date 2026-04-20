let ws = null;
let token = localStorage.getItem("xc_token") || "";
let reconnectTimer = null;
let wsReconnectEnabled = true;

function redirectToLoginSessionExpired() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  wsReconnectEnabled = false;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.close();
  }
  localStorage.removeItem("xc_token");
  window.location.replace("./login.html?session=expired");
}

const ITINERARY_LS_KEY = "xc_itinerary_notes";

/** 界面时间统一按北京时间（与后端 naive UTC 存库一致） */
const BEIJING_TZ = "Asia/Shanghai";

/**
 * 将服务端时间解析为 JS Date（UTC 时刻）。
 * Postgres / Pydantic 常见为无时区 ISO，按 UTC 解读，避免被当成本机时区（在伦敦/UTC 机器上会偏 8 小时）。
 */
function parseServerUtcToDate(raw) {
  if (raw === 0) return new Date(0);
  if (raw == null || raw === "") return new Date();
  let s = String(raw).trim();
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(s)) {
    s = s.replace(" ", "T");
  }
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(s)) {
    return new Date(`${s}Z`);
  }
  return new Date(s);
}

function formatBeijingHm(raw) {
  const d = parseServerUtcToDate(raw);
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: BEIJING_TZ,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    hourCycle: "h23",
  }).format(d);
}

function beijingYmd(date) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: BEIJING_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function previousBeijingCalendarYmd(ymd) {
  const start = Date.parse(`${ymd}T00:00:00+08:00`);
  return beijingYmd(new Date(start - 1));
}

const appEl = document.querySelector(".app");
const toggleHistoryBtn = document.getElementById("toggleHistoryBtn");
const wsUrlInput = document.getElementById("wsUrl");
const apiBaseInput = document.getElementById("apiBase");
const newChatBtn = document.getElementById("newChatBtn");
const locateBtn = document.getElementById("locateBtn");
const locateText = document.getElementById("locateText");
const historyListEl = document.getElementById("historyList");
const logoutBtn = document.getElementById("logoutBtn");
const agentSelect = document.getElementById("agent");
const connectBtn = document.getElementById("connectBtn");
const statusEl = document.getElementById("status");
const messagesEl = document.getElementById("messages");
const queryInput = document.getElementById("queryInput");
const itineraryNotesEl = document.getElementById("itineraryNotes");
const sendBtn = document.getElementById("sendBtn");
const pauseReplyBtn = document.getElementById("pauseReplyBtn");
const streamNodes = new Map();
const conversations = new Map();

/** 当前一轮从发送到 stream_end 的 UI 状态（与 WebSocket 流式对应） */
let activeStreamMessageId = null;
let composerAwaitingReply = false;

/** 与后端 AgentType 一致；仅用于界面展示为中文 */
const AGENT_LABEL_ZH = {
  weather: "天气",
  map: "地图",
  planner: "旅行规划",
};

function formatAgentLabelZh(code) {
  const c = String(code || "").trim();
  return AGENT_LABEL_ZH[c] || c;
}

let currentConversationId = "";
let historyCollapsed = false;
let currentLatitude = null;
let currentLongitude = null;
let currentCity = "";
let currentAddress = "";

function getTokenSubject(rawToken) {
  try {
    const payload = rawToken.split(".")[1];
    if (!payload) return "";
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const json = decodeURIComponent(
      atob(base64)
        .split("")
        .map((char) => `%${char.charCodeAt(0).toString(16).padStart(2, "0")}`)
        .join("")
    );
    const parsed = JSON.parse(json);
    return String(parsed.sub || "");
  } catch {
    return "";
  }
}

function getHistoryStorageKey() {
  const sub = getTokenSubject(token);
  return `xc_conversations_${sub || "anonymous"}`;
}

function saveConversationState() {
  const payload = {
    currentConversationId,
    conversations: Array.from(conversations.values()),
  };
  localStorage.setItem(getHistoryStorageKey(), JSON.stringify(payload));
}

function restoreConversationState() {
  try {
    const raw = localStorage.getItem(getHistoryStorageKey());
    if (!raw) {
      return false;
    }
    const parsed = JSON.parse(raw);
    const list = Array.isArray(parsed.conversations) ? parsed.conversations : [];
    conversations.clear();
    list.forEach((item) => {
      if (!item || !item.id) return;
      const title = String(item.title || "新对话");
      const messages = Array.isArray(item.messages) ? item.messages : [];
      const startedAt = item.startedAt || new Date().toISOString();
      conversations.set(item.id, {
        id: item.id,
        title,
        startedAt,
        messages,
        plannerMemoryResetPending: Boolean(item.plannerMemoryResetPending),
      });
    });
    if (!conversations.size) {
      return false;
    }
    const candidateId = String(parsed.currentConversationId || "");
    currentConversationId = conversations.has(candidateId)
      ? candidateId
      : Array.from(conversations.keys())[conversations.size - 1];
    renderHistoryList();
    renderConversation(currentConversationId);
    return true;
  } catch {
    return false;
  }
}

if (!token) {
  window.location.href = "./login.html";
}

const savedApiBase = localStorage.getItem("xc_api_base");
if (savedApiBase && apiBaseInput) {
  apiBaseInput.value = savedApiBase;
}

function setStatus(text, online) {
  statusEl.textContent = text;
  statusEl.classList.toggle("online", online);
  statusEl.classList.toggle("offline", !online);
}

function buildChatLine(role, text, isoTime = "") {
  const hm = isoTime ? formatBeijingHm(isoTime) : formatBeijingHm(null);
  const sender = role === "user" ? "你" : role === "bot" ? "小C" : "系统";
  return `${sender} ${hm}\n${text}`;
}

function createConversation(title = "新对话", presetMessages = []) {
  const id = `c_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  conversations.set(id, {
    id,
    title,
    startedAt: new Date().toISOString(),
    messages: presetMessages,
    plannerMemoryResetPending: true,
  });
  currentConversationId = id;
  if (itineraryNotesEl) {
    itineraryNotesEl.value = "";
    localStorage.removeItem(ITINERARY_LS_KEY);
  }
  renderHistoryList();
  renderConversation(id);
  saveConversationState();
}

/** @param {"idle" | "awaiting"} mode */
function setComposerState(mode) {
  const busy = mode !== "idle";
  composerAwaitingReply = busy;
  if (!sendBtn) return;
  sendBtn.classList.toggle("is-busy", busy);
  sendBtn.setAttribute("aria-busy", busy ? "true" : "false");
  queryInput.disabled = busy;
  if (pauseReplyBtn) {
    pauseReplyBtn.hidden = !busy;
    pauseReplyBtn.disabled = true;
  }
  if (mode === "idle") {
    activeStreamMessageId = null;
  }
}

function getHistoryGroupLabel(startedAt) {
  const ts = startedAt ? parseServerUtcToDate(startedAt) : new Date();
  const todayYmd = beijingYmd(new Date());
  const targetYmd = beijingYmd(ts);
  if (targetYmd === todayYmd) return "今天";
  if (targetYmd === previousBeijingCalendarYmd(todayYmd)) return "昨天";
  return "更早";
}

function createHistoryItemButton(conv) {
  const btn = document.createElement("button");
  btn.className = `history-item${conv.id === currentConversationId ? " active" : ""}`;
  btn.textContent = conv.title;
  btn.addEventListener("click", () => {
    currentConversationId = conv.id;
    renderHistoryList();
    renderConversation(conv.id);
    saveConversationState();
  });
  return btn;
}

function renderHistoryList() {
  historyListEl.innerHTML = "";
  const items = Array.from(conversations.values()).sort(
    (a, b) =>
      parseServerUtcToDate(b.startedAt || 0).getTime() - parseServerUtcToDate(a.startedAt || 0).getTime()
  );
  const grouped = {
    今天: [],
    昨天: [],
    更早: [],
  };
  items.forEach((conv) => {
    const key = getHistoryGroupLabel(conv.startedAt);
    grouped[key].push(conv);
  });
  ["今天", "昨天", "更早"].forEach((groupName) => {
    if (!grouped[groupName].length) return;
    const title = document.createElement("div");
    title.className = "history-group-title";
    title.textContent = groupName;
    historyListEl.appendChild(title);
    grouped[groupName].forEach((conv) => {
      historyListEl.appendChild(createHistoryItemButton(conv));
    });
  });
}

function renderConversation(conversationId) {
  const conv = conversations.get(conversationId);
  messagesEl.innerHTML = "";
  if (!conv) return;
  conv.messages.forEach((m) => {
    if (m.role === "bot") {
      const outer = document.createElement("div");
      outer.className = "msg bot";
      const bubble = document.createElement("div");
      bubble.className = "msg-bubble";
      renderBotBubbleContent(bubble, m.text);
      outer.appendChild(bubble);
      messagesEl.appendChild(outer);
    } else {
      const item = document.createElement("div");
      item.className = `msg ${m.role}`;
      item.textContent = m.text;
      messagesEl.appendChild(item);
    }
  });
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function resolveLocationAddress(latitude, longitude) {
  const base = apiBaseInput.value.trim().replace(/\/$/, "");
  const url = `${base}/location/reverse?latitude=${encodeURIComponent(latitude)}&longitude=${encodeURIComponent(longitude)}`;
  const response = await fetch(url);
  const data = await readResponseJson(response);
  if (!response.ok) {
    const msg = data._notJson ? data._raw || "地址解析失败" : formatApiDetail(data.detail) || "地址解析失败";
    throw new Error(msg);
  }
  return data;
}

function buildAmapLink(latitude, longitude, address) {
  const name = encodeURIComponent(address || "当前位置");
  return `https://uri.amap.com/marker?position=${longitude},${latitude}&name=${name}&src=xiaoc_assistant`;
}

function applyResolvedLocationHtml(loc) {
  currentCity = loc.city || "";
  currentAddress = loc.address || "";
  const mapUrl = buildAmapLink(currentLatitude, currentLongitude, loc.address);
  locateText.innerHTML = `当前位置：${loc.address} <a class="loc-link" href="${mapUrl}" target="_blank" rel="noopener noreferrer">在地图中查看</a>`;
}

function requestCurrentPosition({ pendingText, showResolvingStep, onResolved, geoFailLabel = "获取失败" }) {
  if (!navigator.geolocation) {
    locateText.textContent = "当前位置：当前浏览器不支持定位";
    return;
  }
  locateText.textContent = pendingText;
  navigator.geolocation.getCurrentPosition(
    async (position) => {
      currentLatitude = Number(position.coords.latitude.toFixed(6));
      currentLongitude = Number(position.coords.longitude.toFixed(6));
      if (showResolvingStep) {
        locateText.textContent = "当前位置：坐标已获取，正在解析具体地址...";
      }
      try {
        const loc = await resolveLocationAddress(currentLatitude, currentLongitude);
        applyResolvedLocationHtml(loc);
        onResolved?.(loc, null);
      } catch (err) {
        locateText.textContent = `当前位置：纬度 ${currentLatitude}，经度 ${currentLongitude}`;
        onResolved?.(null, err);
      }
    },
    (error) => {
      locateText.textContent = `当前位置：${geoFailLabel}（${error.message}）`;
    },
    { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }
  );
}

function addMessage(text, role = "system") {
  const item = document.createElement("div");
  item.className = `msg ${role}`;
  const fullText = buildChatLine(role, text);
  item.textContent = fullText;
  const conv = conversations.get(currentConversationId);
  if (conv) {
    conv.messages.push({ role, text: fullText });
    if (role === "user" && conv.title === "新对话") {
      conv.title = text.slice(0, 16) || "新对话";
      renderHistoryList();
    }
    saveConversationState();
  }
  messagesEl.appendChild(item);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function escapeHtmlText(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function getMarkdownParseFn() {
  if (typeof marked === "undefined") return null;
  if (typeof marked.parse === "function") {
    return (src, opts) => marked.parse(src, opts);
  }
  if (typeof marked === "function") {
    return (src, opts) => marked(src, opts);
  }
  return null;
}

function markdownAvailable() {
  return Boolean(getMarkdownParseFn() && typeof DOMPurify !== "undefined");
}

function configureMarkdownOnce() {
  if (!markdownAvailable() || configureMarkdownOnce._done) return;
  configureMarkdownOnce._done = true;
  try {
    if (typeof marked.use === "function") {
      marked.use({
        gfm: true,
        breaks: true,
      });
    }
  } catch {
    /* ignore */
  }
}

/**
 * 机器人气泡存盘格式：首行「小C HH:MM」，余下以「[智能体标签] 」开头，其后为 Markdown 正文。
 */
function splitBotBubblePlainText(full) {
  const s = String(full ?? "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const m = s.match(/^([^\n]+\n\[[^\]]+\]\s*)([\s\S]*)$/);
  if (m) {
    return { header: m[1], body: m[2] };
  }
  return { header: "", body: s };
}

function promoteAmapUrlsToMarkdownLinks(md) {
  const re = /https:\/\/(uri\.amap\.com|www\.amap\.com)[^\s)"'<>]+/g;
  return String(md ?? "").replace(re, (url) => `[在地图中打开](${url})`);
}

function sanitizeMarkdownHtml(html) {
  const raw = String(html ?? "");
  let clean = raw;
  try {
    clean = DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
  } catch {
    clean = raw;
  }
  const tpl = document.createElement("template");
  tpl.innerHTML = clean;
  tpl.content.querySelectorAll("a[href]").forEach((a) => {
    a.setAttribute("target", "_blank");
    a.setAttribute("rel", "noopener noreferrer");
  });
  return tpl.innerHTML;
}

function renderBotBubbleContent(bubble, fullPlainText) {
  configureMarkdownOnce();
  const { header, body } = splitBotBubblePlainText(fullPlainText);
  if (!markdownAvailable()) {
    bubble.classList.remove("msg-bubble--md");
    bubble.textContent = fullPlainText;
    linkifyBubble(bubble);
    return;
  }
  bubble.classList.add("msg-bubble--md");
  bubble.innerHTML = "";
  if (header) {
    const meta = document.createElement("div");
    meta.className = "msg-bot-meta";
    meta.textContent = header.trimEnd();
    bubble.appendChild(meta);
  }
  const mdWrap = document.createElement("div");
  mdWrap.className = "msg-md-content";
  const source = promoteAmapUrlsToMarkdownLinks(body);
  const parse = getMarkdownParseFn();
  try {
    const rawHtml = parse(source, { async: false });
    const applyHtml = (html) => {
      const str = String(html ?? "");
      mdWrap.innerHTML = sanitizeMarkdownHtml(str);
    };
    if (rawHtml != null && typeof rawHtml.then === "function") {
      rawHtml.then(applyHtml).catch(() => {
        bubble.classList.remove("msg-bubble--md");
        mdWrap.textContent = body;
      });
    } else {
      applyHtml(rawHtml);
    }
  } catch {
    bubble.classList.remove("msg-bubble--md");
    mdWrap.textContent = body;
  }
  bubble.appendChild(mdWrap);
}

function linkifyBubble(bubble) {
  const raw = bubble.textContent || "";
  if (!/https:\/\/(uri\.amap\.com|www\.amap\.com)\//.test(raw)) {
    return;
  }
  const re = /https:\/\/(uri\.amap\.com|www\.amap\.com)[^\s"'<>]+/g;
  const spans = [];
  let last = 0;
  let m;
  while ((m = re.exec(raw)) !== null) {
    spans.push({ t: "text", v: raw.slice(last, m.index) });
    spans.push({ t: "url", v: m[0] });
    last = m.index + m[0].length;
  }
  spans.push({ t: "text", v: raw.slice(last) });
  let hasUrl = false;
  const html = spans
    .map((p) => {
      if (p.t === "text") {
        return escapeHtmlText(p.v).replace(/\n/g, "<br>");
      }
      hasUrl = true;
      const u = p.v.replace(/"/g, "&quot;");
      return `<a class="inline-map-link" href="${u}" target="_blank" rel="noopener noreferrer">${escapeHtmlText(p.v)}</a>`;
    })
    .join("");
  if (!hasUrl) {
    return;
  }
  bubble.innerHTML = html;
}

function createStreamMessage(messageId, agent) {
  const outer = document.createElement("div");
  outer.className = "msg bot streaming";
  const toolHost = document.createElement("div");
  toolHost.className = "tool-trace-host";
  toolHost.setAttribute("aria-label", "工具返回");
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  const hm = formatBeijingHm(null);
  const prefix = `小C ${hm}\n[${formatAgentLabelZh(agent)}] `;
  const rolling = prefix;
  if (markdownAvailable()) {
    renderBotBubbleContent(bubble, rolling);
  } else {
    bubble.textContent = rolling;
  }
  outer.appendChild(toolHost);
  outer.appendChild(bubble);
  messagesEl.appendChild(outer);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  streamNodes.set(messageId, { outer, toolHost, bubble, prefix, agent, rolling, mdFlushTimer: null });
}

function applyToolTraceToMessage(messageId, tools) {
  const info = streamNodes.get(messageId);
  if (!info || !info.toolHost || !Array.isArray(tools) || !tools.length) {
    return;
  }
  info.toolHost.innerHTML = "";
  const details = document.createElement("details");
  details.className = "tool-trace-box";
  details.open = false;
  const summary = document.createElement("summary");
  summary.textContent = `工具返回（${tools.length} 次）· 点击展开`;
  details.appendChild(summary);
  for (let i = 0; i < tools.length; i += 1) {
    const t = tools[i] || {};
    const name = typeof t.name === "string" && t.name ? t.name : "tool";
    const raw = t.content != null ? String(t.content) : "";
    const wrap = document.createElement("div");
    wrap.className = "tool-trace-item";
    const title = document.createElement("div");
    title.className = "tool-trace-name";
    title.textContent = `${i + 1}. ${name}`;
    const pre = document.createElement("pre");
    pre.className = "tool-trace-content";
    pre.textContent = raw.length > 20000 ? raw.slice(0, 20000) + "\n…（截断）" : raw;
    wrap.appendChild(title);
    wrap.appendChild(pre);
    details.appendChild(wrap);
  }
  info.toolHost.appendChild(details);
  info.toolHost.classList.add("tool-trace-host--visible");
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function appendStreamChunk(messageId, chunk) {
  const info = streamNodes.get(messageId);
  if (!info) return;
  info.rolling = (info.rolling || "") + chunk;
  if (markdownAvailable()) {
    if (info.mdFlushTimer) {
      clearTimeout(info.mdFlushTimer);
    }
    info.mdFlushTimer = setTimeout(() => {
      info.mdFlushTimer = null;
      renderBotBubbleContent(info.bubble, info.rolling);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }, 100);
  } else {
    info.bubble.textContent = info.rolling;
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
}

function endStreamMessage(messageId, cancelled = false) {
  const info = streamNodes.get(messageId);
  if (info) {
    if (info.mdFlushTimer) {
      clearTimeout(info.mdFlushTimer);
      info.mdFlushTimer = null;
    }
    info.outer.classList.remove("streaming");
    let plain = typeof info.rolling === "string" ? info.rolling : info.bubble.textContent || "";
    if (cancelled && !String(plain).includes("（已停止输出）")) {
      plain += "\n\n（已停止输出）";
      info.rolling = plain;
    }
    renderBotBubbleContent(info.bubble, plain);
    const conv = conversations.get(currentConversationId);
    if (conv) {
      conv.messages.push({ role: "bot", text: plain });
      saveConversationState();
    }
  }
  streamNodes.delete(messageId);
}

function connect(auto = false) {
  token = localStorage.getItem("xc_token") || "";
  if (!token) {
    addMessage("请先注册或登录获取 token。", "system");
    return;
  }
  const url = wsUrlInput.value.trim();
  if (!url) {
    addMessage("请输入 WebSocket 地址", "system");
    return;
  }
  wsReconnectEnabled = true;
  if (ws && ws.readyState === WebSocket.OPEN) {
    if (!auto) addMessage("当前已连接，无需重复连接。", "system");
    ws.close();
  }

  ws = new WebSocket(url);
  setStatus("连接中", false);
  if (!auto) {
    addMessage(`正在连接 ${url}`, "system");
  }

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "auth", token }));
  };

  ws.onclose = (event) => {
    if (composerAwaitingReply) {
      setComposerState("idle");
    }
    setStatus("未连接", false);
    if (!wsReconnectEnabled) {
      return;
    }
    if (event.code === 1008) {
      addMessage("登录已失效，正在跳转登录页…", "system");
      redirectToLoginSessionExpired();
      return;
    }
    addMessage("连接已关闭，正在自动重连...", "system");
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => connect(true), 1200);
  };

  ws.onerror = () => {
    setStatus("连接异常", false);
    if (!auto) addMessage("WebSocket 发生错误。", "system");
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "stream_start") {
        activeStreamMessageId = data.message_id || null;
        if (pauseReplyBtn) {
          pauseReplyBtn.disabled = false;
        }
        createStreamMessage(data.message_id, data.agent);
      } else if (data.type === "tool_trace") {
        applyToolTraceToMessage(data.message_id, data.tools || []);
      } else if (data.type === "stream_chunk") {
        appendStreamChunk(data.message_id, data.chunk || "");
      } else if (data.type === "stream_end") {
        endStreamMessage(data.message_id, data.cancelled === true);
        setComposerState("idle");
      } else if (data.type === "system") {
        if (data.message === "auth ok") {
          setStatus("已连接", true);
          if (reconnectTimer) clearTimeout(reconnectTimer);
          addMessage("鉴权成功，可以开始提问。", "system");
        } else {
          addMessage(data.message, "system");
        }
      } else if (data.type === "error") {
        if (composerAwaitingReply) {
          setComposerState("idle");
        }
        addMessage(`错误: ${data.message}`, "system");
      } else {
        addMessage(event.data, "system");
      }
    } catch {
      if (composerAwaitingReply) {
        setComposerState("idle");
      }
      addMessage(event.data, "system");
    }
  };
}

function sendMessage() {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    addMessage("请先连接 WebSocket。", "system");
    return;
  }
  if (composerAwaitingReply) {
    return;
  }
  const query = queryInput.value.trim();
  if (!query) {
    return;
  }
  if (!currentConversationId) {
    addMessage("请先点击“新对话”创建会话。", "system");
    return;
  }
  const conv = conversations.get(currentConversationId);
  const payload = {
    query,
    agent: agentSelect.value,
    conversation_id: currentConversationId,
    conversation_started_at: conv?.startedAt || new Date().toISOString(),
  };
  if (conv && conv.plannerMemoryResetPending) {
    payload.planner_memory_reset = true;
    conv.plannerMemoryResetPending = false;
    saveConversationState();
  }
  if (currentLatitude !== null && currentLongitude !== null) {
    payload.latitude = currentLatitude;
    payload.longitude = currentLongitude;
    payload.current_city = currentCity;
    payload.current_address = currentAddress;
  }
  if (itineraryNotesEl) {
    const notes = itineraryNotesEl.value.trim();
    if (notes) {
      payload.itinerary_notes = notes;
    }
  }
  setComposerState("awaiting");
  ws.send(JSON.stringify(payload));
  addMessage(query, "user");
  queryInput.value = "";
}

async function loadHistory() {
  if (!token) return false;
  const base = apiBaseInput.value.trim().replace(/\/$/, "");
  localStorage.setItem("xc_api_base", base);
  try {
    const response = await fetch(`${base}/history`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await readResponseJson(response);
    if (response.status === 401) {
      redirectToLoginSessionExpired();
      return false;
    }
    if (!response.ok) {
      const msg = data._notJson
        ? data._raw || "查询历史失败"
        : formatApiDetail(data.detail) || "查询历史失败";
      throw new Error(msg);
    }
    if (!Array.isArray(data) || !data.length) {
      return false;
    }
    const grouped = new Map();
    data
      .slice()
      .sort((a, b) => parseServerUtcToDate(a.created_at).getTime() - parseServerUtcToDate(b.created_at).getTime())
      .forEach((item) => {
        const conversationId = String(item.conversation_id || `legacy_${item.id}`);
        if (!grouped.has(conversationId)) {
          const rawTitle = String(item.query || "历史对话").split("\n\n")[0];
          grouped.set(conversationId, {
            id: conversationId,
            title: rawTitle.slice(0, 16) || "历史对话",
            startedAt: item.conversation_started_at || item.created_at,
            messages: [],
            plannerMemoryResetPending: false,
          });
        }
        const conv = grouped.get(conversationId);
        conv.messages.push(
          { role: "user", text: buildChatLine("user", item.query, item.created_at) },
          {
            role: "bot",
            text: buildChatLine("bot", `[${formatAgentLabelZh(item.agent)}] ${item.reply}`, item.created_at),
          }
        );
      });
    conversations.clear();
    Array.from(grouped.values())
      .sort((a, b) => parseServerUtcToDate(a.startedAt).getTime() - parseServerUtcToDate(b.startedAt).getTime())
      .forEach((conv) => conversations.set(conv.id, conv));
    currentConversationId = Array.from(conversations.keys())[conversations.size - 1] || "";
    renderHistoryList();
    renderConversation(currentConversationId);
    saveConversationState();
    return true;
  } catch (error) {
    addMessage(`历史查询失败: ${error.message}`, "system");
    return false;
  }
}

function autoLocateOnLogin() {
  requestCurrentPosition({
    pendingText: "当前位置：登录后自动获取中...",
    showResolvingStep: false,
    geoFailLabel: "自动获取失败",
  });
}

connectBtn.addEventListener("click", connect);
sendBtn.addEventListener("click", sendMessage);
if (pauseReplyBtn) {
  pauseReplyBtn.addEventListener("click", () => {
    if (!activeStreamMessageId || !ws || ws.readyState !== WebSocket.OPEN) {
      return;
    }
    ws.send(JSON.stringify({ type: "cancel", message_id: activeStreamMessageId }));
    pauseReplyBtn.disabled = true;
  });
}
newChatBtn.addEventListener("click", () => createConversation("新对话"));
toggleHistoryBtn.addEventListener("click", () => {
  historyCollapsed = !historyCollapsed;
  appEl.classList.toggle("history-collapsed", historyCollapsed);
  toggleHistoryBtn.textContent = historyCollapsed ? "展开" : "收起";
});
locateBtn.addEventListener("click", () => {
  requestCurrentPosition({
    pendingText: "当前位置：正在获取...",
    showResolvingStep: true,
    onResolved: (loc, err) => {
      if (loc) {
        addMessage(`已获取当前位置：${loc.city}，后续地图问答会优先使用该位置。`, "system");
      } else {
        addMessage(`地址解析失败，已使用坐标定位：${err.message}`, "system");
      }
    },
  });
});
logoutBtn.addEventListener("click", () => {
  wsReconnectEnabled = false;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  localStorage.removeItem("xc_token");
  setStatus("未连接", false);
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.close();
  }
  window.location.href = "./login.html";
});
queryInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

async function initializePage() {
  if (itineraryNotesEl) {
    itineraryNotesEl.value = localStorage.getItem(ITINERARY_LS_KEY) || "";
  }
  conversations.clear();
  currentConversationId = "";
  const loadedFromServer = await loadHistory();
  if (!localStorage.getItem("xc_token")) {
    return;
  }
  if (!loadedFromServer && !restoreConversationState()) {
    renderHistoryList();
    messagesEl.innerHTML = "";
    addMessage("请点击左侧“新对话”开始会话。", "system");
  }
  autoLocateOnLogin();
  connect(true);
}

if (itineraryNotesEl) {
  itineraryNotesEl.addEventListener("input", () => {
    localStorage.setItem(ITINERARY_LS_KEY, itineraryNotesEl.value.slice(0, 4000));
  });
}

initializePage();
