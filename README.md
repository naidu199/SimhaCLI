# SimhaCLI 🦁 - AI Coding Agent

## Project Flows

### 1. **Application Startup Flow**

```
main.py
  ↓
Load Config (config/loader.py)
  ↓
Validate Config (API keys, CWD)
  ↓
Initialize SimhaCLI
  ↓
Run Mode Selection:
  ├─→ Single Message Mode (--prompt)
  └─→ Interactive Mode (REPL)
```

### 2. **Configuration Loading Flow**

```
config/loader.py
  ↓
Load System Config (~/.simhacli/config.toml)
  ↓
Load Project Config (CWD/.simhacli/config.toml)
  ↓
Merge Configurations
  ↓
Load AGENT.MD (if exists)
  ↓
Return Config Object (config/config.py)
```

### 3. **Agent Execution Flow**

```
User Input
  ↓
Agent.run() (agent/agent.py)
  ↓
Add User Message to Context
  ↓
Agentic Loop:
  ├─→ LLM Chat Completion
  ├─→ Stream Text Response
  ├─→ Process Tool Calls (if any)
  ├─→ Execute Tools
  ├─→ Add Tool Results to Context
  └─→ Repeat until completion
  ↓
Return Final Response
```

### 4. **LLM Client Flow**

```
client/llm_client.py
  ↓
Get OpenAI Client
  ↓
Build Request (messages + tools)
  ↓
Chat Completion with Retry Logic:
  ├─→ Rate Limit Handling
  ├─→ Connection Error Retry
  └─→ Exponential Backoff
  ↓
Stream Events:
  ├─→ TEXT_DELTA (streaming text)
  ├─→ TOOL_CALL_DELTA (tool invocation)
  ├─→ TOOL_CALL_COMPLETE
  └─→ MESSAGE_COMPLETE
```

### 5. **Context Management Flow**

```
context/manager.py
  ↓
Initialize with System Prompt
  ↓
Message Operations:
  ├─→ Add User Message
  ├─→ Add Assistant Message (with tool_calls)
  └─→ Add Tool Result
  ↓
Track Token Counts per Message
  ↓
Build Messages Array for LLM
```

### 6. **Tool Registry & Execution Flow**

```
tools/registry.py
  ↓
Create Default Registry
  ↓
Register Builtin Tools
  ↓
Tool Invocation:
  ├─→ Get Tool by Name
  ├─→ Validate Parameters
  ├─→ Create Tool Invocation
  ├─→ Execute Tool
  └─→ Return Tool Result
```

### 7. **Tool Execution Flow**

```
tools/base.py
  ↓
Tool Interface (Abstract)
  ├─→ name
  ├─→ description
  ├─→ schema (Pydantic)
  ├─→ kind (READ/WRITE/SHELL/NETWORK/MEMORY/MCP)
  └─→ execute()
  ↓
Builtin Tool Example (tools/builtin/read_file.py):
  ├─→ Validate Parameters
  ├─→ Resolve File Path
  ├─→ Check File Existence
  ├─→ Read File Content
  ├─→ Format with Line Numbers
  ├─→ Truncate if needed
  └─→ Return ToolResult
```

### 8. **Event System Flow**

```
agent/events.py
  ↓
Event Types:
  ├─→ AGENT_START
  ├─→ AGENT_END
  ├─→ AGENT_ERROR
  ├─→ TEXT_DELTA
  ├─→ TEXT_COMPLETE
  ├─→ TOOL_CALL_START
  ├─→ TOOL_CALL_COMPLETE
  └─→ TOOL_CALL_ERROR
  ↓
Agent Yields Events
  ↓
SimhaCLI Handles Events
  ↓
TUI Displays Events
```

### 9. **TUI (Terminal UI) Flow**

```
ui/tui.py
  ↓
Initialize Rich Console with Theme
  ↓
Display Operations:
  ├─→ Print Welcome Banner
  ├─→ Stream Assistant Delta (live text)
  ├─→ Display Tool Call Start
  ├─→ Display Tool Call Complete
  ├─→ Display Errors
  └─→ Format Code/Markdown
  ↓
Input Operations:
  └─→ Read User Input (REPL)
```

### 10. **Interactive Mode Flow**

```
Interactive Loop (main.py)
  ↓
Display Welcome Message
  ↓
Initialize Agent
  ↓
Loop:
  ├─→ Read User Input
  ├─→ Handle Commands (/exit, /quit, /help)
  ├─→ Process Message through Agent
  ├─→ Stream Events to TUI
  └─→ Repeat
```

### 11. **Response Streaming Flow**

```
client/response.py
  ↓
Stream Event Types:
  ├─→ TEXT_DELTA (partial text)
  ├─→ TOOL_CALL_DELTA (partial tool args)
  ├─→ TOOL_CALL_COMPLETE (full tool call)
  └─→ MESSAGE_COMPLETE (with usage)
  ↓
Parse Tool Arguments (JSON)
  ↓
Create Tool Result Messages
```

### 12. **System Prompt Generation Flow**

```
prompts/system.py
  ↓
Build System Prompt Sections:
  ├─→ Identity (SimhaCLI agent role)
  ├─→ AGENTS.md Specification
  ├─→ Security Guidelines
  ├─→ Developer Instructions (if configured)
  ├─→ User Instructions (if configured)
  └─→ Operational Guidelines
  ↓
Return Complete System Prompt
```

### 13. **Utility Functions Flow**

```
utils/
  ├─→ paths.py
  │   ├─→ Resolve Paths (absolute/relative)
  │   ├─→ Display Relative Paths
  │   └─→ Detect Binary Files
  │
  ├─→ text.py
  │   ├─→ Count Tokens (tiktoken)
  │   ├─→ Estimate Tokens
  │   └─→ Truncate Text
  │
  └─→ errors.py
      ├─→ AgentError (base)
      └─→ ConfigError (config-specific)
```

### 14. **Error Handling Flow**

```
Errors Propagate:
  ↓
Tool Execution Error
  ├─→ Return ToolResult.error_result()
  ↓
LLM API Error
  ├─→ Retry with Exponential Backoff
  ├─→ Yield StreamEvent.ERROR
  ↓
Agent Error
  ├─→ Yield AgentEvent.agent_error()
  ↓
SimhaCLI Catches Error
  ↓
TUI Displays Error to User
```

## Architecture Summary

**Entry Point:** `main.py` → CLI interface with Click
**Core Agent:** `agent/agent.py` → Orchestrates LLM + Tools
**LLM Client:** `client/llm_client.py` → OpenAI API integration
**Context:** `context/manager.py` → Message history management
**Tools:** `tools/` → Extensible tool system (read_file, etc.)
**UI:** `ui/tui.py` → Rich terminal interface
**Config:** `config/` → TOML-based configuration
**Events:** `agent/events.py` → Event-driven architecture
**Prompts:** `prompts/system.py` → System prompt generation
**Utils:** `utils/` → Helper functions (paths, text, errors)

## Data Flow Summary

```
User → CLI → Agent → Context + LLM Client → OpenAI API
                ↓                              ↓
            Tool Registry ← Stream Events ← Response
                ↓                              ↓
            Execute Tool                    Parse Events
                ↓                              ↓
            Tool Result → Add to Context → Continue Loop
                                              ↓
                                         TUI Display
```
