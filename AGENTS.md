# AGENTS.md — SimhaCLI Project Guidelines

## Project Description

**SimhaCLI** (v1.4.0) is a Python-based, terminal-native AI coding agent that connects to OpenAI-compatible LLM APIs (OpenRouter, OpenAI, Gemini, etc.). It provides an agentic loop that autonomously reads code, executes tools, manages sessions, and streams thinking — all inside the terminal. Created and maintained by Narasimha Naidu Korrapati.

## Build, Test, Lint, and Run Commands

| Action | Command |
|--------|---------|
| **Install (dev mode)** | `pip install -e .` |
| **Run interactive** | `simhacli` |
| **Run single prompt** | `simhacli "fix the bug in app.py"` |
| **Run as module** | `python -m simhacli` |
| **Show help** | `simhacli --help` |
| **Show version** | `simhacli --version` |
| **Build package** | `python -m build` |
| **Publish to PyPI** | `twine upload dist/*` |
| **Check tool schemas** | `python scripts/check_schemas.py` |
| **Test a tool** | `python scripts/test_tool.py` |

**Note**: No formal test suite or linting configuration exists. Manual testing via `simhacli` is standard.

## Architecture Overview

### Entry Points

- `main.py:main()` — Primary CLI entry point (registered as `simhacli = "main:main"` in `pyproject.toml`)
- `__main__.py` — Allows `python -m simhacli` invocation; delegates to `main.main()`

### Core Components

```
main.py (SimhaCLI class + main() function)
  └── Agent (agent/agent.py)
        └── Session (agent/session.py)
              ├── LLMClient (client/llm_client.py)
              ├── ContextManager (context/manager.py)
              ├── ToolRegistry (tools/registry.py)
              │     ├── Builtin Tools (tools/builtin/*.py) — 11 tools
              │     ├── Subagent Tools (tools/subagent.py) — 5 default subagents
              │     └── MCP Tools (tools/mcp/mcp_tool.py)
              ├── MCPManager (tools/mcp/mcp_manager.py)
              ├── ApprovalManager (safety/approval.py)
              ├── HookSystem (hooks/hook_system.py)
              ├── LoopDetector (context/loop_detector.py)
              └── ChatCompressor (context/compaction.py)

CLI Command System (cli/commands/)
  ├── Command base class (base.py)
  ├── CommandRegistry (registry.py)
  ├── factory.py — create_command_registry()
  └── 20+ command implementations in submodules

UI Layer (ui/tui.py) — Rich-based terminal interface

Configuration (config/)
  ├── config.py — Config Pydantic model
  └── loader.py — load_config(), credential prompts
```

### Data Flow (Agentic Loop)

1. User input → `SimhaCLI._process_message()` (main.py:142)
2. Agent starts agentic loop (`agent/agent.py:_agentic_loop`)
3. For each turn:
   - Build messages from `ContextManager`
   - Call `LLMClient.chat_completion()` with streaming
   - Stream events: `THINKING_DELTA`, `TEXT_DELTA`, `TOOL_CALL_START`
4. When LLM requests tool calls:
   - `ToolRegistry.invoke()` executes tools (can be parallel via `asyncio.gather`)
   - Results wrapped as `ToolResultMessage` added to context
   - Loop continues until no more tool calls
5. Events streamed to TUI (`ui/tui.py`) for real-time display
6. `AgentEvent.AGENT_END` yields final usage stats

### Event System

All communication uses `AgentEvent` dataclass (`agent/events.py`):

- `AGENT_START`, `AGENT_END`, `AGENT_ERROR`
- `TEXT_DELTA`, `TEXT_COMPLETE`
- `THINKING_DELTA`, `THINKING_COMPLETE` (for extended thinking models)
- `TOOL_CALL_START`, `TOOL_CALL_COMPLETE`
- `LOOP_DETECTED`

### Tool System

- **Base class**: `Tool` (`tools/base.py`) — `execute()`, `validate_params()`, `to_openai_schema()`
- **Registry**: `ToolRegistry` (`tools/registry.py`) — manages builtin + MCP + subagent tools
- **Discovery**: `ToolDiscoveryManager` (`tools/discovery.py`) — loads custom tools from `.simhacli/tools/`
- **Kinds**: `READ`, `WRITE`, `SHELL`, `NETWORK`, `MEMORY`, `MCP` (enum `ToolKind`)
- **Invocation**: `ToolInvocation(cwd, params)` passed to `execute()`
- **Result**: `ToolResult(success, output, error, metadata, truncated, diff, exit_code)`

#### Builtin Tools (11 regular + 5 default subagents)

| Tool | File | Kind | Notes |
|------|------|------|-------|
| `read_file` | tools/builtin/read_file.py | READ | Supports offset/limit, checks binary files, max 10MB |
| `write_file` | tools/builtin/write_file.py | WRITE | Creates parent dirs, tracks diffs for `/undo` |
| `edit_file` | tools/builtin/edit_file.py | WRITE | Exact line replacement, returns diffs |
| `shell` | tools/builtin/shell.py | SHELL | 40+ blocked dangerous commands, approval required |
| `list_dir` | tools/builtin/list_dir.py | READ | Shows files vs dirs with `[FILE]`/`[DIR]` prefixes |
| `glob` | tools/builtin/glob.py | READ | Recursive file pattern matching |
| `grep` | tools/builtin/grep.py | READ | Regex search with context lines |
| `web_search` | tools/builtin/web_search.py | NETWORK | DuckDuckGo via `ddgs` library |
| `web_fetch` | tools/builtin/web_fetch.py | NETWORK | Fetches URLs with browser-like headers |
| `todos` | tools/builtin/todo.py | MEMORY | Task management (add/start/complete/list/remove/clear) |
| `memory` | tools/builtin/memory.py | MEMORY | Persistent key-value storage |

**Default subagents** (tools/subagent.py):
- `subagent_codebase_investigator`
- `subagent_code_reviewer`
- `subagent_test_generator`
- `subagent_bug_fixer`
- `subagent_refactorer`

### Configuration System

- **Config model**: `config/config.py` — Pydantic `BaseModel` with all settings
- **Loading**: `config/loader.py:load_config()` loads:
  1. Global: `~/.simhacli/config.toml` (platformdirs)
  2. Project: `<cwd>/.simhacli/config.toml` (overrides global)
  3. `AGENTS.md` in project root → injected as `developer_instructions`
- **Credentials**: API key/base URL stored in TOML or env (`API_KEY`, `API_BASE_URL`)
- **Validation**: `Config.validate()` checks API key existence and CWD validity

#### Important Config Options

```toml
[model]
name = "openrouter/free"      # any OpenAI-compatible model
temperature = 1.0
context_window = 256000
max_turns = 72
max_tool_output_tokens = 50000

approval = "on_request"      # on_request, always, auto_approve, auto_edit, on_failure, yolo, never
hooks_enabled = true
developer_instructions = "..."
user_instructions = "..."

allowed_tools = ["read_file", "write_file", ...]    # if set, only these tools available
denied_tools = ["shell"]                             # tools explicitly blocked

[shell_environment]
ignore_default_excludes = false
exclude_patterns = ["*KEY*", "*TOKEN*", "*SECRET*"]
set_vars = {}

[[hooks]]
name = "format_on_write"
trigger = "after_tool"          # before_tool, after_tool, before_agent, after_agent, on_error
command = "black {file}"        # or script = "..."
time_out_sec = 30.0
enabled = true

[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
# OR http transport:
# url = "http://localhost:8000/sse"
```

### Session Management

- **Session** (`agent/session.py`) — encapsulates LLM client, context manager, tool registry, MCP manager, approval manager, hook system, loop detector, chat compressor
- **StateManager / SessionSnapshot** (`agent/state.py`) — save/resume/checkpoint/restore to disk (JSON in data directory)
- **User memory** — loaded from `user_memory.json` in data directory (`platformdirs.user_data_dir("simhacli")`)

### Approval & Safety

- **ApprovalManager** (`safety/approval.py`) — configurable policies:
  - `on_request` (default): Ask before SHELL/WRITE/NETWORK/MCP
  - `always`: Ask before every tool call
  - `auto_approve`: No asks
  - `auto_edit`: Auto-approve file edits, ask for shell
  - `on_failure`: Only ask if tool fails
  - `yolo`: Fully autonomous (no asks)
  - `never`: Block all tool calls
- **Dangerous patterns** — Shell commands matching regexes (e.g., `rm -rf /`, `dd if=`, `shutdown`, `curl | bash`, fork bombs) auto-flagged as dangerous
- **Tool permissions** — `/permissions` command to manage `allowed_tools`/`denied_tools` in config
- **Secret masking** — Environment variables with `KEY`, `TOKEN`, `SECRET` excluded from shell env

### Lifecycle Hooks

- **HookSystem** (`hooks/hook_system.py`) — triggers before/after agent/tool/error
- **Configuration**: List of `HookConfig` in `config.hooks`
- **Triggers**: `before_tool`, `after_tool`, `before_agent`, `after_agent`, `on_error`
- **Execution**: Runs `command` or `script` as subprocess with timeout (default 30s)
- **Env vars**: `AI_AGENT_TRIGGER`, `AI_AGENT_CWD`, `AI_AGENT_TOOL_NAME`, `AI_AGENT_USER_MESSAGE`, `AI_AGENT_ERROR`

### Context Management

- **ContextManager** (`context/manager.py`) — maintains message history with token tracking
- **Token counting**: Uses `tiktoken` for actual model tokenizers (not approximations)
- **Pruning**: At 75% of context window, `ChatCompressor` summarizes old messages
- **Protection**: `PRUNE_PROTECT_TOKENS = 20000` (last 20k tokens never pruned)
- **Minimum prune threshold**: `PRUNE_MINIMUM_TOKENS = 7500` (only prune if >5k can be saved)
- **Loop detection**: `LoopDetector` tracks actions, breaks on:
  - 3 exact repeats (`max_exact_repeats = 3`)
  - Repeating cycles (`max_cycle_length = 3`)
  - 3 consecutive identical tool failures (`max_consecutive_failures = 3`)

### MCP (Model Context Protocol)

- **Manager**: `tools/mcp/mcp_manager.py` — connects to stdio or HTTP/SSE servers
- **Discovery**: Tools from MCP servers auto-registered as `ToolKind.MCP`
- **Config**: `config.mcp_servers` dictionary with `MCPServerConfig` (command/args or url)
- **Status**: `/mcp` command shows connected servers and their tools
- **Pre-configured examples**: GitHub, PostgreSQL, Supabase, Playwright (see `MCP_SETUP_GUIDE.md`)

### Workflow Automation

- **Workflow engine**: `tools/workflow/engine.py` — step-based orchestration
- **WorkflowTool**: `tools/workflow/workflow_tool.py` — provides `workflow` tool to agent
- **Steps**: Modular `WorkflowStep` classes (`tools/workflow/steps.py`) for: github, database, install_deps, env_setup, build, readme, deploy, tests
- **Fullstack workflow**: End-to-end: GitHub → Push → Install → Env → Build → README → DB → Deploy → Tests
- **Natural language routing**: Agent automatically maps user requests to workflow actions

## Code Conventions and Patterns

### Naming Conventions

- **Classes**: PascalCase — `ToolRegistry`, `ContextManager`, `AgentEvent`, `FileDiff`
- **Functions/methods**: snake_case — `add_user_message()`, `get_system_prompt()`, `invoke()`
- **Constants**: UPPER_SNAKE_CASE — `DEFAULT_API_BASE_URL`, `PRUNE_PROTECT_TOKENS`, `MAX_FILE_SIZE`
- **Files**: snake_case.py — `llm_client.py`, `tool_registry.py`, `loop_detector.py`
- **Directories**: snake_case — `builtin/`, `workflow/`, `cli/commands/`

### Import Order

Standard library → third-party → local imports, separated by blank lines:
```python
import asyncio
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from agent.agent import Agent
from config.config import Config
```

### Error Handling

- **Tool errors**: `ToolResult.error_result(message, output="", **kwargs)`
- **Agent errors**: `AgentEvent.agent_error(message)` — streamed to TUI
- **Config errors**: `utils/errors.py:ConfigError`
- **API retries**: Exponential backoff with 3 retries for `RateLimitError`, `APIError`, `APIConnectionError`
- **Validation**: Pydantic `model_validator` for config constraints (e.g., MCP server transport)

### Async Patterns

- `asyncio.gather` for parallel tool execution when multiple tool calls in one turn
- `async for` streaming for both LLM responses and agent events
- `async with Agent(config) as agent:` context manager pattern for proper cleanup
- `await` on all I/O: subprocess, HTTP, file operations

### Data Models

- **Pydantic BaseModel** for configuration models and tool parameter schemas (`config/config.py`, `tools/builtin/*.py`)
- **@dataclass** for internal structures: `MessageItem`, `ToolResult`, `ToolInvocation`, `FileDiff`, `SessionSnapshot`, `TokenUsage`
- **Enum** for fixed sets: `ApprovalPolicy`, `HookTrigger`, `ToolKind`, `AgentEventType`, `StreamEventType`

### Tool Implementation Pattern

Every builtin tool follows this structure:
```python
from tools.base import Tool, ToolInvocation, ToolResult, ToolKind
from pydantic import BaseModel, Field

class MyToolParams(BaseModel):
    path: str = Field(..., description="File path")
    limit: int | None = Field(None, ge=1, description="Max lines")

class MyTool(Tool):
    name = "my_tool"
    description = "Does something useful"
    kind = ToolKind.READ  # or WRITE, SHELL, NETWORK, MEMORY, MCP
    schema = MyToolParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = MyToolParams(**invocation.params)
        # ... implementation
        return ToolResult.success_result(output="...", metadata={...})
```

### Schema Cleaning for LLM Compatibility

`LLMClient._clean_property()` strips Pydantic artifacts that break small models:
- Removes `title`, `default`
- Resolves `anyOf` (Optional types) to non-null type
- Recursively cleans nested properties and array items
- Also removes `$defs`/`definitions` from top-level schema (`_build_tools()`)

### Git Context Integration

System prompt automatically includes git context if in a git repo (`utils/git.py`):
- Current branch
- Working directory status (modified/untracked files)
- Recent commits (last 5)
- Injected at startup via `get_system_prompt(git_context_str=...)`

## Key Files and Directories

| Path | Description |
|------|-------------|
| `main.py` | CLI entry point, `SimhaCLI` class with command handlers and TUI integration |
| `agent/agent.py` | Core `Agent` class with agentic loop and tool execution logic |
| `agent/session.py` | `Session` — encapsulates all agent state and components |
| `agent/events.py` | `AgentEvent` dataclass and `AgentEventType` enum |
| `agent/state.py` | `StateManager`, `SessionSnapshot` — session persistence |
| `client/llm_client.py` | `LLMClient` — OpenAI API integration with streaming and retries |
| `client/response.py` | Response types: `StreamEvent`, `TokenUsage`, `ToolCall`, `ToolResultMessage` |
| `config/config.py` | `Config` Pydantic model and all config sub-models |
| `config/loader.py` | `load_config()`, `save_config()`, credential prompts |
| `context/manager.py` | `ContextManager` — message history + token tracking |
| `context/compaction.py` | `ChatCompressor` — context summarization when near limit |
| `context/loop_detector.py` | `LoopDetector` — detects repetitive behavior |
| `tools/base.py` | `Tool` abstract base, `ToolResult`, `ToolKind`, `FileDiff` |
| `tools/registry.py` | `ToolRegistry` — registers, filters, invokes tools |
| `tools/discovery.py` | `ToolDiscoveryManager` — loads custom tools from `.simhacli/tools/` |
| `tools/subagent.py` | `SubagentTool` and default subagent definitions |
| `tools/builtin/` | 11 builtin tool implementations (read_file, write_file, etc.) |
| `tools/mcp/` | MCP client (`client.py`), manager (`mcp_manager.py`), tool wrapper (`mcp_tool.py`) |
| `tools/workflow/` | Workflow engine (`engine.py`), steps (`steps.py`), fullstack workflow (`fullstack.py`) |
| `prompts/system.py` | System prompt generation (`get_system_prompt()`, compression prompt, loop breaker) |
| `safety/approval.py` | `ApprovalManager`, `ApprovalDecision`, dangerous pattern detection |
| `hooks/hook_system.py` | `HookSystem` — lifecycle hooks execution |
| `ui/tui.py` | `TUI` class — Rich-based terminal UI with streaming display |
| `utils/errors.py` | `ConfigError` exception |
| `utils/text.py` | Token counting (`count_tokens()`), text truncation (`truncate_text()`) |
| `utils/paths.py` | Path utilities: `resolve_path()`, `is_binary_file()`, `display_path_rel_to_cwd()` |
| `utils/git.py` | Git context extraction (branch, status, commits) |
| `utils/file_attachments.py` | `@attach` file parsing and formatting |
| `cli/` | Command system: `command_handler.py`, `factory.py`, `commands/` (20+ commands) |
| `scripts/` | Debug scripts: `check_schemas.py`, `test_tool.py` |
| `pyproject.toml` | Project metadata, dependencies, setuptools config |
| `README.md` | User-facing documentation |
| `SIMHACLI.md` | Project-specific reference (this file's sibling) |
| `AGENTS.md` | AI agent guidelines (this file) |
| `MCP_SETUP_GUIDE.md` | MCP server setup instructions |
| `PUBLISHING.md` | PyPI publishing guide |

### Command Implementations (`cli/commands/`)

Each command inherits from `Command` base class (`base.py`) and implements `execute(args, context) → CommandResult`.

| Command | File | Purpose |
|---------|------|---------|
| `/help` | system_commands.py | Show all commands |
| `/config` | system_commands.py | Display current configuration |
| `/clear` | system_commands.py | Clear conversation history |
| `/stats` | system_commands.py | Show session stats and token usage |
| `/tools` | system_commands.py | List available tools |
| `/mcp` | system_commands.py | Show MCP server status |
| `/exit`, `/quit` | system_commands.py | Exit SimhaCLI |
| `/version` | system_commands.py | Show version |
| `/model` | model_commands.py | Switch LLM model (saves to project config) |
| `/approval` | model_commands.py | Change approval policy |
| `/credentials` | model_commands.py | View/update API key and base URL |
| `/creds` | model_commands.py | Alias for `/credentials` |
| `/save` | session_commands.py | Save session to disk |
| `/sessions` | session_commands.py | List saved sessions |
| `/resume` | session_commands.py | Resume a session |
| `/checkpoint` | session_commands.py | Create checkpoint of current session |
| `/restore` | session_commands.py | Restore a checkpoint |
| `/permissions` | permissions_commands.py | Manage tool allow/deny lists |
| `/workflow` | workflow_commands.py | Run development workflows |
| `/init` | init_commands.py | Analyze project and generate AGENTS.md/SIMHACLI.md |
| `/undo` | undo_commands.py | Undo last file edit (interactive selective revert) |
| `/run` | run_commands.py | Execute terminal command directly |
| `!<cmd>` | run_commands.py | Alias for `/run` |

## Important Setup Steps and Pitfalls

### No Test Suite

- The project has **no pytest/unittest configuration**. Manual testing via `simhacli` is the norm.
- Use `scripts/check_schemas.py` to validate tool schemas.
- Use `scripts/test_tool.py` to test individual tools.

### Token Counting and Context Management

- Uses **real tokenizers** via `tiktoken` (not character approximations).
- Context window default: `256,000` tokens (OpenRouter/OpenAI large models).
- Pruning triggered at **75%** of context window.
- Last **20,000 tokens** are protected from pruning to preserve recent context.
- Truncation limit: `max_tool_output_tokens` (default 50,000) — tool output exceeding this is truncated with suffix.

### Undo Stack Behavior

- `Agent._undo_stack` tracks file diffs as `(path, old_content, new_content)` tuples.
- Undo stack is **cleared on each new user message** (`main.py:122`), so `/undo` only reverts the most recent interaction.
- Powered by `FileDiff` (`tools/base.py`) — uses `difflib.unified_diff`.

### Approval Policies and Mutating Tools

- **Mutating tool kinds**: `WRITE`, `SHELL`, `NETWORK`, `MCP` require approval (unless policy waives).
- `ApprovalManager` checks `is_mutating()` on tools and consults policy.
- Shell commands matching dangerous patterns auto-flagged as `is_dangerous=True`.

### Windows Compatibility

- File permissions: `os.chmod` skipped on Windows (`sys.platform == "win32"`).
- Shell info: Reports `PowerShell/cmd.exe` (detected via `SHELL`/`COMSPEC` env or default).
- Path handling: Uses `pathlib.Path` exclusively — works cross-platform.
- Signal handling: `signal.SIGKILL` only used on non-Windows; `process.kill()` on Windows.

### MCP Server Requirements

- Pre-configured MCP servers need Node.js (`npx`) or Python environments.
- See `MCP_SETUP_GUIDE.md` for step-by-step setup of GitHub, PostgreSQL, Supabase, Playwright.
- MCP tools appear as `ToolKind.MCP` in registry.

### File Attachment Syntax

- Attach files: `@attach path/to/file.py` or multiple: `@attach file1.txt @attach file2.md`
- Parsed by `utils/file_attachments.py:parse_attachments()`
- Files are **read and injected** into the message content before sending to LLM.
- Attachments shown in TUI with count and total size.

### Custom Tool Development

Place `.py` files in `<project>/.simhacli/tools/`:
```python
from tools.base import Tool, ToolResult, ToolInvocation, ToolKind
from pydantic import BaseModel, Field

class MyParams(BaseModel):
    message: str = Field(description="Input message")

class MyTool(Tool):
    name = "my_tool"
    description = "Does something useful"
    kind = ToolKind.READ
    schema = MyParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        return ToolResult.success_result(f"Got: {invocation.params['message']}")
```

Tools are auto-discovered at session start via `ToolDiscoveryManager`.

### Configuration File Locations

- **Global**: `~/.simhacli/config.toml` (platformdirs: `~/.config/simhacli` on Linux, `%APPDATA%\simhacli` on Windows)
- **Project**: `<cwd>/.simhacli/config.toml` — overrides global
- **Priority**: CLI options > project config > global config > environment variables > defaults

### Schema Writing Tips

- Tool parameter schemas should use **Pydantic BaseModel** with `Field(description=...)`
- Avoid complex nested models with `$ref` — `Tool._resolve_refs()` inlines them.
- `title` and `default` are auto-stripped by `LLMClient._clean_property()`.

## System Prompt Identity (for reference)

The agent's system prompt is built by `prompts/system.py:get_system_prompt()` and includes:

- Identity section (creator, capabilities, pairing philosophy)
- Environment (date/time, OS, CWD, shell)
- Git context (if available)
- Tool guidelines (available tools, usage patterns)
- Workflow capabilities
- AGENTS.md spec reminder
- Security guidelines (approval, dangerous patterns, secret masking)
- Optional developer_instructions and user_instructions from config
- User memory (if any)
- Operational guidelines (loop detection, context compression, truncation recovery)

**Important**: When asked about creators, always state:
- SimhaCLI framework created by Narasimha Naidu Korrapati
- Underlying language model as shown in config (e.g., `stepfun/step-3.5-flash:free` or `openrouter/free`)

---

*Last updated: Based on SimhaCLI v1.4.0 codebase (March 20, 2026)*
