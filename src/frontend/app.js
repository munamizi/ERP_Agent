import { readEventStream } from "/frontend/stream.js";

const ui = Object.fromEntries([...document.querySelectorAll("[id]")].map((node) => [node.id, node]));
const statusLabels = { running: "执行中", completed: "已完成", interrupted: "等待处理", error: "执行失败" };
let config = _loadConfig();
sessionStorage.setItem("erp-agent.config", JSON.stringify(config));
const state = {
  threadId: null, busy: false, status: "", title: "新的采购会话", interrupts: [],
  replies: new Map(), assistant: null, childMessages: new Map(), eventCount: 0, controller: null,
  chatMarkers: [], chatJumpTop: null, chatJumpFrame: null,
};

/** 读取当前标签页保存的用户信息，首次打开时使用本机用户。 */
function _loadConfig() {
  try {
    const saved = JSON.parse(sessionStorage.getItem("erp-agent.config"));
    if (saved?.userId && saved.username) return { userId: saved.userId, username: saved.username };
  } catch { /* 无可用设置时使用默认本机用户。 */ }
  return { userId: "local-user", username: "本机用户" };
}

/** 保存当前会话编号，便于刷新页面后加载服务端展示记录。 */
function _rememberThread() {
  sessionStorage.setItem(`erp-agent.thread.${config.userId}`, state.threadId || "");
}

/** 用纯文本创建节点，避免把模型输出或工具结果作为 HTML 执行。 */
function _element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}

/** 显示当前请求错误或需要用户注意的服务状态。 */
function _notice(message = "") {
  ui.notice.textContent = message;
  ui.notice.hidden = !message;
}

/** 在窄屏上展开或收起会话导航，避免导航挤占聊天区域。 */
function _sidebar(open) {
  ui.sidebar.classList.toggle("is-open", open);
  ui["sidebar-backdrop"].hidden = !open;
  ui["toggle-sidebar"].setAttribute("aria-expanded", String(open));
}

/** 将服务端消息内容块转换为可展示的文本。 */
function _text(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.map((item) => typeof item === "string" ? item : item.text || "").join("");
  return content == null ? "" : JSON.stringify(content, null, 2);
}

/** 判断当前阅读位置是否应跟随新回复。 */
function _followsChat(scroll) {
  return state.chatJumpTop === null && scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 180;
}

/** 将对话滚动到底部；用户定位或向上查看记录时保留阅读位置。 */
function _scroll(force = false) {
  const node = ui["chat-scroll"];
  if (force) _cancelChatJump();
  if (force || _followsChat(node)) node.scrollTop = node.scrollHeight;
}

/** 高亮当前刻度，必要时将它滚入定位栏的可视区域。 */
function _setActiveChatMarker(marker) {
  const navigation = ui["chat-navigation"];
  const active = navigation.querySelector("[aria-current]");
  if (active === marker) return;

  active?.removeAttribute("aria-current");
  marker.setAttribute("aria-current", "location");
  const top = marker.offsetTop;
  if (top < navigation.scrollTop || top + marker.offsetHeight > navigation.scrollTop + navigation.clientHeight) {
    navigation.scrollTop = top - (navigation.clientHeight - marker.offsetHeight) / 2;
  }
}

/** 按聊天滚动位置同步刻度，点击定位后保留选中状态直到再次滚动。 */
function _syncChatNavigation() {
  if (!state.chatMarkers.length) return;
  const scroll = ui["chat-scroll"];
  if (state.chatJumpTop !== null) {
    if (Math.abs(scroll.scrollTop - state.chatJumpTop) < 2) return;
    _cancelChatJump();
  }

  const maxScrollTop = scroll.scrollHeight - scroll.clientHeight;
  if (maxScrollTop - scroll.scrollTop < 2) {
    _setActiveChatMarker(state.chatMarkers.at(-1).marker);
    return;
  }

  const top = scroll.getBoundingClientRect().top + 24;
  let current = state.chatMarkers[0].marker;
  for (const { message, marker } of state.chatMarkers) {
    if (message.getBoundingClientRect().top > top) break;
    current = marker;
  }
  _setActiveChatMarker(current);
}

/** 停止当前定位动画并解除阅读位置锁定。 */
function _cancelChatJump() {
  if (state.chatJumpFrame !== null) cancelAnimationFrame(state.chatJumpFrame);
  state.chatJumpFrame = null;
  state.chatJumpTop = null;
}

/** 以先加速后减速的方式滚到目标问题，并在定位期间暂停跟随回复。 */
function _jumpToChatMessage(message, marker) {
  _cancelChatJump();
  const scroll = ui["chat-scroll"];
  const start = scroll.scrollTop;
  const offset = message.getBoundingClientRect().top - scroll.getBoundingClientRect().top;
  const target = Math.max(0, Math.min(start + offset - 16, scroll.scrollHeight - scroll.clientHeight));
  const distance = target - start;
  _setActiveChatMarker(marker);

  if (Math.abs(distance) < 2 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    scroll.scrollTo({ top: target, behavior: "instant" });
    state.chatJumpTop = scroll.scrollTop;
    return;
  }

  // 先结束浏览器已有的平滑滚动，再逐帧应用自定义缓动。
  scroll.scrollTo({ top: start, behavior: "instant" });
  state.chatJumpTop = scroll.scrollTop;
  const duration = Math.min(640, Math.max(260, Math.abs(distance) * 0.26));
  const started = performance.now();

  function _step(now) {
    const progress = Math.min(1, Math.max(0, (now - started) / duration));
    const eased = progress < 0.5 ? 4 * progress ** 3 : 1 - (2 - 2 * progress) ** 3 / 2;
    scroll.scrollTo({ top: start + distance * eased, behavior: "instant" });
    state.chatJumpTop = scroll.scrollTop;
    state.chatJumpFrame = progress < 1 ? requestAnimationFrame(_step) : null;
  }
  state.chatJumpFrame = requestAnimationFrame(_step);
}

/** 为用户消息添加定位刻度，并将按钮绑定到对应问题。 */
function _addChatMarker(message, text) {
  const navigation = ui["chat-navigation"];
  const marker = _element("button", "chat-marker");
  const preview = text.trim().replace(/\s+/g, " ").slice(0, 60);
  const label = `定位到第 ${state.chatMarkers.length + 1} 条消息`;
  marker.type = "button";
  marker.title = preview || label;
  marker.setAttribute("aria-label", preview ? `${label}，${preview}` : label);
  marker.addEventListener("click", () => _jumpToChatMessage(message, marker));
  state.chatMarkers.push({ message, marker });
  navigation.append(marker);
  navigation.hidden = false;
  _setActiveChatMarker(marker);
}

/** 拆分 Markdown 表格行，保留用反斜杠转义的竖线。 */
function _tableCells(line) {
  if (!line.includes("|") || /^( {4}|\t)/.test(line)) return [];
  const row = line.trim();
  const cells = [];
  let cell = "";
  for (let index = 0; index < row.length; index += 1) {
    const char = row[index];
    if (char === "\\" && (row[index + 1] === "|" || row[index + 1] === "\\")) {
      cell += row[index + 1];
      index += 1;
    } else if (char === "|") {
      cells.push(cell.trim());
      cell = "";
    } else {
      cell += char;
    }
  }
  if (!cells.length) return [];
  if (row.startsWith("|")) cells.shift();
  if (cell || !row.endsWith("|")) cells.push(cell.trim());
  return cells;
}

/** 创建可横向滚动的表格，单元格只接受文本和加粗标记。 */
function _messageTable(header, separators, rows) {
  const scroll = _element("div", "message-table-scroll");
  scroll.tabIndex = 0;
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", "回复数据表格");
  const table = _element("table", "message-table");
  const headings = table.createTHead();
  const data = table.createTBody();

  for (const [index, values] of [header, ...rows].entries()) {
    const row = (index === 0 ? headings : data).insertRow();
    for (const [column, value] of values.entries()) {
      const cell = _element(index === 0 ? "th" : "td");
      if (index === 0) cell.scope = "col";
      if (separators[column].endsWith(":")) {
        cell.style.textAlign = separators[column].startsWith(":") ? "center" : "right";
      }
      for (const [part, text] of value.split(/(\*\*[^*]+\*\*)/).entries()) {
        cell.append(part % 2 ? _element("strong", "", text.slice(2, -2)) : text);
      }
      row.append(cell);
    }
  }
  scroll.append(table);
  return scroll;
}

/** 把完整助手回复里的表格转成 DOM，保留其他内容及代码块的原文。 */
function _renderAssistantTables(body, text) {
  const lines = text.split(/\r\n?|\n/);
  const content = document.createDocumentFragment();
  let textStart = 0;
  let fence = "";

  for (let index = 0; index + 1 < lines.length; index += 1) {
    const marker = lines[index].match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if (fence) {
      if (marker && marker[1][0] === fence[0] && marker[1].length >= fence.length && !marker[2].trim()) fence = "";
      continue;
    }
    if (marker) {
      fence = marker[1];
      continue;
    }

    const header = _tableCells(lines[index]);
    if (!header.length) continue;
    const separators = _tableCells(lines[index + 1]);
    if (header.length !== separators.length || !separators.every((cell) => /^:?-{3,}:?$/.test(cell))) continue;

    const rows = [];
    let next = index + 2;
    for (; next < lines.length; next += 1) {
      const row = _tableCells(lines[next]);
      if (row.length !== header.length) break;
      rows.push(row);
    }
    content.append(lines.slice(textStart, index).join("\n"), _messageTable(header, separators, rows));
    textStart = next;
    index = next - 1;
  }

  if (!textStart) {
    body.textContent = text;
    return;
  }
  content.append(lines.slice(textStart).join("\n"));
  body.replaceChildren(content);
}

/** 添加一条用户消息或主代理回复，返回正文节点以接收后续分片。 */
function _message(role, text) {
  const follow = _followsChat(ui["chat-scroll"]);
  ui.welcome.hidden = true;
  const article = _element("article", `message ${role}`);
  article.setAttribute("aria-label", role === "user" ? "你的消息" : "助手回复");
  const body = _element("div", "message-body");
  if (role === "assistant" && text) _renderAssistantTables(body, text);
  else body.textContent = text;
  article.append(body);
  ui.messages.append(article);
  if (role === "user") _addChatMarker(article, text);
  if (role === "user" || follow) _scroll(true);
  return body;
}

/** 为诊断记录创建折叠条目，并限制当前页面保留的条目数量。 */
function _trace(title, value, status = "") {
  ui.trace.querySelector(".trace-empty")?.remove();
  const details = _element("details");
  details.dataset.status = status;
  details.append(_element("summary", "", title));
  const content = _element("pre", "", _text(typeof value === "object" ? JSON.stringify(value, null, 2) : value).slice(0, 50000));
  details.append(content);
  ui.trace.append(details);
  state.eventCount += 1;
  ui["event-count"].textContent = String(state.eventCount);
  while (ui.trace.children.length > 100) ui.trace.firstElementChild.remove();
  return content;
}

/** 为导出工具的结构化结果添加下载按钮，通过本机文件接口取文件。 */
function _attachment(container, result) {
  let value = result;
  try { if (typeof value === "string") value = JSON.parse(value); } catch { return; }
  if (!value?.download_url || !value.file_name) return;
  let url;
  try { url = new URL(value.download_url, location.origin); } catch { return; }
  if (!url.pathname.startsWith("/api/files/") || url.searchParams.get("user_id") !== config.userId || url.searchParams.get("thread_id") !== state.threadId) return;
  const button = _element("button", "secondary", `下载 ${value.file_name}`);
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const response = await _request(url.pathname + url.search);
      const objectUrl = URL.createObjectURL(await response.blob());
      const link = _element("a");
      link.href = objectUrl;
      link.download = value.file_name;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (error) { _notice(error.message); }
    finally { button.disabled = false; }
  });
  container.append(button);
}

/** 根据执行状态切换发送和断开按钮，锁定正在执行或等待处理的会话输入。 */
function _controls() {
  const pending = state.interrupts.length > 0;
  const blocked = state.busy || pending || state.status === "running";
  ui.message.disabled = blocked;
  ui.send.disabled = blocked || !ui.message.value.trim();
  ui.send.hidden = Boolean(state.controller);
  ui.message.placeholder = pending ? "请先处理上方的补充信息或审批" : "描述你的采购需求…";
  ui["new-chat"].disabled = state.busy;
  ui["refresh-history"].disabled = state.busy;
  ui.settings.disabled = state.busy;
  ui.disconnect.hidden = !ui.send.hidden;
  for (const button of ui.sessions.querySelectorAll("button")) button.disabled = state.busy;
  for (const input of ui.interrupts.querySelectorAll("button, textarea, select, input")) input.disabled = state.busy;
  ui["chat-title"].textContent = state.title;
  ui["thread-label"].textContent = state.threadId || "开始对话后自动保存";
}

/** 校验 HTTP 响应，将非流式接口错误转为可读异常。 */
async function _checked(response) {
  if (response.ok) return response;
  const text = await response.text();
  let detail = text;
  try { detail = JSON.parse(text).detail || text; } catch { /* 代理或服务也可能返回纯文本错误。 */ }
  throw new Error(`HTTP ${response.status}：${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
}

/** 访问同源 API，有请求体时设置 JSON 内容类型。 */
async function _request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers },
  });
  return _checked(response);
}

/** 分别更新网页接口和沙箱服务的可达状态。 */
async function _health() {
  const sandboxCheck = _sandboxHealth();
  try {
    const response = await fetch("/health", { cache: "no-store", signal: AbortSignal.timeout(4000) });
    const data = await (await _checked(response)).json();
    const online = data.status === "ok";
    ui.health.textContent = online ? "正常" : "异常";
    ui.health.className = online ? "health online" : "health offline";
  } catch {
    ui.health.textContent = "无法连接";
    ui.health.className = "health offline";
  }
  await sandboxCheck;
}

/** 显示沙箱探测结果，探测接口不可达时标为未检测。 */
async function _sandboxHealth() {
  const indicator = ui["sandbox-health"];
  try {
    const response = await fetch("/health/sandbox", { cache: "no-store", signal: AbortSignal.timeout(4000) });
    const data = await (await _checked(response)).json();
    const online = data.status === "ok";
    indicator.textContent = online ? "正常" : "异常";
    indicator.className = online ? "health online" : "health offline";
  } catch {
    indicator.textContent = "未检测";
    indicator.className = "health";
  }
}

/** 刷新当前用户的会话列表，不自动执行或恢复任何任务。 */
async function _history() {
  const data = await (await _request(`/api/history?user_id=${encodeURIComponent(config.userId)}`)).json();
  ui.sessions.replaceChildren();
  for (const item of data.items) {
    const row = _element("div", "session-row");
    row.dataset.threadId = item.thread_id;
    const button = _element("button", `session-item${item.thread_id === state.threadId ? " active" : ""}`);
    button.type = "button";
    button.dataset.threadId = item.thread_id;
    button.disabled = state.busy;
    button.append(_element("strong", "", item.title || "未命名会话"));
    const date = new Date(item.updated_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    button.append(_element("small", "", `${statusLabels[item.status] || item.status} · ${date}`));
    button.addEventListener("click", () => _openThread(item));
    const remove = _element("button", "session-delete", "删除");
    remove.type = "button";
    remove.disabled = state.busy;
    remove.setAttribute("aria-label", `删除会话：${item.title || "未命名会话"}`);
    remove.addEventListener("click", () => _deleteThread(item));
    row.append(button, remove);
    ui.sessions.append(row);
  }
  if (!data.items.length) ui.sessions.append(_element("p", "muted empty-list", "还没有会话，开始聊聊吧"));
  return data.items;
}

/** 确认后删除服务端会话；成功才更新列表，并清空被删除的当前会话。 */
async function _deleteThread(item) {
  if (state.busy) return;
  if (!window.confirm(`删除会话「${item.title || "未命名会话"}」？\n聊天记录删除后无法恢复，已导出的文件会保留。`)) return;
  state.busy = true;
  _notice();
  _controls();
  let deleted = false;
  try {
    await _request(`/api/history/${encodeURIComponent(item.thread_id)}?user_id=${encodeURIComponent(config.userId)}`, { method: "DELETE" });
    deleted = true;
    for (const row of ui.sessions.querySelectorAll(".session-row")) {
      if (row.dataset.threadId === item.thread_id) row.remove();
    }
    if (!ui.sessions.children.length) ui.sessions.append(_element("p", "muted empty-list", "还没有会话，开始聊聊吧"));
  } catch (error) {
    _notice(`删除会话失败：${error.message}`);
  } finally {
    state.busy = false;
    if (deleted && state.threadId === item.thread_id) _newChat();
    else _controls();
  }
}

/** 清空当前展示内容和诊断记录，不删除服务端会话。 */
function _clearView() {
  state.interrupts = [];
  state.replies.clear();
  state.assistant = null;
  state.childMessages.clear();
  state.eventCount = 0;
  ui["event-count"].textContent = "0";
  _cancelChatJump();
  ui.messages.replaceChildren();
  state.chatMarkers = [];
  ui["chat-navigation"].replaceChildren();
  ui["chat-navigation"].hidden = true;
  ui.interrupts.replaceChildren();
  ui.trace.replaceChildren(_element("p", "muted trace-empty", "发起任务后显示执行过程"));
  ui.welcome.hidden = false;
  _notice();
}

/** 切换到空白会话，首次发送时再创建服务端记录。 */
function _newChat() {
  if (state.busy) return;
  _sidebar(false);
  _clearView();
  state.threadId = null;
  state.status = "";
  state.title = "新的采购会话";
  _rememberThread();
  ui.message.value = "";
  ui.activity.textContent = "就绪";
  for (const item of ui.sessions.querySelectorAll(".active")) item.classList.remove("active");
  _controls();
  ui.message.focus();
}

/** 加载服务端保存的主会话和待处理中断，刷新后仍可继续人工处理。 */
async function _openThread(item) {
  if (state.busy) return;
  _sidebar(false);
  state.busy = true;
  _controls();
  try {
    const response = await fetch(`/api/history/${encodeURIComponent(item.thread_id)}?user_id=${encodeURIComponent(config.userId)}`);
    // 初次执行还没有展示快照时，保留会话状态，等待用户刷新记录。
    const data = response.status === 404 && item.status === "running" ? { messages: [], interrupts: [] } : await (await _checked(response)).json();
    _clearView();
    state.threadId = item.thread_id;
    state.title = item.title;
    state.status = item.status;
    _rememberThread();
    for (const message of data.messages) {
      if (message.role === "human") _message("user", _text(message.content));
      else if (message.role === "ai" && !message.tool_calls?.length && _text(message.content)) _message("assistant", _text(message.content));
      else if (message.role === "tool") {
        const node = _trace("工具结果", message.content);
        _attachment(node.parentElement, message.content);
      }
      else if (message.tool_calls?.length) _trace("历史工具调用", message.tool_calls);
    }
    // 错误或取消时保存的旧快照不能作为新的审批依据。
    state.interrupts = item.status === "interrupted" ? data.interrupts || [] : [];
    _renderInterrupts();
    if (item.status === "running") _notice("该会话仍在服务端执行，请稍后点击“刷新”查看结果。");
    if (item.status === "error") _notice("上次执行失败。此处显示已保存记录；请查看服务端日志确认失败原因。");
    if (item.status === "interrupted" && !state.interrupts.length) {
      _notice("连接曾被断开，当前没有保存可处理的中断卡片。请确认服务端状态；不要重复提交采购操作。");
      state.status = "running";
    }
    ui.activity.textContent = statusLabels[item.status] || "就绪";
    for (const button of ui.sessions.querySelectorAll(".session-item")) button.classList.toggle("active", button.dataset.threadId === item.thread_id);
    _scroll(true);
  } catch (error) { _notice(error.message); }
  finally { state.busy = false; _controls(); }
}

/** 记录用户对某个中断的明确回复，全部中断处理完后按 ID 提交恢复。 */
async function _reply(id, value, label) {
  if (state.busy) return;
  state.replies.set(id, { value, label });
  if (state.replies.size < state.interrupts.length) {
    _renderInterrupts();
    return;
  }
  const reply = Object.fromEntries([...state.replies].map(([key, item]) => [key, item.value]));
  const text = [...state.replies.values()].map((item) => item.label).join("\n");
  await _run("/api/chat/resume", { reply }, text);
}

/** 将工具名和目标状态转换成审批人可读的操作。 */
function _approvalOperation(action) {
  if (action.name === "order_create") return { title: "创建采购草稿", approve: "同意创建" };
  if (action.name === "order_update") {
    const status = action.args?.status;
    if (status === "confirmed") return { title: "确认采购单", approve: "同意确认" };
    if (status === "cancelled") return { title: "取消采购单", approve: "同意取消" };
    if (status == null) return { title: "修改采购草稿", approve: "同意修改" };
    return { title: "更新采购单", approve: "同意更新" };
  }
  return { title: "工具操作", approve: "同意执行" };
}

/** 将可按分精确表示的金额转换成整数分。 */
function _approvalCents(amount) {
  if (typeof amount !== "string" && typeof amount !== "number") return null;
  const match = /^(\d+)(?:\.(\d{1,2}))?$/.exec(String(amount ?? "").trim());
  return match ? BigInt(match[1]) * 100n + BigInt((match[2] || "").padEnd(2, "0")) : null;
}

/** 显示两位小数，保留无法解析的原始金额供核对。 */
function _approvalAmount(amount, cents = _approvalCents(amount)) {
  if (cents === null) {
    if (amount == null || amount === "") return "未提供";
    return typeof amount === "string" || typeof amount === "number" ? String(amount) : "格式有误";
  }
  const whole = (cents / 100n).toLocaleString("zh-CN");
  return '¥' + whole + '.' + String(cents % 100n).padStart(2, "0");
}

/** 为新草稿汇总物料和运费，信息不完整时不显示合计。 */
function _draftTotal(lines, freight) {
  let total = _approvalCents(freight);
  if (total === null || !lines.length) return null;
  for (const line of lines) {
    const price = _approvalCents(line?.unit_price);
    const quantity = line?.quantity;
    if (price === null || price <= 0n || !Number.isSafeInteger(quantity) || quantity <= 0) return null;
    total += price * BigInt(quantity);
  }
  return total;
}

/** 将业务参数排成概览和明细，原始参数另放在技术详情。 */
function _approvalSummary(section, action) {
  const args = action.args || {};
  const create = action.name === "order_create";
  const update = action.name === "order_update";
  const lines = Array.isArray(args.lines) ? args.lines : [];
  const facts = [];
  if (create) facts.push(["供应商", args.supplier_id == null ? "未提供" : "#" + args.supplier_id]);
  if (update) facts.push(["采购单", args.order_id == null ? "未提供" : "#" + args.order_id]);
  if (create || args.expected_date != null) facts.push(["预计到货", args.expected_date || "未提供"]);
  if (args.sales_order_id != null) facts.push(["关联销售单", "#" + args.sales_order_id]);
  const freight = args.freight === undefined ? "0.00" : args.freight;
  if (create || args.freight != null) facts.push(["运费", _approvalAmount(freight)]);
  if (update && args.status != null && !["confirmed", "cancelled"].includes(args.status)) {
    facts.push(["目标状态", args.status]);
  }
  const total = create ? _draftTotal(lines, freight) : null;
  if (total !== null) facts.push(["合计（含运费）", _approvalAmount(null, total)]);

  if (facts.length) {
    const list = _element("dl", "approval-facts");
    for (const [label, text] of facts) {
      const fact = _element("div");
      fact.append(_element("dt", "", label), _element("dd", "", text));
      list.append(fact);
    }
    section.append(list);
  }
  if (lines.length) {
    const table = _element("table", "approval-lines");
    table.append(_element("caption", "", update ? "替换后的物料明细" : "物料明细"));
    const headers = table.createTHead().insertRow();
    for (const label of ["物料", "数量", "单价"]) {
      const header = _element("th", "", label);
      header.scope = "col";
      headers.append(header);
    }
    const body = table.createTBody();
    for (const line of lines) {
      const row = body.insertRow();
      const part = line?.part_id == null ? "未提供" : "#" + line.part_id;
      for (const text of [part, line?.quantity ?? "未提供", _approvalAmount(line?.unit_price)]) {
        row.append(_element("td", "", text));
      }
    }
    section.append(table);
  } else if (create) {
    section.append(_element("p", "", "未提供物料明细，请核对。"));
  }
  if ((create || update) && (args.notes || (update && args.notes === ""))) {
    const note = _element("div", "approval-note");
    note.append(_element("div", "approval-note-label", "采购备注"), _element("p", "", args.notes || "清空原采购备注"));
    section.append(note);
  }

  const details = _element("details", "approval-details");
  details.open = !create && !update;
  details.append(_element("summary", "", "技术详情"), _element("code", "approval-tool", action.name));
  if (details.open && action.description) details.append(_element("p", "", action.description));
  details.append(_element("pre", "approval-args", JSON.stringify(args, null, 2)));
  section.append(details);
}

/** 为普通审批提供直接同意和可填写原因的拒绝确认。 */
function _approvalButtons(section, id, allowed, operation, input) {
  const actions = _element("div", "actions approval-actions");
  section.append(actions);
  if (allowed.includes("reject")) {
    const reject = _element("button", "secondary", "拒绝");
    const panel = _element("div", "approval-rejection");
    panel.hidden = true;
    input.hidden = false;
    const buttons = _element("div", "actions approval-actions");
    const back = _element("button", "secondary", "返回");
    const confirm = _element("button", "danger", "确认拒绝");
    reject.type = back.type = confirm.type = "button";
    buttons.append(back, confirm);
    panel.append(input, buttons);
    section.append(panel);

    reject.addEventListener("click", () => {
      actions.hidden = true;
      panel.hidden = false;
      input.focus();
    });
    back.addEventListener("click", () => {
      panel.hidden = true;
      actions.hidden = false;
      reject.focus();
    });
    confirm.addEventListener("click", () => {
      const decision = { type: "reject" };
      if (input.value.trim()) decision.message = input.value.trim();
      _reply(id, { decisions: [decision] }, "已拒绝 · " + operation.title);
    });
    actions.append(reject);
  }
  if (allowed.includes("approve")) {
    const approve = _element("button", "primary", operation.approve);
    approve.type = "button";
    approve.addEventListener("click", () => _reply(id, { decisions: [{ type: "approve" }] }, "已同意 · " + operation.title));
    actions.append(approve);
  }
  if (!actions.children.length) actions.remove();
}

/** 展示采购审批摘要，只提供服务端允许的决定类型。 */
function _approval(card, item) {
  const value = item.value;
  const requests = value.action_requests.map((action) => ({
    action,
    operation: _approvalOperation(action),
    allowed: value.review_configs?.find((rule) => rule.action_name === action.name)?.allowed_decisions || [],
  }));
  const multiple = requests.length > 1;
  const useForm = multiple || requests.some(({ allowed }) => allowed.includes("edit") || allowed.includes("respond"));
  card.classList.add("purchase-approval");
  card.append(
    _element("span", "approval-status", "等待审批"),
    _element("h3", "", multiple ? "采购操作审批" : requests[0].operation.title),
  );

  const forms = [];
  for (const { action, operation, allowed } of requests) {
    const section = _element("div", "approval-action");
    if (multiple) section.append(_element("h4", "", operation.title));
    _approvalSummary(section, action);
    const input = _element("textarea");
    input.placeholder = "可选：填写拒绝原因";
    input.setAttribute("aria-label", operation.title + "的审批说明");
    input.hidden = true;

    if (useForm) {
      const select = _element("select");
      select.setAttribute("aria-label", operation.title + "的审批决定");
      select.append(new Option("请选择处理方式", ""));
      const labels = { approve: operation.approve, reject: "拒绝", edit: "修改参数后执行", respond: "回复代理" };
      for (const type of allowed) {
        if (Object.hasOwn(labels, type)) select.append(new Option(labels[type], type));
      }
      select.addEventListener("change", () => {
        input.hidden = !["reject", "edit", "respond"].includes(select.value);
        input.placeholder = select.value === "edit" ? "填写完整的新参数（JSON 对象）" : select.value === "respond" ? "填写给代理的回复" : "可选：填写拒绝原因";
        input.value = select.value === "edit" ? JSON.stringify(action.args, null, 2) : "";
      });
      section.append(select, input);
      forms.push({ action, select, input });
    } else {
      _approvalButtons(section, item.id, allowed, operation, input);
    }
    if (!allowed.some((type) => ["approve", "reject", "edit", "respond"].includes(type))) {
      section.append(_element("p", "", "服务端未提供可用审批选项，请检查中断数据。"));
    }
    card.append(section);
  }

  if (useForm) {
    const button = _element("button", "primary", "提交审批并继续");
    button.type = "button";
    button.addEventListener("click", () => {
      try {
        const decisions = forms.map(({ action, select, input }) => {
          const type = select.value;
          if (!type) throw new Error("请为每一项操作选择审批决定");
          if (type === "edit") {
            const args = JSON.parse(input.value);
            if (!args || Array.isArray(args) || typeof args !== "object") throw new Error("修改后的参数必须是 JSON 对象");
            return { type, edited_action: { name: action.name, args } };
          }
          if (type === "respond" && !input.value.trim()) throw new Error("请填写给代理的回复");
          return { type, ...(["reject", "respond"].includes(type) && input.value.trim() ? { message: input.value.trim() } : {}) };
        });
        _reply(item.id, { decisions }, "已提交采购操作审批");
      } catch (error) { _notice(error.message); }
    });
    const actions = _element("div", "actions approval-actions");
    actions.append(button);
    card.append(actions);
  }
}

/** 根据中断协议生成补充信息卡片或审批卡片，不猜测未知中断的恢复格式。 */
function _renderInterrupts() {
  ui.interrupts.replaceChildren();
  for (const item of state.interrupts) {
    ui.welcome.hidden = true;
    const card = _element("div", "interrupt-card");
    if (state.replies.has(item.id)) {
      card.append(_element("h3", "", "已选择 · 等待其他事项处理"));
      card.append(_element("p", "", state.replies.get(item.id).label));
      const reset = _element("button", "secondary", "重新选择");
      reset.type = "button";
      reset.addEventListener("click", () => { state.replies.delete(item.id); _renderInterrupts(); });
      card.append(reset);
    } else if (item.value?.kind === "order_info") {
      card.append(_element("h3", "", "需要补充信息"));
      card.append(_element("p", "", item.value.question || "请补充本次任务所需的信息"));
      const form = _element("form");
      const input = _element("textarea");
      input.placeholder = "填写你的补充信息…";
      input.setAttribute("aria-label", "补充采购信息");
      input.required = true;
      const button = _element("button", "primary", "补充并继续");
      button.type = "submit";
      const actions = _element("div", "actions");
      actions.append(button);
      form.append(input, actions);
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        if (input.value.trim()) _reply(item.id, input.value.trim(), input.value.trim());
      });
      card.append(form);
    } else if (Array.isArray(item.value?.action_requests) && item.value.action_requests.length) _approval(card, item);
    else {
      card.append(_element("h3", "", "收到未识别的中断"));
      card.append(_element("pre", "approval-args", JSON.stringify(item.value, null, 2)));
      card.append(_element("p", "", "请检查后端中断协议后再处理。"));
    }
    ui.interrupts.append(card);
  }
  _controls();
}

/** 将 SSE 事件分发到主对话、工具诊断和人工处理中断区域。 */
function _onEvent(event, data) {
  if (event === "session") {
    state.threadId = data.thread_id;
    _rememberThread();
    _controls();
  } else if (event === "token") {
    if (data.source === "main") {
      if (!state.assistant) state.assistant = _message("assistant", "");
      state.assistant.textContent += data.text;
      _scroll();
    } else {
      if (!state.childMessages.has(data.source)) state.childMessages.set(data.source, _trace("子代理消息", ""));
      const node = state.childMessages.get(data.source);
      node.textContent = (node.textContent + data.text).slice(-20000);
    }
  } else if (event === "tool") {
    const title = `${data.status === "calling" ? "调用" : data.status === "error" ? "失败" : "返回"} · ${data.name || "工具"}`;
    const node = _trace(title, { source: data.source, id: data.id, ...(data.status === "calling" ? { args: data.args } : { result: data.result }) }, data.status);
    if (data.status !== "calling") _attachment(node.parentElement, data.result);
    ui.activity.textContent = data.status === "calling" ? `正在调用 ${data.name}` : "继续处理任务…";
  } else if (event === "interrupt") {
    if (!state.interrupts.some((item) => item.id === data.id)) state.interrupts.push(data);
  } else if (event === "done") {
    state.status = data.status;
    if (state.assistant) {
      if (data.answer) _renderAssistantTables(state.assistant, data.answer);
      else state.assistant.parentElement.remove();
      state.assistant = null;
    } else if (data.answer) _message("assistant", data.answer);
    ui.activity.textContent = statusLabels[data.status] || "已结束";
  } else if (event === "error") {
    state.status = "error";
    state.interrupts = [];
    _notice(data.message || "执行失败，请查看服务端日志");
    _trace("执行失败", data, "error");
    ui.activity.textContent = "执行失败";
  }
}

/** 发送新消息或人工回复，并确保任何退出路径都会释放页面等待状态。 */
async function _run(path, body, displayText) {
  if (state.busy) return;
  state.busy = true;
  state.controller = new AbortController();
  state.threadId ||= crypto.randomUUID();
  _rememberThread();
  const previous = state.interrupts;
  let connected = false;
  const previousStatus = state.status;
  state.status = "running";
  state.assistant = null;
  state.childMessages.clear();
  _notice();
  _controls();
  ui.activity.textContent = "正在连接 Agent…";
  const started = Date.now();
  const ticker = setInterval(() => { ui.activity.textContent = `任务处理中 · 已等待 ${Math.floor((Date.now() - started) / 1000)} 秒`; }, 1000);
  try {
    const response = await _request(path, {
      method: "POST", signal: state.controller.signal,
      body: JSON.stringify({ ...body, thread_id: state.threadId, user_id: config.userId, username: config.username }),
    });
    if (!response.headers.get("content-type")?.includes("text/event-stream")) throw new Error("服务端返回了非 SSE 响应，请检查 API 地址");
    connected = true;
    state.interrupts = [];
    state.replies.clear();
    ui.interrupts.replaceChildren();
    _message("user", displayText);
    if (path.endsWith("/stream")) {
      if (state.title === "新的采购会话") state.title = body.message.slice(0, 40);
      ui.message.value = "";
    }
    _controls();
    await readEventStream(response, _onEvent);
  } catch (error) {
    state.status = connected ? "error" : previousStatus;
    if (!connected) { state.interrupts = previous; state.replies.clear(); }
    else state.interrupts = [];
    _notice(error.name === "AbortError" ? "已断开本次响应。请刷新会话记录确认服务端状态，断开不等于撤销采购操作。" : error.message);
    ui.activity.textContent = error.name === "AbortError" ? "连接已断开" : "请求失败";
  } finally {
    clearInterval(ticker);
    state.controller = null;
    state.busy = false;
    state.assistant = null;
    _renderInterrupts();
    _controls();
    _scroll();
    // 历史刷新失败不覆盖本轮真正的执行结果或错误。
    try { await _history(); } catch (error) { _trace("历史刷新失败", error.message, "error"); }
  }
}

/** 打开用户设置面板，编辑当前标签页的用户标识和显示名称。 */
function _settings() {
  ui["user-id"].value = config.userId;
  ui.username.value = config.username;
  ui["config-dialog"].showModal();
}

/** 恢复当前用户最近选择的会话；这里只读历史，不自动恢复采购执行。 */
async function _restore() {
  try {
    const items = await _history();
    const id = sessionStorage.getItem(`erp-agent.thread.${config.userId}`);
    const item = items.find((entry) => entry.thread_id === id);
    if (item) await _openThread(item);
  } catch (error) { _notice(error.message); }
}

ui["chat-scroll"].addEventListener("scroll", _syncChatNavigation, { passive: true });
ui["chat-scroll"].addEventListener("wheel", _cancelChatJump, { passive: true });
ui["chat-scroll"].addEventListener("touchstart", _cancelChatJump, { passive: true });
ui["new-chat"].addEventListener("click", _newChat);
ui["toggle-sidebar"].addEventListener("click", () => _sidebar(!ui.sidebar.classList.contains("is-open")));
ui["close-sidebar"].addEventListener("click", () => _sidebar(false));
ui["sidebar-backdrop"].addEventListener("click", () => _sidebar(false));
// 收起面板时保留记录，便于随时展开查看本轮执行过程。
ui["toggle-trace"].addEventListener("click", () => {
  const panel = ui["trace-panel"];
  panel.hidden = !panel.hidden;
  ui["toggle-trace"].setAttribute("aria-expanded", String(!panel.hidden));
});
document.addEventListener("keydown", (event) => { if (event.key === "Escape") _sidebar(false); });
ui.settings.addEventListener("click", _settings);
ui["close-settings"].addEventListener("click", () => ui["config-dialog"].close());
ui.disconnect.addEventListener("click", () => state.controller?.abort());
ui.message.addEventListener("input", _controls);
ui.message.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); ui.composer.requestSubmit(); }
});
ui.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!state.busy && !state.interrupts.length && state.status !== "running" && ui.message.value.trim()) {
    _run("/api/chat/stream", { message: ui.message.value.trim() }, ui.message.value.trim());
  }
});
ui["refresh-history"].addEventListener("click", async () => {
  if (state.busy) return;
  _notice();
  try {
    const items = await _history();
    const item = items.find((entry) => entry.thread_id === state.threadId);
    if (item) await _openThread(item);
  } catch (error) { _notice(error.message); }
  await _health();
});
ui["config-form"].addEventListener("submit", async (event) => {
  event.preventDefault();
  const next = { userId: ui["user-id"].value.trim(), username: ui.username.value.trim() };
  if (!next.userId || !next.username) return;
  const changed = next.userId !== config.userId;
  config = next;
  sessionStorage.setItem("erp-agent.config", JSON.stringify(config));
  ui["config-dialog"].close();
  if (changed) {
    _clearView();
    state.threadId = null;
    state.status = "";
    state.title = "新的采购会话";
    ui.message.value = "";
    ui.activity.textContent = "就绪";
    _controls();
  }
  await _restore();
  await _health();
});
for (const button of document.querySelectorAll("[data-prompt]")) {
  button.addEventListener("click", () => {
    ui.message.value = button.dataset.prompt;
    _controls();
    ui.message.focus();
  });
}

_controls();
_health();
_restore();
