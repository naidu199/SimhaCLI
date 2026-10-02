// Chat panel script (runs inside the webview).
// Talks to the extension only through the messages in webviewMessages.ts.

import type { FromPanel, PanelState, ToPanel } from "../webviewMessages";

interface VsCodeApi {
  postMessage(message: FromPanel): void;
}
declare function acquireVsCodeApi(): VsCodeApi;

const vscode = acquireVsCodeApi();

function byId<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`Missing element #${id}`);
  }
  return element as T;
}

const statusEl = byId<HTMLDivElement>("status");
const messagesEl = byId<HTMLElement>("messages");
const composer = byId<HTMLFormElement>("composer");
const input = byId<HTMLTextAreaElement>("input");
const sendButton = byId<HTMLButtonElement>("send");
const stopButton = byId<HTMLButtonElement>("stop");
const metaEl = byId<HTMLSpanElement>("meta");

let state: PanelState = { status: "starting" };
let currentTurn: string | null = null;
let assistantText: HTMLElement | null = null;
let thinkingRow: HTMLElement | null = null;
let turnErrorShown = false;
const toolRows = new Map<string, HTMLElement>();

// ---------------------------------------------------------------------------
// Rendering helpers
// ---------------------------------------------------------------------------

function isNearBottom(): boolean {
  return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
}

function append(element: HTMLElement): HTMLElement {
  const stick = isNearBottom();
  messagesEl.append(element);
  if (stick) {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
  return element;
}

function block(className: string, text = ""): HTMLElement {
  const element = document.createElement("div");
  element.className = className;
  element.textContent = text;
  return element;
}

function addMessage(role: "user" | "assistant", text: string): HTMLElement {
  const wrapper = block(`message ${role}`);
  wrapper.append(block("role", role === "user" ? "You" : "SimhaCLI"));
  const body = block("text", text);
  wrapper.append(body);
  append(wrapper);
  return body;
}

function addNotice(text: string, kind: "info" | "error" = "info"): void {
  append(block(`notice ${kind}`, text));
}

function argsSummary(args: unknown): string {
  if (!args || typeof args !== "object") {
    return "";
  }
  const entries = Object.entries(args as Record<string, unknown>);
  const preferred = entries.find(([key]) => ["path", "command", "pattern", "url", "query", "goal"].includes(key));
  const [key, value] = preferred ?? entries[0] ?? [];
  if (key === undefined) {
    return "";
  }
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length > 80 ? `${text.slice(0, 77)}…` : text;
}

function endAssistantText(): void {
  assistantText = null;
}

function clearThinking(): void {
  thinkingRow?.remove();
  thinkingRow = null;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

function renderState(): void {
  const lines: string[] = [];
  let kind = "info";
  let actions = false;

  switch (state.status) {
    case "starting":
      lines.push(state.detail ?? "Starting SimhaCLI…");
      break;
    case "noWorkspace":
      lines.push(state.detail ?? "Open a folder to use SimhaCLI.");
      break;
    case "stopped":
      lines.push(state.detail ?? "SimhaCLI is not running.");
      kind = "error";
      actions = true;
      break;
    case "ready":
      if (state.needsCredentials) {
        lines.push("No API key is configured. Run `simhacli` in a terminal and use /credentials, then restart the backend.");
        kind = "error";
        actions = true;
      } else if (state.detail) {
        lines.push(state.detail);
        kind = "error";
      }
      break;
  }

  statusEl.replaceChildren();
  statusEl.hidden = lines.length === 0;
  statusEl.className = `status ${kind}`;
  if (lines.length > 0) {
    statusEl.append(block("status-text", lines.join("\n")));
  }
  if (actions) {
    const row = block("status-actions");
    const restart = document.createElement("button");
    restart.textContent = "Restart backend";
    restart.addEventListener("click", () => vscode.postMessage({ type: "restartBackend" }));
    const logs = document.createElement("button");
    logs.textContent = "Show logs";
    logs.className = "secondary";
    logs.addEventListener("click", () => vscode.postMessage({ type: "showLogs" }));
    row.append(restart, logs);
    statusEl.append(row);
  }

  const parts = [state.model, state.approval].filter(Boolean);
  metaEl.textContent = parts.join(" · ");
  updateButtons();
}

function updateButtons(): void {
  const running = Boolean(state.turnId) || currentTurn !== null;
  const canSend = state.status === "ready" && !state.needsCredentials && !running;
  sendButton.disabled = !canSend || input.value.trim() === "";
  stopButton.hidden = !running;
}

// ---------------------------------------------------------------------------
// Messages from the extension
// ---------------------------------------------------------------------------

function startTurn(turnId: string): void {
  if (currentTurn === turnId) {
    return;
  }
  currentTurn = turnId;
  assistantText = null;
  turnErrorShown = false;
  toolRows.clear();
}

function handleAgentEvent(turnId: string, event: string, data: Record<string, unknown>): void {
  startTurn(turnId);
  switch (event) {
    case "text_delta": {
      clearThinking();
      if (!assistantText) {
        assistantText = addMessage("assistant", "");
      }
      const stick = isNearBottom();
      assistantText.textContent += String(data.content ?? "");
      if (stick) {
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
      break;
    }
    case "text_complete":
      endAssistantText();
      break;
    case "thinking_delta":
      if (!thinkingRow) {
        thinkingRow = append(block("thinking", "Thinking…"));
      }
      break;
    case "thinking_complete":
      clearThinking();
      break;
    case "tool_call_start": {
      clearThinking();
      endAssistantText();
      const row = block("tool running");
      row.append(block("tool-name", String(data.name ?? "tool")), block("tool-args", argsSummary(data.arguments)));
      toolRows.set(String(data.call_id), append(row));
      break;
    }
    case "tool_call_complete": {
      const row = toolRows.get(String(data.call_id));
      const ok = data.success === true;
      if (row) {
        row.classList.remove("running");
        row.classList.add(ok ? "ok" : "failed");
        if (!ok && data.error) {
          row.append(block("tool-error", String(data.error)));
        }
      } else {
        addNotice(`${String(data.name ?? "tool")} ${ok ? "finished" : `failed: ${String(data.error ?? "")}`}`, ok ? "info" : "error");
      }
      break;
    }
    case "agent_error":
      clearThinking();
      turnErrorShown = true;
      addNotice(String(data.message ?? "Something went wrong"), "error");
      break;
    case "loop_detected":
      addNotice("SimhaCLI noticed it was repeating itself and changed approach.");
      break;
  }
}

window.addEventListener("message", (event: MessageEvent<ToPanel>) => {
  const message = event.data;
  switch (message.type) {
    case "state":
      state = message.state;
      renderState();
      break;
    case "turnStarted":
      startTurn(message.turnId);
      updateButtons();
      break;
    case "sendFailed":
      addNotice(`Not sent: ${message.message}`, "error");
      if (!input.value.trim()) {
        input.value = message.text;
      }
      updateButtons();
      break;
    case "agentEvent":
      handleAgentEvent(message.turnId, message.event, message.data);
      updateButtons();
      break;
    case "turnFinished":
      clearThinking();
      if (message.status === "cancelled") {
        addNotice("Stopped.");
      } else if (message.status === "error" && message.error && !turnErrorShown) {
        addNotice(message.error, "error");
      }
      if (message.undoCount > 0) {
        addNotice(`${message.undoCount} file${message.undoCount === 1 ? "" : "s"} changed.`);
      }
      currentTurn = null;
      assistantText = null;
      updateButtons();
      break;
  }
});

// ---------------------------------------------------------------------------
// Composer
// ---------------------------------------------------------------------------

function submit(): void {
  const text = input.value.trim();
  if (!text || sendButton.disabled) {
    return;
  }
  addMessage("user", text);
  input.value = "";
  sendButton.disabled = true;
  vscode.postMessage({ type: "send", text });
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

renderState();
vscode.postMessage({ type: "ready" });
