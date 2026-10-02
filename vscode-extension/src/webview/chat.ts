// Chat panel script (runs inside the webview).
// Talks to the extension only through the messages in webviewMessages.ts.

import { APPROVAL_MODES, approvalMode } from "../approvalModes";
import type { ApprovalRequestParams, SessionSummary, TranscriptMessage } from "../protocol";
import type {
  EditorContextUse,
  FromPanel,
  NoticeKind,
  PanelAttachment,
  PanelEditorContext,
  PanelState,
  ToPanel,
} from "../webviewMessages";
import { button, byId, el, shorten } from "./dom";
import { renderHistory } from "./history";
import { icons } from "./icons";
import { renderMarkdown } from "./markdown";

interface VsCodeApi {
  postMessage(message: FromPanel): void;
}
declare function acquireVsCodeApi(): VsCodeApi;

const vscode = acquireVsCodeApi();

const OUTPUT_PREVIEW_CHARS = 4000;
const INPUT_MAX_HEIGHT = 200;

const statusEl = byId<HTMLDivElement>("status");
const chatView = byId<HTMLElement>("chatView");
const historyView = byId<HTMLElement>("historyView");
const messagesEl = byId<HTMLElement>("messages");
const composer = byId<HTMLFormElement>("composer");
const attachmentsEl = byId<HTMLDivElement>("attachments");
const input = byId<HTMLTextAreaElement>("input");
const sendButton = byId<HTMLButtonElement>("send");
const stopButton = byId<HTMLButtonElement>("stop");
const attachButton = byId<HTMLButtonElement>("attach");
const modelButton = byId<HTMLButtonElement>("model");
const modeButton = byId<HTMLButtonElement>("mode");
const modeMenu = byId<HTMLDivElement>("modeMenu");
const historyBack = byId<HTMLButtonElement>("historyBack");
const historySearch = byId<HTMLInputElement>("historySearch");
const historyList = byId<HTMLDivElement>("historyList");

attachButton.innerHTML = icons.paperclip();
sendButton.innerHTML = icons.arrowUp();
stopButton.innerHTML = icons.stop();
historyBack.innerHTML = icons.arrowLeft();

let state: PanelState = { status: "starting" };
let currentTurn: string | null = null;
let attachments: PanelAttachment[] = [];
/** Attachments of the last sent message, restored if sending fails. */
let lastSentAttachments: PanelAttachment[] = [];
let historySessions: SessionSummary[] = [];
/** The active editor (tracked by the extension) and whether to send it. */
let editorContext: PanelEditorContext | null = null;
let editorContextIncluded = false;

// Per-turn rendering state
let turnBody: HTMLElement | null = null;
let assistantEl: HTMLElement | null = null;
let assistantRaw = "";
let renderScheduled = false;
let thinkingEl: HTMLDetailsElement | null = null;
let thinkingStarted = 0;
let turnErrorShown = false;
const toolRows = new Map<string, HTMLDetailsElement>();
const approvalCards = new Map<string, HTMLElement>();

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

const TOOL_LABELS: Record<string, string> = {
  read_file: "Read",
  write_file: "Write",
  edit_file: "Edit",
  shell: "Run",
  grep: "Search",
  glob: "Find files",
  list_dir: "List",
  web_search: "Search the web",
  web_fetch: "Fetch",
  memory: "Memory",
  todos: "Todos",
  workflow: "Workflow",
};

function toolLabel(name: string): string {
  if (TOOL_LABELS[name]) return TOOL_LABELS[name];
  if (name.startsWith("subagent_")) return `Subagent: ${name.slice(9).replace(/_/g, " ")}`;
  if (name.includes("__")) return name.replace("__", ": ").replace(/_/g, " ");
  return name.replace(/_/g, " ");
}

function approvalTitle(request: ApprovalRequestParams): string {
  switch (request.tool) {
    case "shell":
      return "Run this command?";
    case "write_file":
      return request.fileChange?.isNewFile ? "Create this file?" : "Overwrite this file?";
    case "edit_file":
      return "Edit this file?";
    default:
      return `Allow ${toolLabel(request.tool)}?`;
  }
}

function workspaceName(): string {
  const cwd = state.cwd ?? "";
  return cwd.split(/[\\/]/).filter(Boolean).pop() ?? "this workspace";
}

// ---------------------------------------------------------------------------
// Layout helpers
// ---------------------------------------------------------------------------

function isNearBottom(): boolean {
  return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
}

function scrollIfNeeded(stick: boolean): void {
  if (stick) messagesEl.scrollTop = messagesEl.scrollHeight;
}

/** Append to the conversation (or to the current reply, if one is open). */
function append<T extends HTMLElement>(element: T, intoTurn = true): T {
  const stick = isNearBottom();
  removeWelcome();
  (intoTurn && turnBody ? turnBody : messagesEl).append(element);
  scrollIfNeeded(stick);
  return element;
}

function removeWelcome(): void {
  messagesEl.querySelector(".welcome")?.remove();
}

function showView(view: "chat" | "history"): void {
  chatView.hidden = view !== "chat";
  historyView.hidden = view !== "history";
  if (view === "history") historySearch.focus();
}

// ---------------------------------------------------------------------------
// Welcome screen
// ---------------------------------------------------------------------------

const SUGGESTIONS = [
  { icon: icons.compass, title: "Explain this project", prompt: "Give me an overview of this project: what it does, how it's organised, and where to start reading." },
  { icon: icons.bug, title: "Find and fix a bug", prompt: "Help me find and fix a bug: " },
  { icon: icons.flask, title: "Write tests", prompt: "Write tests for " },
  { icon: icons.gitCompare, title: "Review my changes", prompt: "Review my uncommitted changes (git diff) and point out bugs or risky edits." },
];

function renderWelcome(): void {
  if (messagesEl.children.length > 0) return;
  const welcome = el("div", "welcome");
  const logo = el("div", "welcome-logo");
  logo.innerHTML = icons.logo(26);
  const heading = el("h2", "welcome-title", "What can I help you build?");
  const intro = el("p", "welcome-intro");
  intro.append("Reads, edits and runs code in ", el("strong", "", workspaceName()), ". Asks before anything risky.");
  const suggestions = el("div", "suggestions");
  for (const suggestion of SUGGESTIONS) {
    const row = button("", "suggestion", () => {
      input.value = suggestion.prompt;
      autosize();
      updateButtons();
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    });
    const icon = el("span", "suggestion-icon");
    icon.innerHTML = suggestion.icon();
    row.append(icon, el("span", "suggestion-title", suggestion.title));
    suggestions.append(row);
  }
  const hint = el("p", "welcome-hint");
  const hintIcon = el("span", "welcome-hint-icon");
  hintIcon.innerHTML = icons.selection(12);
  hint.append(hintIcon, "Select code in the editor and it's added to your message automatically.");
  welcome.append(logo, heading, intro, suggestions, hint);
  messagesEl.append(welcome);
}

function refreshWelcome(): void {
  const strong = messagesEl.querySelector(".welcome-intro strong");
  if (strong) strong.textContent = workspaceName();
}

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

function addUserMessage(text: string, labels: string[] = []): void {
  closeTurn();
  const wrapper = el("div", "message user");
  const bubble = el("div", "bubble", text);
  wrapper.append(bubble);
  if (labels.length) {
    const chips = el("div", "sent-attachments");
    for (const label of labels) chips.append(el("span", "chip", label));
    wrapper.append(chips);
  }
  append(wrapper, false);
}

/** Open the reply block for the current turn (avatar + name, then content). */
function ensureTurn(): HTMLElement {
  if (turnBody) return turnBody;
  const turn = el("div", "message assistant");
  const header = el("div", "assistant-header");
  const avatar = el("span", "avatar");
  avatar.innerHTML = icons.sparkle(12);
  header.append(avatar, el("span", "assistant-name", "SimhaCLI"));
  const body = el("div", "assistant-body");
  turn.append(header, body);
  append(turn, false);
  turnBody = body;
  return body;
}

function closeTurn(): void {
  endThinking();
  endAssistantText();
  turnBody = null;
}

function addNotice(text: string, kind: NoticeKind = "info", intoTurn = false): HTMLElement {
  const notice = el("div", `notice ${kind}`);
  if (kind === "error") {
    const icon = el("span", "notice-icon");
    icon.innerHTML = icons.alert();
    notice.append(icon);
  }
  notice.append(el("span", "notice-text", text));
  return append(notice, intoTurn);
}

// ---------------------------------------------------------------------------
// Assistant text (markdown, re-rendered at most once per frame while streaming)
// ---------------------------------------------------------------------------

function renderAssistant(): void {
  renderScheduled = false;
  if (!assistantEl) return;
  const stick = isNearBottom();
  assistantEl.innerHTML = renderMarkdown(assistantRaw);
  scrollIfNeeded(stick);
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
    ensureTurn();
    thinkingEl = el("details", "thinking active");
    const summary = el("summary");
    const icon = el("span", "thinking-icon");
    icon.innerHTML = icons.sparkle(12);
    const chevron = el("span", "chevron");
    chevron.innerHTML = icons.chevronRight(12);
    summary.append(icon, el("span", "thinking-label", "Thinking…"), chevron);
    thinkingEl.append(summary, el("div", "thinking-text"));
    thinkingStarted = Date.now();
    append(thinkingEl);
  }
  thinkingEl.querySelector(".thinking-text")!.textContent += text;
}

function endThinking(): void {
  if (thinkingEl) {
    const seconds = Math.max(1, Math.round((Date.now() - thinkingStarted) / 1000));
    thinkingEl.querySelector(".thinking-label")!.textContent = `Thought for ${seconds}s`;
    thinkingEl.classList.remove("active");
  }
  thinkingEl = null;
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
  if (key === undefined) return "";
  return shorten(typeof value === "string" ? value : JSON.stringify(value), 80);
}

function diffBlock(diff: string): HTMLElement {
  const pre = el("pre", "diff");
  for (const line of diff.replace(/\n$/, "").split("\n")) {
    const kind =
      line.startsWith("+++") || line.startsWith("---")
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

function setToolStatus(row: HTMLDetailsElement, status: "running" | "ok" | "failed" | "history"): void {
  row.classList.remove("running", "ok", "failed", "history");
  row.classList.add(status);
  const icon = row.querySelector(".tool-status")!;
  icon.innerHTML =
    status === "running" ? icons.loader(13) : status === "ok" ? icons.check(13) : status === "failed" ? icons.x(13) : icons.chevronRight(12);
}

function toolRow(name: string, args: unknown, status: "running" | "history"): HTMLDetailsElement {
  const row = el("details", "tool");
  const summary = el("summary");
  summary.title = name;
  summary.append(el("span", "tool-status"), el("span", "tool-name", toolLabel(name)), el("code", "tool-args", argsSummary(args)));
  row.append(summary);
  const body = el("div", "tool-body");
  if (args && typeof args === "object" && Object.keys(args).length) {
    body.append(section("Arguments", el("pre", "", JSON.stringify(args, null, 2))));
  }
  row.append(body);
  setToolStatus(row, status);
  return row;
}

function toolStart(data: Record<string, unknown>): void {
  endThinking();
  endAssistantText();
  ensureTurn();
  const row = toolRow(String(data.name ?? "tool"), data.arguments, "running");
  toolRows.set(String(data.call_id), append(row));
}

function toolComplete(data: Record<string, unknown>): void {
  ensureTurn();
  let row = toolRows.get(String(data.call_id));
  if (!row) row = append(toolRow(String(data.name ?? "tool"), data.arguments, "running"));
  const ok = data.success === true;
  setToolStatus(row, ok ? "ok" : "failed");
  const body = row.querySelector(".tool-body")!;
  if (typeof data.diff === "string" && data.diff) {
    body.append(section("Changes", diffBlock(data.diff)));
  } else if (typeof data.output === "string" && data.output.trim()) {
    const output =
      data.output.length > OUTPUT_PREVIEW_CHARS
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
  ensureTurn();
  const card = el("div", `approval${request.isDangerous ? " dangerous" : ""}`);
  const header = el("div", "approval-header");
  const icon = el("span", "approval-icon");
  icon.innerHTML = request.isDangerous ? icons.alert() : icons.shield();
  header.append(icon, el("span", "approval-title", approvalTitle(request)));
  card.append(header);

  if (request.command) {
    card.append(el("pre", "approval-command", request.command));
  } else if (request.paths.length) {
    card.append(el("div", "approval-paths", request.paths.join("\n")));
  } else if (request.description) {
    // Only when there's nothing more specific to show (it repeats the path)
    card.append(el("div", "approval-description", request.description));
  }
  if (request.isDangerous) {
    card.append(el("div", "approval-warning", "Flagged as potentially destructive. Check it carefully."));
  }

  const actions = el("div", "approval-actions");
  const approve = button("Approve", "", () => answer(id, true));
  actions.append(approve, button("Deny", "secondary", () => answer(id, false)));
  if (request.fileChange) {
    const diff = button("", "secondary with-icon", () => vscode.postMessage({ type: "viewDiff", id }));
    diff.innerHTML = `${icons.fileDiff()}<span>View diff</span>`;
    actions.append(diff);
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
  const outcome = reason === "cancelled" ? "cancelled" : approved ? "approved" : "denied";
  card.classList.add("resolved", outcome);
  const result = el("div", "approval-result");
  result.innerHTML = outcome === "approved" ? icons.check(13) : icons.x(13);
  result.append(outcome === "approved" ? "Approved" : outcome === "denied" ? "Denied" : "Cancelled");
  card.append(result);
}

// ---------------------------------------------------------------------------
// History and transcripts
// ---------------------------------------------------------------------------

function clearMessages(): void {
  messagesEl.replaceChildren();
  toolRows.clear();
  approvalCards.clear();
  turnBody = null;
  assistantEl = null;
  assistantRaw = "";
  thinkingEl = null;
  renderWelcome();
}

function loadTranscript(messages: TranscriptMessage[], warning?: string): void {
  clearMessages();
  for (const message of messages) {
    if (message.role === "user") {
      addUserMessage(message.text);
      continue;
    }
    const body = ensureTurn();
    if (message.text) {
      const text = el("div", "markdown");
      text.innerHTML = renderMarkdown(message.text);
      body.append(text);
    }
    for (const call of message.toolCalls) {
      body.append(toolRow(call.name, call.arguments, "history"));
    }
  }
  turnBody = null;
  if (warning) addNotice(warning);
  showView("chat");
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function showHistory(sessions: SessionSummary[]): void {
  historySessions = sessions;
  drawHistory();
  showView("history");
}

function drawHistory(): void {
  renderHistory(historyList, historySessions, historySearch.value, {
    open: (session) => {
      if (session.isCurrent) {
        showView("chat");
      } else {
        vscode.postMessage({ type: "resumeSession", id: session.id });
      }
    },
    remove: (session) => vscode.postMessage({ type: "deleteSession", id: session.id }),
  });
}

// ---------------------------------------------------------------------------
// Status banner, composer and mode menu
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
        text = "Add an API key to start chatting.";
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
  modelButton.hidden = !ready || !state.model;
  modelButton.innerHTML = `<span class="pill-text"></span>${icons.chevronDown(11)}`;
  modelButton.querySelector(".pill-text")!.textContent = state.model ?? "";
  modelButton.title = `Model: ${state.model ?? ""} (click to change)`;

  const mode = approvalMode(state.approval);
  modeButton.hidden = !ready || !state.approval;
  modeButton.className = `pill mode risk-${mode.risk}`;
  modeButton.innerHTML = `<span class="dot"></span><span class="pill-text"></span>${icons.chevronDown(11)}`;
  modeButton.querySelector(".pill-text")!.textContent = mode.label;
  modeButton.title = `Approval mode: ${mode.label}. ${mode.description}`;
  if (!modeMenu.hidden) renderModeMenu();

  refreshWelcome();
  updateButtons();
}

function updateButtons(): void {
  const running = Boolean(state.turnId) || currentTurn !== null;
  const ready = state.status === "ready" && !state.needsCredentials;
  sendButton.disabled = !ready || running || input.value.trim() === "";
  sendButton.hidden = running;
  stopButton.hidden = !running;
  attachButton.disabled = state.status !== "ready";
}

function autosize(): void {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, INPUT_MAX_HEIGHT)}px`;
}

function renderModeMenu(): void {
  modeMenu.replaceChildren(el("div", "menu-title", "Approval mode"));
  for (const mode of APPROVAL_MODES) {
    const option = button("", `menu-item risk-${mode.risk}${mode.policy === state.approval ? " selected" : ""}`, () => {
      closeModeMenu();
      if (mode.policy !== state.approval) {
        vscode.postMessage({ type: "setApproval", policy: mode.policy });
      }
    });
    option.setAttribute("role", "menuitemradio");
    option.setAttribute("aria-checked", String(mode.policy === state.approval));
    const label = el("span", "menu-item-label");
    label.append(el("span", "dot"), el("span", "", mode.label));
    if (mode.policy === state.approval) {
      const check = el("span", "menu-check");
      check.innerHTML = icons.check(13);
      label.append(check);
    }
    option.append(label, el("span", "menu-item-description", mode.description));
    modeMenu.append(option);
  }
}

function openModeMenu(): void {
  renderModeMenu();
  modeMenu.hidden = false;
  modeButton.setAttribute("aria-expanded", "true");
  (modeMenu.querySelector(".menu-item.selected") as HTMLElement | null)?.focus();
}

function closeModeMenu(): void {
  modeMenu.hidden = true;
  modeButton.setAttribute("aria-expanded", "false");
}

function editorContextUse(): EditorContextUse {
  if (!editorContext || !editorContextIncluded) return "none";
  return editorContext.hasSelection ? "selection" : "file";
}

/** Chip for the active editor: a selection is included by default, a whole file on request. */
function contextChip(context: PanelEditorContext): HTMLElement {
  const chip = el("button", `chip context-chip${editorContextIncluded ? " included" : ""}${context.hasSelection ? " selection" : ""}`);
  chip.type = "button";
  const icon = el("span", "chip-icon");
  icon.innerHTML = editorContextIncluded
    ? context.hasSelection ? icons.selection() : icons.file()
    : icons.plus();
  chip.append(icon, el("span", "chip-label", context.label));
  if (context.hasSelection) {
    chip.append(el("span", "chip-meta", `${context.lineCount} line${context.lineCount === 1 ? "" : "s"}`));
  }
  chip.title = editorContextIncluded
    ? `${context.hasSelection ? "Selected lines" : "This file"} will be sent with your message. Click to leave it out.`
    : `Click to send ${context.hasSelection ? "the selected lines" : "this file"} with your message.`;
  chip.setAttribute("aria-pressed", String(editorContextIncluded));
  chip.addEventListener("click", () => {
    editorContextIncluded = !editorContextIncluded;
    renderAttachments();
  });
  return chip;
}

function renderAttachments(): void {
  attachmentsEl.replaceChildren();
  attachmentsEl.hidden = attachments.length === 0 && !editorContext;
  if (editorContext) {
    attachmentsEl.append(contextChip(editorContext));
  }
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

// ---------------------------------------------------------------------------
// Turns
// ---------------------------------------------------------------------------

function startTurn(turnId: string): void {
  if (currentTurn === turnId) return;
  currentTurn = turnId;
  assistantEl = null;
  assistantRaw = "";
  turnErrorShown = false;
  toolRows.clear();
}

function handleAgentEvent(turnId: string, event: string, data: Record<string, unknown>): void {
  startTurn(turnId);
  switch (event) {
    case "text_delta":
      endThinking();
      if (!assistantEl) {
        ensureTurn();
        assistantEl = append(el("div", "markdown"));
      }
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
      ensureTurn();
      addNotice(String(data.message ?? "Something went wrong"), "error", true);
      break;
    case "loop_detected":
      ensureTurn();
      addNotice("SimhaCLI noticed it was repeating itself and changed approach.", "info", true);
      break;
  }
}

function finishTurn(status: string, error: string | undefined, undoCount: number): void {
  endThinking();
  endAssistantText();
  if (status === "cancelled") {
    ensureTurn();
    addNotice("Stopped.", "info", true);
  } else if (status === "error" && error && !turnErrorShown) {
    ensureTurn();
    addNotice(error, "error", true);
  }
  if (undoCount > 0) {
    const footer = el("div", "turn-footer");
    footer.append(el("span", "", `${undoCount} file${undoCount === 1 ? "" : "s"} changed`));
    const revert = button("", "link with-icon", () => vscode.postMessage({ type: "revertChanges" }));
    revert.innerHTML = `${icons.undo()}<span>Revert…</span>`;
    footer.append(revert);
    ensureTurn();
    append(footer);
  }
  currentTurn = null;
  turnBody = null;
}

// ---------------------------------------------------------------------------
// Messages from the extension
// ---------------------------------------------------------------------------

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
      autosize();
      break;
    case "agentEvent":
      handleAgentEvent(message.turnId, message.event, message.data);
      break;
    case "turnFinished":
      finishTurn(message.status, message.error, message.undoCount);
      break;
    case "approvalRequest":
      showView("chat");
      showApproval(message.id, message.request);
      break;
    case "approvalResolved":
      resolveApproval(message.id, message.approved, message.reason);
      break;
    case "addAttachment":
      showView("chat");
      addAttachment(message.attachment);
      break;
    case "focusInput":
      showView("chat");
      input.focus();
      break;
    case "loadTranscript":
      loadTranscript(message.messages, message.warning);
      break;
    case "cleared":
      clearMessages();
      showView("chat");
      break;
    case "notice":
      addNotice(message.text, message.kind);
      break;
    case "history":
      showHistory(message.sessions);
      break;
    case "editorContext": {
      const previous = editorContext?.label;
      editorContext = message.context;
      // A new selection is included by default; a plain file only on request
      if (editorContext && editorContext.label !== previous) {
        editorContextIncluded = editorContext.hasSelection;
      }
      renderAttachments();
      break;
    }
    case "userMessage":
      showView("chat");
      addUserMessage(message.text, message.labels);
      break;
    case "prefill":
      showView("chat");
      input.value = message.text;
      autosize();
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
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
  closeModeMenu();
  const use = editorContextUse();
  const labels = [...(use !== "none" && editorContext ? [editorContext.label] : []), ...attachments.map((a) => a.label)];
  addUserMessage(text, labels);
  vscode.postMessage({ type: "send", text, attachments, editorContext: use });
  input.value = "";
  autosize();
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
input.addEventListener("input", () => {
  autosize();
  updateButtons();
});
stopButton.addEventListener("click", () => vscode.postMessage({ type: "cancel" }));
attachButton.addEventListener("click", () => vscode.postMessage({ type: "attachFiles" }));
modelButton.addEventListener("click", () => vscode.postMessage({ type: "pickModel" }));
modeButton.addEventListener("click", (event) => {
  event.stopPropagation();
  if (modeMenu.hidden) openModeMenu();
  else closeModeMenu();
});
document.addEventListener("click", (event) => {
  if (!modeMenu.hidden && !modeMenu.contains(event.target as Node)) closeModeMenu();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (!modeMenu.hidden) {
      closeModeMenu();
      modeButton.focus();
    } else if (!historyView.hidden) {
      showView("chat");
    }
  }
});
historyBack.addEventListener("click", () => showView("chat"));
historySearch.addEventListener("input", drawHistory);

renderWelcome();
renderState();
vscode.postMessage({ type: "ready" });
