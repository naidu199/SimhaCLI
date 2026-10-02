# SimhaCLI Server & VS Code Extension: Build Plan (Phase 1)

**Branch:** `feat/simhacli-server`
**Status:** M1–M2 done; M3 complete (awaiting review); M4 next

Phase 1 brings SimhaCLI into VS Code as a sidebar chat panel. It runs the same agent as the CLI, with the same tools, approvals, saved chats, undo, config and API key. Phase 2 (inline code suggestions) is out of scope here.

Progress is tracked in the [implementation checklist](#implementation-checklist): tick an item when it is merged into this branch.

---

## 1. Scope

**In scope**
- `simhacli serve`: a long-running backend with no terminal UI, controlled over stdin/stdout.
- A VS Code extension in `vscode-extension/` with an activity-bar icon and a chat panel.
- Chat with streaming text and thinking, tool call display, Stop.
- Tool approvals as VS Code pop-ups, with a diff view for file edits.
- Chat history: list, read, resume, new chat, delete (uses the auto-saved sessions).
- Model, approval policy and credentials settings from the panel.
- Undo of the agent's file changes.
- Attaching the current file or selection to a message.

**Out of scope for Phase 1**
- Inline code suggestions (Phase 2).
- `/workflow`, `/init`, `/run` and `/bot` in the panel.
- More than one workspace folder: the first folder is used.
- Publishing to the VS Code Marketplace. A `.vsix` file for local install is in scope.

---

## 2. Architecture

```
VS Code extension (TypeScript)                  simhacli serve (Python, long-running)
┌────────────────────────────┐  stdin: JSON    ┌───────────────────────────────┐
│ Chat panel (HTML/TS)       │ ──────────────▶ │ AgentServer                   │
│ Backend client             │ ◀────────────── │  └ Agent / Session (existing) │
│ Approval pop-ups, diff view│  stdout: JSON   │ stderr = logs only            │
└────────────────────────────┘                 └───────────────────────────────┘
```

- The extension starts one `simhacli serve --cwd <workspace folder>` process and keeps it running for the whole VS Code window.
- Communication is newline-delimited JSON (one message per line) over stdin/stdout. Both sides can send requests. The server sends requests to the extension for approvals.
- Why stdin/stdout: no network port, no auth token, the process ends with VS Code, and it behaves the same on Windows.

### Design rules

1. **stdout is protocol-only.** The server writes protocol messages to a private copy of the real stdout. `sys.stdout` is then pointed at stderr, so a stray `print()`, Rich output or subagent progress line can never corrupt the protocol.
2. **The server never reads stdin for anything except protocol messages.**
   - Config is loaded with `load_config(prompt_api=False)`. A missing API key is reported as `needsCredentials`, never asked for on stdin.
   - The CLI's `q` stop check (`main.py`, `_check_stop_input`) is never used in serve mode. Serve mode has its own turn loop and does not reuse `SimhaCLI._process_message`.
3. **One turn at a time per server.** `chat/send` while a turn is running returns an error. Use `chat/cancel` to stop.
4. **The CLI and the server share logic.** Session, history and undo logic moves out of the console-printing slash commands into plain functions that return data. CLI commands and server methods both call these functions.
5. **The UI is replaceable.** The panel talks to the extension only through a typed message contract (`webview ⇄ extension`). It never talks to the backend directly, so the plain HTML/TS panel can later be swapped for a framework without touching the extension or the server.
6. **Approvals fail closed.** If the extension doesn't answer an approval request (it crashed, or the panel closed), the server treats it as denied.

---

## 3. Protocol (v1)

**Message shapes**
- Request: `{"id": 1, "method": "chat/send", "params": {...}}`
- Response: `{"id": 1, "result": {...}}` or `{"id": 1, "error": {"code": -32000, "message": "..."}}`
- Notification (no reply): `{"method": "agent/event", "params": {...}}`

Ids are unique per sender. Server-initiated requests use string ids (`"s1"`, `"s2"`, …) so they never collide with the extension's numeric ids.

### Extension → Server

| Method | Params | Result |
|---|---|---|
| `initialize` | `{cwd?, clientName?, clientVersion?, protocolVersion?}` | `{serverVersion, protocolVersion, cwd, model, approval, sessionId, needsCredentials}`. `clientName` is recorded as the saved chat's source. |
| `chat/send` | `{text, attachments?: [{path, startLine?, endLine?}]}` | `{turnId}`; output arrives as `agent/event` notifications |
| `chat/cancel` | `{turnId}` | `{cancelled: bool}` |
| `sessions/list` | `{limit?}` | `{sessions: [{id, title, createdAt, updatedAt, messageCount, cwd, model, source, isCurrent}]}` |
| `sessions/history` | `{id?}` (default: current chat) | `{id, title, messages: [{role, text, toolCalls: [{name, arguments}]}]}` |
| `sessions/resume` | `{id}` (full id, prefix or list number) | `{sessionId, title, messages, warning?}` |
| `sessions/new` | `{}` | `{sessionId}` |
| `sessions/delete` | `{id}` | `{deleted: bool}` |
| `config/get` | `{}` | `{model, approval, approvalPolicies[], cwd, autoSaveSessions, apiBaseUrl, hasApiKey}` |
| `model/set` | `{name}` | `{model, savedTo?, saveError?}` |
| `approval/set` | `{policy}` | `{approval, savedTo?, saveError?}` |
| `credentials/set` | `{apiKey?, baseUrl?}` | `{needsCredentials}` |
| `undo/list` | `{}` | `{changes: [{index, path, isNewFile}]}` |
| `undo/revert` | `{index}` or `{all: true}` | `{reverted: [path], skipped: [{path, status, reason}], remaining}` |
| `shutdown` | `{}` | `{}` (server exits after replying) |

### Server → Extension

| Message | Kind | Payload |
|---|---|---|
| `agent/event` | notification | `{turnId, type, data}`. `type` is an `AgentEventType` value: `agent_start`, `text_delta`, `text_complete`, `thinking_delta`, `thinking_complete`, `tool_call_start`, `tool_call_complete`, `loop_detected`, `agent_error`, `agent_end`. `data` is the event's existing data dict, JSON-safe. |
| `turn/finished` | notification | `{turnId, status: "completed" \| "cancelled" \| "error", undoCount, error?}` |
| `approval/request` | request | `{turnId, tool, description, params, command?, paths[], diff?, isDangerous}`, answered with `{approved: bool}`. If the turn is cancelled while the request is open, a later answer is ignored. |
| `server/log` | notification | `{level, message}`, for the extension's Output channel |

### Error codes

| Code | Meaning |
|---|---|
| `-32700` | Invalid JSON |
| `-32601` | Unknown method |
| `-32602` | Invalid params |
| `-32001` | Not initialized |
| `-32002` | Turn already running |
| `-32003` | Credentials missing |
| `-32000` | Other server error (message explains) |

---

## 4. Folder layout

```
server/                     # new Python package (backend)
  __init__.py
  protocol.py               # JSON-lines framing, stdout protection, stdin reader thread
  agent_server.py           # AgentServer: Agent lifecycle, method dispatch, turns, approvals
  serialization.py          # AgentEvent / ToolConfirmation → JSON-safe dicts
  attachments.py            # chat/send text + attachments → agent message
services/                   # new: logic shared by CLI commands and the server
  sessions.py               # list / history / resume / new / delete
  undo.py                   # list / revert
  settings.py               # model / approval policy / credentials
scripts/
  serve_smoke_test.py       # drives a real `simhacli serve` with a fake LLM

vscode-extension/
  package.json              # activity bar view, commands, settings
  tsconfig.json
  esbuild.mjs
  src/
    extension.ts            # activate / deactivate, command registration
    backend.ts              # spawn server, request/response matching, restart, Output channel
    protocol.ts             # TypeScript types for the server protocol (mirrors section 3)
    controller.ts           # backend lifecycle per VS Code window, events for the panel
    variables.ts            # ${workspaceFolder} / ${userHome} expansion in settings
    chatViewProvider.ts     # WebviewViewProvider, bridges panel ⇄ backend
    approvals.ts            # approval pop-ups + diff view
    webviewMessages.ts      # typed panel ⇄ extension message contract (design rule 5)
    webview/
      chat.ts               # panel script (bundled to dist/webview.js)
      tsconfig.json         # DOM typings for the panel only
  media/
    chat.css  simhacli.svg
  README.md
```

---

## 5. Implementation checklist

Mark items `[x]` when merged into this branch. Each milestone ends with a **Done when** check that must pass before the next milestone starts.

### M1: Server core (Python)

- [x] **M1.1** Create the `server/` package and add it to `[tool.setuptools] packages` in `pyproject.toml`
- [x] **M1.2** `protocol.py`: JSON-lines reader on a background thread (works on Windows)
- [x] **M1.3** `protocol.py`: writer on a private duplicate of the real stdout; `sys.stdout` redirected to stderr
- [x] **M1.4** `protocol.py`: request/response matching for server-initiated requests (`approval/request`)
- [x] **M1.5** `protocol.py`: parse errors (`-32700`) and unknown methods (`-32601`) answered without crashing
- [x] **M1.6** `serialization.py`: `AgentEvent` → JSON-safe dict (paths, datetimes, `FileDiff`, `TokenUsage`)
- [x] **M1.7** `serialization.py`: `ToolConfirmation` → approval payload, including the diff text
- [x] **M1.8** `agent_server.py`: `initialize`, using `load_config(prompt_api=False)` and reporting `needsCredentials`
- [x] **M1.9** `agent_server.py`: `chat/send` runs a turn as an asyncio task and streams `agent/event` notifications
- [x] **M1.10** `agent_server.py`: attachments (`path`, optional line range) via the existing `utils/file_attachments.py`
- [x] **M1.11** `agent_server.py`: `chat/cancel`; the session stays usable afterwards (no orphaned tool calls)
- [x] **M1.12** `agent_server.py`: `-32002` when a turn is already running
- [x] **M1.13** `agent_server.py`: approval callback sends `approval/request` and waits; a missing answer counts as denied
- [x] **M1.14** `agent_server.py`: auto-save after every turn (same as the CLI)
- [x] **M1.15** `agent_server.py`: `turn/finished` with status and undo count
- [x] **M1.16** `agent_server.py`: `shutdown`, plus clean exit on stdin EOF (MCP servers and HTTP client closed)
- [x] **M1.17** `simhacli serve [--cwd PATH]` click subcommand in `main.py`
- [x] **M1.18** `scripts/serve_smoke_test.py`: starts the real server with a fake LLM and checks streaming, approval round trip (approve and deny), cancel, the busy error, a clean stdout, and shutdown

**Done when:** `python scripts/serve_smoke_test.py` passes on macOS, and the CLI (`simhacli`) still works unchanged.

**Result (2026-10-02):** smoke test passes 34/34 (3 consecutive runs); CLI regression scripts pass; one real-model run through `simhacli serve` (streaming, thinking, tool call, shutdown) succeeded.
Additions beyond the original list:
- `server/attachments.py` builds the agent message (inline `@path` + explicit attachments with line ranges).
- `agent/agent.py` now emits `tool_call_start` *before* a tool runs (previously only after it finished), so both the CLI and the panel can show a tool as running before its approval prompt.
- Child processes get stdin from the null device in serve mode, so a command like `cat` can't consume protocol messages.
- Extra smoke-test coverage: cancel while an approval is open (late answer ignored), subagent console output routed to stderr.

### M2: Server features + shared logic (Python)

- [x] **M2.1** `services/sessions.py`: move list, history, resume, new and delete logic out of `cli/commands/session_commands.py`
- [x] **M2.2** `services/undo.py`: move list and revert logic out of `cli/commands/undo_commands.py`
- [x] **M2.3** Refactor the CLI commands (`/sessions`, `/history`, `/resume`, `/clear`, `/undo`) to call the shared services, with no behaviour change
- [x] **M2.4** Server: `sessions/list`, `sessions/history`, `sessions/resume`, `sessions/new`, `sessions/delete`
- [x] **M2.5** Server: `config/get`, `model/set`, `approval/set` (also updates the live ApprovalManager)
- [x] **M2.6** Server: `credentials/set`, saved the same way as `/credentials`
- [x] **M2.7** Server: `undo/list`, `undo/revert`
- [x] **M2.8** Extend `serve_smoke_test.py` to cover every M2 method
- [x] **M2.9** Re-run the existing session/undo verification for the CLI

**Done when:** the smoke test covers all protocol methods, and the CLI `/sessions`, `/history`, `/resume`, `/clear` and `/undo` behave as before.

**Result (2026-10-02):** smoke test passes 61/61 (3 consecutive runs); CLI regression passes, including a new test for the refactored `/undo`, `/model`, `/approval` and `/credentials`; a one-shot CLI run against the fake model works.
Additions beyond the original list:
- `services/settings.py` (model, approval, credentials) so `/model`, `/approval`, `/credentials` and the server share one implementation.
- `sessions/list` items include `isCurrent` and `model`; `sessions/resume` may return a `warning` when the chat was started in another directory; `undo/revert` also returns `remaining`; `model/set` / `approval/set` return `savedTo` or `saveError`.
- State-changing methods (`sessions/new`, `sessions/resume`, `model/set`, `credentials/set`, `undo/revert`) return `-32002` while a turn is running. `approval/set` is allowed mid-turn.
- Fixed a pre-existing bug: `simhacli "<prompt>"` failed with "No such command" since the `bot` subcommand was added. Words that aren't a subcommand are now treated as the prompt.

### M3: Extension skeleton (TypeScript)

- [x] **M3.1** Scaffold `vscode-extension/`: `package.json`, `tsconfig.json`, esbuild bundling, `.vscodeignore`, F5 launch config
- [x] **M3.2** Activity-bar icon and `simhacli.chat` webview view
- [x] **M3.3** Settings `simhacli.command` (default `simhacli`) and `simhacli.args`
- [x] **M3.4** `protocol.ts`: types matching section 3
- [x] **M3.5** `backend.ts`: spawn the server, match requests to responses, Output channel for stderr and `server/log`
- [x] **M3.6** `backend.ts`: run `initialize` on start; restart with a user-visible notice if the process exits
- [x] **M3.7** `webviewMessages.ts`: typed panel ⇄ extension contract
- [x] **M3.8** Minimal panel: message box, Send, streamed assistant text

**Done when:** in the F5 development window, sending a message streams a reply from the real configured model.

**Result (2026-10-02):** automated tests (kept outside the repo) pass: backend 15/15 against the real `simhacli serve`, panel script 25/25 in jsdom, integration 14/14 inside a real VS Code window (panel ready in ~115 ms; no backend processes left after VS Code exits). The F5 check against the real model is the manual step for review.
Additions beyond the original list:
- Basic approval pop-ups (Approve / close = deny) are in M3, otherwise any tool needing approval would leave a turn hanging. M4.4 adds the diff view.
- `controller.ts` owns the backend lifecycle (start per workspace folder, restart on settings or folder changes, crash notice); `backend.ts` stays free of the `vscode` API so it can be tested from plain Node.
- `${workspaceFolder}` and `${userHome}` are expanded in `simhacli.command` / `simhacli.args` (VS Code doesn't do this for extension settings).
- The extension declares it doesn't run in untrusted workspaces (it runs an agent that edits files and runs commands).
- F5 setup lives in the repo's `.vscode/` (launch, build task, and settings pointing at this checkout's `main.py`); that folder is gitignored, so it stays local.

### M4: Extension features (TypeScript)

- [ ] **M4.1** Markdown rendering with code highlighting and a copy button on code blocks
- [ ] **M4.2** Thinking shown in a collapsible block
- [ ] **M4.3** Tool calls shown as collapsible rows (name, short arguments, success/failure, output preview)
- [ ] **M4.4** Approval pop-up (Approve / Deny); file edits offer **View diff** in VS Code's diff editor before deciding
- [ ] **M4.5** Stop button (`chat/cancel`) while a turn is running
- [ ] **M4.6** Attach current file / selection button; **SimhaCLI: Ask About Selection** in the editor right-click menu
- [ ] **M4.7** New Chat and History (quick pick of saved chats → resume, with previous messages rendered)
- [ ] **M4.8** Model and approval policy shown in the panel header and editable
- [ ] **M4.9** Missing-credentials flow: prompt for API key and base URL, then `credentials/set`
- [ ] **M4.10** Undo: "N files changed. Revert" action after a turn, using `undo/list` and `undo/revert`
- [ ] **M4.11** Panel follows VS Code light, dark and high-contrast themes

**Done when:** this manual pass works: read a file; edit a file with approval and diff; a shell command needing approval; cancel mid-tool; resume an old chat; revert a change.

### M5: Polish & packaging

- [ ] **M5.1** Clear errors for: `simhacli` not found (with install hint), backend crash, protocol version mismatch
- [ ] **M5.2** Extension `README.md`: install, settings, using a virtualenv's `simhacli`; third-party notice for the activity-bar icon (built from Lucide icons, ISC License)
- [ ] **M5.3** Build a `.vsix` file with `vsce package` and install it into everyday VS Code
- [ ] **M5.4** Update `AGENTS.md`, `README.md` and `SIMHACLI.md` with `simhacli serve` and the extension
- [ ] **M5.5** Windows check: spawning `simhacli.exe`, stdin reader thread, path handling

**Done when:** the `.vsix` is installed in everyday VS Code and used for a real task end to end.

---

## 6. Known risks

| Risk | Mitigation |
|---|---|
| Something writes to stdout and breaks the protocol | Design rule 1; the smoke test asserts every stdout line is valid JSON |
| Server hangs waiting on a stdin prompt | Design rule 2; no `Prompt.ask` / `Confirm.ask` reachable in serve mode |
| Users with SimhaCLI in a virtualenv | `simhacli.command` setting; README section |
| Packaging installs generic top-level modules (`utils`, `config`, `tools`) that can clash with other packages | Known issue; fix before Marketplace publishing (post Phase 1) |
| Long tool calls (shell, MCP) during cancel | Shell process-group kill and MCP call timeouts already exist; cancel is covered by the smoke test |

---

## 7. Decisions log

| Date | Decision |
|---|---|
| 2026-10-02 | Phase 1 = sidebar chat; inline suggestions deferred to Phase 2 |
| 2026-10-02 | Extension lives in this repo under `vscode-extension/` |
| 2026-10-02 | Panel UI: plain TypeScript + HTML, decoupled through a typed message contract so it can be replaced later |
| 2026-10-02 | Transport: newline-delimited JSON over stdin/stdout |
| 2026-10-02 | `tool_call_start` is emitted before a tool runs (agent change, benefits CLI and panel) |
| 2026-10-02 | Serve mode redirects fd 0 to the null device and fd 1 to stderr at the OS level |
| 2026-10-02 | Extension supports VS Code ≥ 1.90; disabled in untrusted workspaces |
| 2026-10-02 | Test code and test-only dependencies stay outside the repo |
