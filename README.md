<div align="center">

# 🦁 SimhaCLI

### AI-Powered Coding Agent for Your Terminal

[![PyPI version](https://img.shields.io/pypi/v/simhacli.svg)](https://pypi.org/project/simhacli/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

_Built by [Narasimha Naidu Korrapati](https://www.linkedin.com/in/narasimhanaidukorrapati/)_

[Features](#-features) • [Installation](#-installation) • [Configuration](#-configuration) • [Commands](#-commands) • [Tools](#-tools)

</div>

---

## 📖 Overview

**SimhaCLI** is a powerful terminal-based AI coding agent that brings the intelligence of Large Language Models directly into your development workflow. It reads your code, executes tools, manages sessions, and streams its thinking — all inside your terminal.

```
SimhaCLI🦁  starting  refactor my auth module
⠦ 🦁 Simha is working... (2.1s)
💭 SimhaCLI thinking (1.3s) The user wants to refactor the auth module...  ▌
💭 thought for 1.3s

I'll read the existing auth module first and then suggest improvements.
SimhaCLI🦁  complete in 14.2s  8821 tokens (8120 prompt + 701 completion)
```

---

## ✨ Features

### 🤖 Intelligent Agentic Loop

- **Multi-turn reasoning** — autonomously calls tools, reads results, and continues until the task is done
- **Parallel tool execution** — runs multiple tool calls simultaneously with `asyncio.gather`
- **Context compression** — auto-summarises history when the context window fills up
- **Loop detection** — detects and breaks repetitive behaviour automatically
- **Truncation recovery** — handles `finish_reason: length` gracefully, continues or retries
- **Git context awareness** — system prompts include current branch, status, and recent commits

### 📎 File Attachments

- **Attach files to prompts** — use `@attach file.txt` or `@attach path/to/file.py`
- **Multiple file support** — attach multiple files in a single prompt
- **Smart summary** — shows attachment count and total size
- **Auto-inclusion** — file contents are automatically included in the model context

### 💭 Thinking Display

- **Live reasoning** — streaming 💭 display shows what the model is thinking in grey italic text
- **Running timer** — see how long the model has been reasoning
- **Collapsed summary** — freezes as `💭 thought for X.Xs` when reasoning completes (models with extended thinking)

### ⏱️ Performance Visibility

- **Live working spinner** — `⠦ 🦁 Simha is working... (10.1s)` shows elapsed time
- **Total request timer** — complete time shown on every response
- **Token tracking** — `complete in 12.4s  8375 tokens (8119 prompt + 256 completion)`

### 🛠️ 16 Built-in Tools

| Category      | Tools                                                                                 |
| ------------- | ------------------------------------------------------------------------------------- |
| 📖 Read       | `read_file`, `list_dir`, `glob`, `grep`                                               |
| ✏️ Write      | `write_file`, `edit_file`                                                             |
| 🖥️ Shell      | `shell` (40+ blocked dangerous commands)                                              |
| 🌐 Web        | `web_search`, `web_fetch`                                                             |
| 💾 Memory     | `todos` (task management), `memory` (persistent key-value)                            |
| 🤖 Sub-agents | `codebase_investigator`, `code_reviewer`, `test_generator`, `bug_fixer`, `refactorer` |

### 🔌 MCP (Model Context Protocol)

- Connect to any MCP server via stdio or HTTP/SSE transport
- Tools discovered automatically at startup
- Manage connections live with `/mcp`
- Pre-configured examples for GitHub, PostgreSQL, Supabase, and Playwright
- Vercel deployment uses CLI (`npm install -g vercel`) — no MCP needed

### 🚀 Development Workflows

End-to-end automation with a single command or natural language:

| Action         | Description                                                          |
| -------------- | -------------------------------------------------------------------- |
| `fullstack`    | GitHub → Push → Install → Env → Build → README → DB → Deploy → Tests |
| `github`       | Create a GitHub repository                                           |
| `push`         | Commit and push code changes                                         |
| `install_deps` | Auto-detect and install dependencies (npm, yarn, pip, cargo, etc.)   |
| `env_setup`    | Create .env file from template or with custom variables              |
| `build`        | Auto-detect and run build commands                                   |
| `readme`       | Generate README.md for the project                                   |
| `database`     | Set up PostgreSQL or Supabase database                               |
| `deploy`       | Deploy to Vercel                                                     |
| `tests`        | Run Playwright E2E tests                                             |

**Just ask in natural language:**

- "Deploy my app to Vercel"
- "Create a GitHub repo and push my code"
- "Set up the database for my project"
- "Build and deploy my full stack app"

Works with MCP servers when configured, falls back to CLI tools automatically.

### 💾 Session Management

- Save sessions to disk (`/save`) and resume them later (`/resume <id>`)
- Create mid-task checkpoints (`/checkpoint` / `/restore <id>`)
- Undo the last file edit (`/undo`)

### 🔒 Safety & Approval

- Configurable approval policy — from `on_request` to fully autonomous `yolo`
- Shell command allowlist/blocklist
- Environment variable masking (API keys, tokens, secrets never leaked to the model)
- **Tool permissions** — `/permissions` command to manage tool access (allow/deny specific tools)
- **Allowed/denied tools** — configure `allowed_tools` and `denied_tools` in config.toml

### 🚀 Project Initialization

- **`/init` command** — deeply analyzes project structure and generates:
  - `AGENTS.md` — coding conventions and project guidelines for AI agents
  - `SIMHACLI.md` — SimhaCLI-specific project context and instructions
- **Smart detection** — identifies languages, frameworks, and project patterns
- **Context-aware** — future sessions automatically load these instruction files

---

## 🚀 Installation

### Prerequisites

- Python 3.10+
- An API key (OpenRouter, OpenAI, Gemini, or any OpenAI-compatible endpoint)

### Install from PyPI (Recommended)

```bash
pip install simhacli
```

```bash
simhacli                          # interactive mode
simhacli "fix the bug in app.py"  # single prompt
simhacli --help                   # show all options
```

### Install from Source

```bash
git clone https://github.com/naidu199/SimhaCLI.git
cd SimhaCLI
pip install -e .
simhacli
```

---

## ⚙️ Configuration

SimhaCLI looks for configuration in two places (project overrides global):

| Location                          | Purpose               |
| --------------------------------- | --------------------- |
| `~/.simhacli/config.toml`         | Global defaults       |
| `<project>/.simhacli/config.toml` | Per-project overrides |

### Minimal config.toml

```toml
[model]
name = "openrouter/free"
temperature = 1.0

api_key = "your_api_key_here"
api_base_url = "https://openrouter.ai/api/v1"
```

### Environment Variables

```bash
# Windows (PowerShell)
$env:API_KEY = "your_api_key_here"
$env:API_BASE_URL = "https://openrouter.ai/api/v1"

# Linux / macOS
export API_KEY="your_api_key_here"
export API_BASE_URL="https://openrouter.ai/api/v1"
```

### Set credentials interactively

```bash
simhacli
> /credentials
```

### Full config.toml Reference

```toml
[model]
name = "openrouter/free"   # any OpenAI-compatible model
temperature = 1.0

api_key = "sk-..."
api_base_url = "https://openrouter.ai/api/v1"

max_turns = 72                  # max agentic loop turns per request
max_tool_output_tokens = 50000  # truncate large tool outputs
approval = "on_request"         # see Approval Policies below
hooks_enabled = true
developer_instructions = "Always prefer TypeScript over JavaScript."
user_instructions = "Be concise."

# Restrict which tools the agent can use
# allowed_tools = ["read_file", "write_file", "shell"]

[shell_environment]
ignore_default_excludes = false
exclude_patterns = ["*KEY*", "*TOKEN*", "*SECRET*"]

# Add MCP servers
[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]

# HTTP/SSE transport
[mcp_servers.my_remote]
url = "http://localhost:8000/sse"

# Add lifecycle hooks
[[hooks]]
name = "format_on_write"
trigger = "after_tool"
command = "black {file}"
enabled = true
```

### Approval Policies

| Policy         | Behaviour                                           |
| -------------- | --------------------------------------------------- |
| `on_request`   | Ask before shell commands and file writes (default) |
| `always`       | Ask before every tool call                          |
| `auto_approve` | Auto-approve everything                             |
| `auto_edit`    | Auto-approve file edits, ask for shell              |
| `on_failure`   | Only ask if the tool fails                          |
| `yolo`         | Never ask — fully autonomous                        |
| `never`        | Block all tool calls                                |

---

## 💬 Commands

Type any of these during an interactive session:

| Command                     | Description                                                  |
| --------------------------- | ------------------------------------------------------------ |
| `/help`                     | Show all commands                                            |
| `/exit` / `/quit`           | Exit SimhaCLI                                                |
| `/clear`                    | Clear conversation history                                   |
| `/config`                   | Display current configuration                                |
| `/stats`                    | Show session statistics and token usage                      |
| `/tools`                    | List available tools                                         |
| `/mcp`                      | Show MCP server connection status                            |
| `/model <name>`             | Switch model (saves to project config)                       |
| `/approval <policy>`        | Change approval policy                                       |
| `/credentials` / `/creds`   | View or update API key / base URL                            |
| `/permissions`              | Manage tool access permissions (allow/deny/reset)            |
| `/init`                     | Analyze project and generate AGENTS.md and SIMHACLI.md files |
| `/save`                     | Save current session to disk                                 |
| `/sessions`                 | List all saved sessions                                      |
| `/resume <id>`              | Resume a previously saved session                            |
| `/checkpoint`               | Create a checkpoint of the current session                   |
| `/restore <id>`             | Restore a checkpoint                                         |
| `/undo`                     | Undo the last file edit (interactive selective revert)       |
| `/run <command>` / `!<cmd>` | Execute a terminal command directly                          |
| `/workflow <name> [args]`   | Run development workflows (fullstack, github, push, etc.)    |

---

## 🔧 Custom Tools

Drop a Python file into `<project>/.simhacli/tool/` and SimhaCLI picks it up automatically:

```python
from tools.base import Tool, ToolResult
from pydantic import Field

class MyTool(Tool):
    name = "my_tool"
    description = "Does something useful"

    class Arguments(Tool.Arguments):
        message: str = Field(description="Input message")

    async def execute(self, args: Arguments) -> ToolResult:
        return ToolResult.success_result(f"Got: {args.message}")
```

---

## 🖥️ CLI Options

```
simhacli [OPTIONS] [PROMPT]

Options:
  --cwd PATH        Set working directory
  --model TEXT      Override model name
  --approval TEXT   Override approval policy
  --help            Show this message and exit
```

---

## 📝 Changelog

### v1.4.0 (March 20, 2026)

- **Complete Command System Overhaul**: New Command pattern with registry for better extensibility
- **New Commands**:
  - `/undo` – Undo file changes with interactive selective revert menu
  - `/run <command>` / `!<cmd>` – Execute terminal commands directly
  - `/workflow <name> [args]` – Run development workflows (fullstack, github, push, etc.)

- **Live Context Usage Display**: See real-time token count vs context window in TUI
- **Enhanced Context Management**: Actual token counting, pruning at 75%, improved compression at 75% threshold
- **Improved Undo**: Interactive menu for selective file reversion with safety checks
- **Better Model Switching**: `/model` now preserves config file comments and updates system prompt
- **Refactored Architecture**: Cleaner separation with CommandHandler and command registry
- **Enhanced Error Messages**: System prompts include context management feedback

### v1.3.0 (March 18, 2026)

- **Development Workflows**: 10 end-to-end workflow actions (fullstack, github, push, install_deps, env_setup, build, readme, database, deploy, tests)
- **Natural Language Routing**: Agent automatically maps user requests to workflow actions
- **Supabase MCP Support**: Full Supabase integration alongside PostgreSQL
- **Smart Auto-Detection**: Package managers, build commands, and project types detected automatically
- **MCP Setup Guide**: Comprehensive `MCP_SETUP_GUIDE.md` with step-by-step instructions
- **Preserved Config Comments**: Changing model via `/model` no longer strips comments from config.toml
- **Enhanced Error Messages**: All MCP errors now show setup instructions with config snippets
- **Security Improvements**: Placeholder values in configs, .gitignore protection for sensitive data

### v1.2.0 (March 17, 2026)

- **New `/init` Command**: Deeply analyzes projects and generates `AGENTS.md` and `SIMHACLI.md` instruction files for better context-aware coding
- **New `/permissions` Command**: Manage tool access permissions directly from the CLI
- **File Attachment Support**: Attach files to prompts using `@attach file` syntax
- **Git Context Integration**: System prompts now include git context (branch, status) for enhanced understanding
- **Enhanced Error Handling**: Improved error handling and logging throughout the agent
- **Tool Permission Status**: TUI now displays tool permission status (allowed/denied)

### v1.1.0 (January 27, 2026)

- Initial public release on PyPI
- 16 built-in tools for file operations, shell commands, web access, and sub-agents
- MCP (Model Context Protocol) support
- Session management with save/resume/checkpoint/restore
- Configurable approval policies
- Thinking display with live reasoning visualization
- Token tracking and performance metrics

---

## 🔗 Links

- **PyPI**: https://pypi.org/project/simhacli/
- **GitHub**: https://github.com/naidu199/SimhaCLI
- **Developer**: [Narasimha Naidu Korrapati on LinkedIn](https://www.linkedin.com/in/narasimhanaidukorrapati/)
- **MCP Setup Guide**: See `MCP_SETUP_GUIDE.md` for detailed MCP configuration
- **Publishing Guide**: See `PUBLISHING.md` for PyPI deployment instructions

---

<div align="center">

Made with ❤️ by Narasimha Naidu Korrapati

</div>
