// Chat panel script (runs inside the webview).
// Talks to the extension only through the messages in webviewMessages.ts.

import type { ApprovalRequestParams, TranscriptMessage } from "../protocol";
import type { FromPanel, NoticeKind, PanelAttachment, PanelState, ToPanel } from "../webviewMessages";
import { renderMarkdown } from "./markdown";

interface VsCodeApi {
  postMessage(message: FromPanel): void;
}
declare function acquireVsCodeApi(): VsCodeApi;

const vscode = acquireVsCodeApi();

const OUTPUT_PREVIEW_CHARS = 4000;

function byId<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`Missing element #${id}`);
  }
  return element as T;
}

const statusEl = byId<HTMLDivElement>("status");
const messagesEl = byId<HTMLElement>("messages");
const emptyEl = byId<HTMLDivElement>("empty");
const composer = byId<HTMLFormElement>("composer");
const attachmentsEl = byId<HTMLDivElement>("attachments");
const input = byId<HTMLTextAreaElement>("input");
const sendButton = byId<HTMLButtonElement>("send");
const stopButton = byId<HTMLButtonElement>("stop");
const attachButton = byId<HTMLButtonElement>("attach");
const modelButton = byId<HTMLButtonElement>("model");
const approvalButton = byId<HTMLButtonElement>("approval");

let state: PanelState = { status: "starting" };
let currentTurn: string | null = null;
let attachments: PanelAttachment[] = [];
/** Attachments of the last sent message, restored if sending fails. */
let lastSentAttachments: PanelAttachment[] = [];

// Per-turn rendering state
let assistantEl: HTMLElement | null = null;
let assistantRaw = "";
let renderScheduled = false;
let thinkingEl: HTMLDetailsElement | null = null;
let thinkingStarted = 0;
let turnErrorShown = false;
const toolRows = new Map<string, HTMLDetailsElement>();
const approvalCards = new Map<string, HTMLElement>();

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className = "",
  text?: string,
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function button(label: string, className: string, onClick: () => void): HTMLButtonElement {
  const b = el("button", className, label);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

function isNearBottom(): boolean {
  return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
}

function append<T extends HTMLElement>(element: T): T {
  const stick = isNearBottom();
  emptyEl.hidden = true;
  messagesEl.append(element);
  if (stick) {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
  return element;
}

function addUserMessage(text: string, labels: string[] = []): void {
  const wrapper = el("div", "message user");
  wrapper.append(el("div", "role", "You"));
  wrapper.append(el("div", "text", text));
  if (labels.length) {
    const chips = el("div", "sent-attachments");
    for (const label of labels) chips.append(el("span", "chip", label));
    wrapper.append(chips);
  }
  append(wrapper);
}

function addAssistantBlock(): HTMLElement {
  const wrapper = el("div", "message assistant");
  wrapper.append(el("div", "role", "SimhaCLI"));
  const body = el("div", "markdown");
  wrapper.append(body);
  append(wrapper);
  return body;
}

function addNotice(text: string, kind: NoticeKind = "info"): HTMLElement {
  return append(el("div", `notice ${kind}`, text));
}

function shorten(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function argsSummary(args: unknown): string {
  if (!args || typeof args !== "object") {
    return typeof args === "string" ? shorten(args, 80) : "";
  }
  const entries = Object.entries(args as Record<string, unknown>);
  const preferred = entries.find(([key]) =>
    ["path", "command", "pattern", "url", "query", "goal", "action"].includes(key),
  );
  const [key, value] = preferred ?? entries[0] ?? [];
  if (key === undefined) {
    return "";
  }
  return shorten(typeof value === "string" ? value : JSON.stringify(value), 80);
}

function diffBlock(diff: string): HTMLElement {
  const pre = el("pre", "diff");
  for (const line of diff.replace(/\n$/, "").split("\n")) {
    const kind = line.startsWith("+++") || line.startsWith("---")
      ? "meta"
      : line.startsWith("+")
        ? "add"
        : line.startsWith("-")
          ? "del"
          : line.startsWith("@@")
            ? "hunk"
            : "";
    pre.append(el("span", `diff-line ${kind}`, `${line}\n`));
  }
  return pre;
}

function section(title: string, content: HTMLElement): HTMLElement {
  const wrapper = el("div", "tool-section");
  wrapper.append(el("div", "tool-section-title", title), content);
  return wrapper;
}

// ---------------------------------------------------------------------------
// Assistant text (markdown, re-rendered at most once per frame while streaming)
// ---------------------------------------------------------------------------

function renderAssistant(): void {
  renderScheduled = false;
  if (!assistantEl) return;
  const stick = isNearBottom();
  assistantEl.innerHTML = renderMarkdown(assistantRaw);
  if (stick) messagesEl.scrollTop = messagesEl.scrollHeight;
}

function scheduleRender(): void {
  if (!renderScheduled) {
    renderScheduled = true;
    requestAnimationFrame(renderAssistant);
  }
}

function endAssistantText(): void {
  if (assistantEl) renderAssistant();
  assistantEl = null;
  assistantRaw = "";
}

// ---------------------------------------------------------------------------
// Thinking and tools
// ---------------------------------------------------------------------------

function thinkingDelta(text: string): void {
  if (!thinkingEl) {
    thinkingEl = el("details", "thinking");
    thinkingEl.append(el("summary", "", "Thinking…"), el("div", "thinking-text"));
    thinkingStarted = Date.now();
    append(thinkingEl);
  }
  thinkingEl.querySelector(".thinking-text")!.textContent += text;
}

function endThinking(): void {
  if (thinkingEl) {
    const seconds = Math.max(1, Math.round((Date.now() - thinkingStarted) / 1000));
    thinkingEl.querySelector("summary")!.textContent = `Thought for ${seconds}s`;
  }
  thinkingEl = null;
}

function toolRow(name: string, args: unknown, status: string): HTMLDetailsElement {
  const row = el("details", `tool ${status}`);
  const summary = el("summary");
  summary.append(el("span", "tool-icon"), el("span", "tool-name", name), el("span", "tool-args", argsSummary(args)));
  row.append(summary);
  const body = el("div", "tool-body");
  if (args && typeof args === "object" && Object.keys(args).length) {
    body.append(section("Arguments", el("pre", "", JSON.stringify(args, null, 2))));
  }
  row.append(body);
  return row;
}

function toolStart(data: Record<string, unknown>): void {
  endThinking();
  endAssistantText();
  const row = toolRow(String(data.name ?? "tool"), data.arguments, "running");
  toolRows.set(String(data.call_id), append(row));
}

function toolComplete(data: Record<string, unknown>): void {
  let row = toolRows.get(String(data.call_id));
  if (!row) {
    row = append(toolRow(String(data.name ?? "tool"), data.arguments, "running"));
  }
  const ok = data.success === true;
  row.classList.remove("running");
  row.classList.add(ok ? "ok" : "failed");
  const body = row.querySelector(".tool-body")!;
  if (typeof data.diff === "string" && data.diff) {
    body.append(section("Changes", diffBlock(data.diff)));
  } else if (typeof data.output === "string" && data.output.trim()) {
    const output = data.output.length > OUTPUT_PREVIEW_CHARS
      ? `${data.output.slice(0, OUTPUT_PREVIEW_CHARS)}\n… (${data.output.length - OUTPUT_PREVIEW_CHARS} more characters)`
      : data.output;
    body.append(section("Output", el("pre", "", output)));
  }
  if (!ok && data.error) {
    body.append(el("div", "tool-error", String(data.error)));
    row.querySelector("summary")!.append(el("span", "tool-error-inline", shorten(String(data.error), 60)));
  }
}

// ---------------------------------------------------------------------------
// Approvals
// ---------------------------------------------------------------------------

function showApproval(id: string, request: ApprovalRequestParams): void {
  endThinking();
  endAssistantText();
  const card = el("div", `approval${request.isDangerous ? " dangerous" : ""}`);
  card.append(el("div", "approval-title", `Allow ${request.tool}?`));
  card.append(el("div", "approval-description", request.description));
  if (request.command) {
    card.append(el("pre", "approval-command", request.command));
  }
  if (request.paths.length) {
    card.append(el("div", "approval-paths", request.paths.join("\n")));
  }
  if (request.isDangerous) {
    card.append(el("div", "approval-warning", "SimhaCLI flagged this as potentially destructive."));
  }
  const actions = el("div", "approval-actions");
  const approve = button("Approve", "", () => answer(id, true));
  actions.append(approve, button("Deny", "secondary", () => answer(id, false)));
  if (request.fileChange) {
    actions.append(button("View diff", "secondary", () => vscode.postMessage({ type: "viewDiff", id })));
  }
  card.append(actions);
  approvalCards.set(id, append(card));
  approve.focus();
}

function answer(id: string, approved: boolean): void {
  vscode.postMessage({ type: "approvalResponse", id, approved });
  resolveApproval(id, approved);
}

function resolveApproval(id: string, approved: boolean, reason?: string): void {
  const card = approvalCards.get(id);
  if (!card) return;
  approvalCards.delete(id);
  card.querySelector(".approval-actions")?.remove();
  card.classList.add("resolved");
  card.append(el("div", "approval-result", reason === "cancelled" ? "Cancelled" : approved ? "Approved" : "Denied"));
}

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

function clearMessages(): void {
  for (const child of [...messagesEl.children]) {
    if (child !== emptyEl) child.remove();
  }
  emptyEl.hidden = false;
  toolRows.clear();
  approvalCards.clear();
  assistantEl = null;
  assistantRaw = "";
  thinkingEl = null;
}

function loadTranscript(messages: TranscriptMessage[], warning?: string): void {
  clearMessages();
  for (const message of messages) {
    if (message.role === "user") {
      addUserMessage(message.text);
      continue;
    }
    if (message.text) {
      addAssistantBlock().innerHTML = renderMarkdown(message.text);
    }
    for (const call of message.toolCalls) {
      append(toolRow(call.name, call.arguments, "history"));
    }
  }
  addNotice(warning ? `Continuing this chat. ${warning}` : "Continuing this chat.");
}

// ---------------------------------------------------------------------------
// State and composer
// ---------------------------------------------------------------------------

function renderState(): void {
  let text = "";
  let kind: NoticeKind = "info";
  const actions: HTMLButtonElement[] = [];

  switch (state.status) {
    case "starting":
      text = state.detail ?? "Starting SimhaCLI…";
      break;
    case "noWorkspace":
      text = state.detail ?? "Open a folder to use SimhaCLI.";
      break;
    case "stopped":
      text = state.detail ?? "SimhaCLI is not running.";
      kind = "error";
      actions.push(
        button("Restart backend", "", () => vscode.postMessage({ type: "restartBackend" })),
        button("Show logs", "secondary", () => vscode.postMessage({ type: "showLogs" })),
      );
      break;
    case "ready":
      if (state.needsCredentials) {
        text = "No API key is configured yet.";
        kind = "error";
        actions.push(button("Set API key", "", () => vscode.postMessage({ type: "setCredentials" })));
      } else if (state.detail) {
        text = state.detail;
        kind = "error";
      }
      break;
  }

  statusEl.replaceChildren();
  statusEl.hidden = !text;
  statusEl.className = `status ${kind}`;
  if (text) {
    statusEl.append(el("div", "status-text", text));
    if (actions.length) {
      const row = el("div", "status-actions");
      row.append(...actions);
      statusEl.append(row);
    }
  }

  const ready = state.status === "ready";
  modelButton.textContent = state.model ?? "";
  modelButton.hidden = !ready || !state.model;
  approvalButton.textContent = state.approval ? `approval: ${state.approval}` : "";
  approvalButton.hidden = !ready || !state.approval;
  updateButtons();
}

function updateButtons(): void {
  const running = Boolean(state.turnId) || currentTurn !== null;
  const ready = state.status === "ready" && !state.needsCredentials;
  sendButton.disabled = !ready || running || input.value.trim() === "";
  stopButton.hidden = !running;
  attachButton.disabled = state.status !== "ready";
}

function renderAttachments(): void {
  attachmentsEl.replaceChildren();
  attachmentsEl.hidden = attachments.length === 0;
  attachments.forEach((attachment, index) => {
    const chip = el("span", "chip", attachment.label);
    chip.title = attachment.path;
    const remove = button("×", "chip-remove", () => {
      attachments.splice(index, 1);
      renderAttachments();
    });
    remove.setAttribute("aria-label", `Remove ${attachment.label}`);
    chip.append(remove);
    attachmentsEl.append(chip);
  });
}

function addAttachment(attachment: PanelAttachment): void {
  const duplicate = attachments.some(
    (a) => a.path === attachment.path && a.startLine === attachment.startLine && a.endLine === attachment.endLine,
  );
  if (!duplicate) {
    attachments.push(attachment);
    renderAttachments();
  }
}

function startTurn(turnId: string): void {
  if (currentTurn === turnId) return;
  currentTurn = turnId;
  assistantEl = null;
  assistantRaw = "";
  turnErrorShown = false;
  toolRows.clear();
}

// ---------------------------------------------------------------------------
// Messages from the extension
// ---------------------------------------------------------------------------

function handleAgentEvent(turnId: string, event: string, data: Record<string, unknown>): void {
  startTurn(turnId);
  switch (event) {
    case "text_delta":
      endThinking();
      if (!assistantEl) assistantEl = addAssistantBlock();
      assistantRaw += String(data.content ?? "");
      scheduleRender();
      break;
    case "text_complete":
      endAssistantText();
      break;
    case "thinking_delta":
      thinkingDelta(String(data.content ?? ""));
      break;
    case "thinking_complete":
      endThinking();
      break;
    case "tool_call_start":
      toolStart(data);
      break;
    case "tool_call_complete":
      toolComplete(data);
      break;
    case "agent_error":
      endThinking();
      turnErrorShown = true;
      addNotice(String(data.message ?? "Something went wrong"), "error");
      break;
    case "loop_detected":
      addNotice("SimhaCLI noticed it was repeating itself and changed approach.");
      break;
  }
}

function finishTurn(status: string, error: string | undefined, undoCount: number): void {
  endThinking();
  endAssistantText();
  if (status === "cancelled") {
    addNotice("Stopped.");
  } else if (status === "error" && error && !turnErrorShown) {
    addNotice(error, "error");
  }
  if (undoCount > 0) {
    const notice = addNotice(`${undoCount} file${undoCount === 1 ? "" : "s"} changed.`);
    notice.append(" ", button("Revert…", "link", () => vscode.postMessage({ type: "revertChanges" })));
  }
  currentTurn = null;
}

window.addEventListener("message", (event: MessageEvent<ToPanel>) => {
  const message = event.data;
  switch (message.type) {
    case "state":
      state = message.state;
      renderState();
      return;
    case "turnStarted":
      startTurn(message.turnId);
      break;
    case "sendFailed":
      addNotice(`Not sent: ${message.message}`, "error");
      if (!input.value.trim()) input.value = message.text;
      if (attachments.length === 0 && lastSentAttachments.length) {
        attachments = lastSentAttachments;
        renderAttachments();
      }
      break;
    case "agentEvent":
      handleAgentEvent(message.turnId, message.event, message.data);
      break;
    case "turnFinished":
      finishTurn(message.status, message.error, message.undoCount);
      break;
    case "approvalRequest":
      showApproval(message.id, message.request);
      break;
    case "approvalResolved":
      resolveApproval(message.id, message.approved, message.reason);
      break;
    case "addAttachment":
      addAttachment(message.attachment);
      break;
    case "focusInput":
      input.focus();
      break;
    case "loadTranscript":
      loadTranscript(message.messages, message.warning);
      break;
    case "cleared":
      clearMessages();
      break;
    case "notice":
      addNotice(message.text, message.kind);
      break;
  }
  updateButtons();
});

// Copy buttons and links inside rendered replies
messagesEl.addEventListener("click", (event) => {
  const target = event.target as HTMLElement;
  const copy = target.closest(".code-copy");
  if (copy) {
    const code = copy.closest(".code-block")?.querySelector("code")?.textContent ?? "";
    vscode.postMessage({ type: "copy", text: code });
    copy.textContent = "Copied";
    setTimeout(() => (copy.textContent = "Copy"), 1500);
    return;
  }
  const link = target.closest("a");
  if (link) {
    event.preventDefault();
    const href = link.getAttribute("data-href") ?? link.getAttribute("href");
    if (href) vscode.postMessage({ type: "openLink", href });
  }
});

function submit(): void {
  const text = input.value.trim();
  if (!text || sendButton.disabled) return;
  addUserMessage(text, attachments.map((a) => a.label));
  vscode.postMessage({ type: "send", text, attachments });
  input.value = "";
  lastSentAttachments = attachments;
  attachments = [];
  renderAttachments();
  sendButton.disabled = true;
}

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  submit();
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit();
  }
});
input.addEventListener("input", updateButtons);
stopButton.addEventListener("click", () => vscode.postMessage({ type: "cancel" }));
attachButton.addEventListener("click", () => vscode.postMessage({ type: "attachActiveEditor" }));
modelButton.addEventListener("click", () => vscode.postMessage({ type: "pickModel" }));
approvalButton.addEventListener("click", () => vscode.postMessage({ type: "pickApproval" }));

renderState();
vscode.postMessage({ type: "ready" });
