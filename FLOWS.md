# SimhaCLI Flow Diagrams 🦁

Visual representation of how SimhaCLI processes user requests, executes tools, and manages the complete agent lifecycle.

**Last Updated:** January 14, 2026

---

## 🚀 New Architecture Highlights

**Session-Based Design:**

- Agent now uses **Session** object to manage state
- Session encapsulates: LLM Client, Context Manager, Tool Registry
- Persistent user memory loaded from `user_memory.json`
- Turn counting and session tracking (UUID + timestamps)

**11 Builtin Tools:**

1. `read_file` - Read file contents with line numbers
2. `write_file` - Create/overwrite files
3. `edit_file` - Surgical text replacement
4. `shell` - Execute shell commands (with safety blocking)
5. `list_dir` - Directory listing
6. `glob` - Pattern-based file search
7. `grep` - Text search in files
8. `web_search` - Search the web
9. `web_fetch` - Fetch webpage content
10. `todos` - Task management with priorities
11. `memory` - Persistent key-value storage

---

## 1. Complete User Question Flow (End-to-End)

```
                      ┌─────────────────────────┐
                      │  User Enters Question   │
                      └───────────┬─────────────┘
                                  │
                                  ▼
                          ┌───────────────┐
                          │  Mode Check?  │
                          └───┬───────┬───┘
                              │       │
                   ┌──────────┘       └──────────┐
                   │                             │
                   ▼                             ▼
         ┌──────────────────┐        ┌──────────────────────┐
         │  Single Message  │        │  Interactive Mode    │
         │      Mode        │        │      (REPL)          │
         └────────┬─────────┘        └──────────┬───────────┘
                  │                             │
                  └──────────┬──────────────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │   Load Config        │
                  │  (System + Project)  │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │  Create Agent with   │
                  │     Session          │
                  └──────────┬───────────┘
                             │
                ┌────────────┼────────────┐
                │            │            │
                ▼            ▼            ▼
    ┌─────────────────┐  ┌──────────┐  ┌──────────────┐
    │ Context Manager │  │   LLM    │  │     Tool     │
    │  (+ Memory)     │  │  Client  │  │   Registry   │
    │                 │  │          │  │  (11 tools)  │
    └────────┬────────┘  └────┬─────┘  └──────┬───────┘
             │                │               │
             └────────────────┼───────────────┘
                              │
                    ALL INSIDE SESSION
                              │
                              ▼
                   ┌────────────────────────┐
                   │  Add User Message to   │
                   │       Context          │
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │   Get System Prompt    │
                   │  (+ Tools + Memory)    │
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │  Build Messages Array  │
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │   Send to OpenAI API   │◄─────────┐
                   └───────────┬────────────┘          │
                               │                       │
                               ▼                       │
                   ┌────────────────────────┐          │
                   │   Stream Response      │          │
                   │  (Increment Turn)      │          │
                   └───────────┬────────────┘          │
                               │                       │
            ┌──────────────────┼──────────────────┐    │
            │                  │                  │    │
            ▼                  ▼                  ▼    │
    ┌───────────────┐  ┌──────────────┐  ┌────────────────┐
    │  TEXT_DELTA   │  │  TOOL_CALL   │  │   MESSAGE_     │
    │     Event     │  │    Event     │  │   COMPLETE     │
    └───────┬───────┘  └──────┬───────┘  └────────┬───────┘
            │                  │                   │
            ▼                  ▼                   │
    ┌───────────────┐  ┌──────────────┐           │
    │  TUI Display  │  │ Execute Tool │           │
    │     Text      │  │  in Registry │           │
    └───────┬───────┘  └──────┬───────┘           │
            │                  │                   │
            │                  ▼                   │
            │          ┌──────────────┐            │
            │          │ Tool Result  │            │
            │          └──────┬───────┘            │
            │                 │                    │
            │                 ▼                    │
            │          ┌──────────────┐            │
            │          │ Add Result   │            │
            │          │ to Context   │            │
            │          └──────┬───────┘            │
            │                 │                    │
            │                 └────────────────────┘
            │
            ▼
    ┌───────────────────┐
    │ Continue Stream   │
    └───────────────────┘

            After MESSAGE_COMPLETE:
                   │
                   ▼
        ┌──────────────────────┐
        │  No Tool Calls?      │
        │  → Agent End         │
        │  Has Tool Calls?     │
        │  → Continue Loop     │
        └──────────┬───────────┘
                   │
                   ▼
            ┌──────────────┐
            │ Interactive? │
            └──┬────────┬──┘
               │        │
        Yes ◄──┘        └──► No
         │                  │
         ▼                  ▼
┌──────────────────┐  ┌─────────┐
│ Wait for Next    │  │  Exit   │
│    Question      │  │ Program │
└────────┬─────────┘  └─────────┘
         │
         └──────► (Loop back to top)
```

---

## 2. Tool Execution Flow

```

         ┌──────────────────────────┐
         │ LLM Requests Tool Call   │
         └────────────┬─────────────┘
                      │
                      ▼
         ┌──────────────────────────┐
         │ Parse Tool Name &        │
         │      Arguments           │
         └────────────┬─────────────┘
                      │
                      ▼
              ┌───────────────┐
              │ Tool Exists?  │
              └───┬───────┬───┘
                  │       │
            No ◄──┘       └──► Yes
             │                 │
             ▼                 ▼
    ┌─────────────────┐  ┌──────────────────┐
    │ Return Error:   │  │ Get Tool         │
    │  Unknown Tool   │  │   Instance       │
    └────────┬────────┘  └────────┬─────────┘
             │                    │
             │                    ▼
             │           ┌──────────────────┐
             │           │    Validate      │
             │           │   Parameters     │
             │           └────────┬─────────┘
             │                    │
             │                    ▼
             │            ┌───────────────┐
             │            │ Parameters    │
             │            │   Valid?      │
             │            └───┬───────┬───┘
             │                │       │
             │          No ◄──┘       └──► Yes
             │           │                 │
             │           ▼                 ▼
             │  ┌─────────────────┐  ┌──────────────────┐
             │  │ Return          │  │  Create Tool     │
             │  │ Validation      │  │  Invocation      │
             │  │    Error        │  └────────┬─────────┘
             │  └────────┬────────┘           │
             │           │                    ▼
             │           │           ┌─────────────────┐
             │           │           │   Tool Kind?    │
             │           │           └────┬───┬───┬───┬┘
             │           │                │   │   │   │
             │           │     ┌──────────┘   │   │   └──────────┐
             │           │     │              │   │              │
             │           │     ▼              ▼   ▼              ▼
             │           │  ┌──────┐     ┌───────────┐      ┌─────────┐
             │           │  │ READ │     │ WRITE     │      │ SHELL   │
             │           │  └──┬───┘     └─────┬─────┘      └────┬────┘
             │           │     │               │                 │
             │           │     └───────┬───────┘                 │
             │           │             │                         │
             │           │             ▼                         │
             │           │    ┌──────────────────┐              │
             │           │    │ Resolve File     │              │
             │           │    │      Path        │              │
             │           │    └────────┬─────────┘              │
             │           │             │                        │
             │           │             ▼                        │
             │           │    ┌──────────────────┐              │
             │           │    │ Check File       │              │
             │           │    │    Exists?       │              │
             │           │    └────┬────────┬────┘              │
             │           │         │        │                   │
             │           │    No ◄─┘        └─► Yes             │
             │           │      │               │               │
             │           │      ▼               │               │
             │           │ ┌────────────┐       │               │
             │           │ │ Return     │       │               │
             │           │ │  Error     │       │               │
             │           │ └─────┬──────┘       │               │
             │           │       │              │               │
             └───────────┼───────┼──────────────┘               │
                         │       │                              │
                         │       └──────────────┬───────────────┘
                         │                      │
                         │                      ▼
                         │           ┌─────────────────────┐
                         │           │   Execute Tool      │
                         │           │      Logic          │
                         │           └──────────┬──────────┘
                         │                      │
                         │                      ▼
                         │              ┌───────────────┐
                         │              │   Success?    │
                         │              └───┬───────┬───┘
                         │                  │       │
                         │            Yes ◄─┘       └─► No
                         │              │               │
                         │              ▼               ▼
                         │    ┌──────────────────┐  ┌──────────────────┐
                         │    │ Create Success   │  │  Create Error    │
                         │    │     Result       │  │     Result       │
                         │    └────────┬─────────┘  └────────┬─────────┘
                         │             │                     │
                         └─────────────┼─────────────────────┘
                                       │
                                       ▼
                            ┌────────────────────┐
                            │  Return Tool       │
                            │     Result         │
                            └──────────┬─────────┘
                                       │
                                       ▼
                            ┌────────────────────┐
                            │  Add to Context    │
                            │  as Tool Message   │
                            └──────────┬─────────┘
                                       │
                                       ▼
                            ┌────────────────────┐
                            │  Continue Agent    │
                            │       Loop         │
                            └────────────────────┘
```

---

## 3. Agent Agentic Loop Flow

```
                    ┌─────────────────────┐
                    │  Agent.run Called   │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Emit AGENT_START    │
                    │      Event          │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  Add User Message   │
                    │    to Context       │
                    └──────────┬──────────┘
                               │
        ┌──────────────────────┴──────────────────────┐
        │                                             │
        ▼                                             │
┌────────────────────┐                                │
│  Enter Agentic     │                                │
│       Loop         │◄───────────────────────────────┤
└─────────┬──────────┘                                │
          │                                           │
          ▼                                           │
┌────────────────────┐                                │
│ Get Context        │                                │
│    Messages        │                                │
└─────────┬──────────┘                                │
          │                                           │
          ▼                                           │
┌────────────────────┐                                │
│ Get Tool Schemas   │                                │
└─────────┬──────────┘                                │
          │                                           │
          ▼                                           │
┌────────────────────┐                                │
│  Call LLM Chat     │                                │
│   Completion       │                                │
└─────────┬──────────┘                                │
          │                                           │
          ▼                                           │
┌────────────────────┐                                │
│ Stream Processing  │                                │
└─────────┬──────────┘                                │
          │                                           │
          ▼                                           │
    ┌──────────┐                                      │
    │  Event   │                                      │
    │  Type?   │                                      │
    └─┬──┬──┬──┘                                      │
      │  │  │                                         │
  ────┘  │  └────                                     │
  │      │      │                                     │
  ▼      ▼      ▼                                     │
┌────┐ ┌────┐ ┌────────┐                             │
│TEXT│ │TOOL│ │MESSAGE │                             │
│DELTA│ │CALL│ │COMPLETE│                             │
└─┬──┘ └─┬──┘ └───┬────┘                             │
  │      │        │                                   │
  ▼      ▼        ▼                                   │
┌─────┐ ┌────┐ ┌──────────────┐                      │
│Acc  │ │Add │ │ Processing   │                      │
│Text │ │Tool│ │  Complete    │                      │
└──┬──┘ │Call│ └──────┬───────┘                      │
   │    └─┬──┘        │                              │
   ▼      │           ▼                              │
┌──────┐  │  ┌──────────────────┐                    │
│Emit  │  │  │ Emit TEXT_       │                    │
│DELTA │  │  │   COMPLETE       │                    │
└──┬───┘  │  └────────┬─────────┘                    │
   │      │           │                              │
   │      │           ▼                              │
   │      │  ┌──────────────────┐                    │
   │      │  │ Add Assistant    │                    │
   │      │  │  Message to      │                    │
   │      │  │   Context        │                    │
   │      │  └────────┬─────────┘                    │
   │      │           │                              │
   │      │           ▼                              │
   │      │    ┌──────────────┐                      │
   │      │    │ Has Tool     │                      │
   │      │    │   Calls?     │                      │
   │      │    └───┬──────┬───┘                      │
   │      │        │      │                          │
   │      │   No ◄─┘      └─► Yes                    │
   │      │     │             │                      │
   │      │     ▼             ▼                      │
   │      │ ┌───────┐  ┌──────────────┐             │
   │      │ │ Emit  │  │   Process    │             │
   │      │ │AGENT_ │  │   Each Tool  │             │
   │      │ │ END   │  │     Call     │             │
   │      │ └───┬───┘  └──────┬───────┘             │
   │      │     │             │                      │
   │      │     │             ▼                      │
   │      │     │     ┌──────────────┐               │
   │      │     │     │ Parse Tool   │               │
   │      │     │     │  Arguments   │               │
   │      │     │     └──────┬───────┘               │
   │      │     │            │                       │
   │      │     │            ▼                       │
   │      │     │     ┌──────────────┐               │
   │      │     │     │  Emit TOOL_  │               │
   │      │     │     │ CALL_START   │               │
   │      │     │     └──────┬───────┘               │
   │      │     │            │                       │
   │      │     │            ▼                       │
   │      │     │     ┌──────────────┐               │
   │      │     │     │ Execute Tool │               │
   │      │     │     │ via Registry │               │
   │      │     │     └──────┬───────┘               │
   │      │     │            │                       │
   │      │     │            ▼                       │
   │      │     │     ┌──────────────┐               │
   │      │     │     │ Get Tool     │               │
   │      │     │     │   Result     │               │
   │      │     │     └──────┬───────┘               │
   │      │     │            │                       │
   │      │     │            ▼                       │
   │      │     │     ┌──────────────┐               │
   │      │     │     │  Emit TOOL_  │               │
   │      │     │     │CALL_COMPLETE │               │
   │      │     │     └──────┬───────┘               │
   │      │     │            │                       │
   │      │     │            ▼                       │
   │      │     │     ┌──────────────┐               │
   │      │     │     │ Add Tool     │               │
   │      │     │     │  Result to   │               │
   │      │     │     │   Context    │               │
   │      │     │     └──────┬───────┘               │
   │      │     │            │                       │
   │      │     │            ▼                       │
   │      │     │     ┌──────────────┐               │
   │      │     │     │ More Tools?  │               │
   │      │     │     └───┬──────┬───┘               │
   │      │     │         │      │                   │
   │      │     │    Yes ◄┘      └─► No              │
   │      │     │      │             │               │
   │      │     │      └─────────────┼───────────────┘
   │      │     │                    │
   │      └─────┼────────────────────┘
   │            │
   └────────────┘

   All paths eventually lead to:
                ▼
      ┌────────────────────┐
      │  Return Final      │
      │    Response        │
      └────────────────────┘
```

---

## 4. LLM Client Communication Flow (Simplified)

```
    [User Question] → [Get OpenAI Client] → [Build Request]
            ↓                                      ↓
    [Add Messages + Model + Tools] → [Attempt API Call]
            ↓                                      ↓
            ├──────────[Success]──────────────────►│
            │                                      │
            └──[Error: Rate/Connection]◄───────┐   │
                    ↓                          │   │
            [Retries Left?]                    │   │
               Yes ↓     No ↓                  │   │
          [Wait 2^N] [Emit Error]              │   │
                ↓         ↓                    │   │
                └─────────┴────────────────────┘   │
                                                   ▼
                                         [Process Response]
                                                   ↓
                                           [Stream Mode?]
                                          Yes ↓     No ↓
                                    [Process    [Process
                                     Stream]     Normal]
                                        ↓            ↓
                               [Iterate Chunks]     │
                                   ↓    ↓    ↓      │
                              [Text] [Tool] [Usage] │
                                ↓      ↓      ↓     │
                              [Emit Events] ────────┘
                                        ↓
                               [Return to Agent]
```

---

## 5. Context Management Flow (Simplified)

```
    [Context Manager Init] → [Load System Prompt] → [Empty Messages List]
                ↓
        ┌───────────────┐
        │  Operation?   │◄──────────────────────┐
        └──┬──┬───┬──┬──┘                       │
           │  │   │  │                          │
     ┌─────┘  │   │  └────────┐                 │
     │        │   │           │                 │
     ▼        ▼   ▼           ▼                 │
  [Add     [Add  [Add     [Get                  │
   User]   Asst] Tool]   Messages]              │
     │        │   │           │                 │
     └────────┼───┘           │                 │
              ▼               ▼                 │
        [Count Tokens]   [Prepend System        │
              ↓            Prompt]              │
        [Store in              ↓                │
         Messages]        [Convert to Dicts]    │
              │                ↓                │
              └──────►   [Add tool_calls        │
                         if present]            │
                              ↓                 │
                         [Return Array]         │
                              │                 │
                              └─────────────────┘
```

---

## 6. Configuration Loading Flow (Simplified)

```
    [Load Config Called] → [Determine CWD]
              ↓
    [Get System Config: ~/.simhacli/config.toml]
              ↓
        [Exists?] ──Yes──► [Parse System TOML]
              │                      ↓
              No                     │
              ↓                      │
        [Use Defaults] ──────────────┘
              ↓
    [Get Project Config: .simhacli/config.toml]
              ↓
        [Exists?] ──Yes──► [Parse Project TOML]
              │                      ↓
              No           [Merge Configs]
              ↓                      │
              └──────────────────────┘
                        ↓
              [Check for AGENT.MD]
                        ↓
                  [Exists?] ──Yes──► [Read Content]
                        │                  ↓
                        No          [Add to Config]
                        ↓                  │
                        └──────────────────┘
                                 ↓
                        [Create Config Object]
                                 ↓
                          [Validate Config]
                         Valid ↓   Invalid ↓
                      [Return]  [Throw Error]
```

---

## 7. TUI Event Display Flow (Simplified)

```
    [Event Received]
            │
            ▼
      ┌──────────┐
      │  Type?   │
      └───┬──────┘
          │
    ┌─────┼─────┬─────┬─────┬─────┬──────┐
    │     │     │     │     │     │      │
    ▼     ▼     ▼     ▼     ▼     ▼      ▼
[AGENT [TEXT [TEXT [TOOL [TOOL [AGENT [ERROR]
START] DELTA]COMP]START] COMP]  END]
    │     │     │     │     │     │      │
    ▼     ▼     ▼     ▼     ▼     ▼      ▼
[Banner][Stream][New [Format][Result][Summary][Error
       [Text] Line]  Tool]  Based       Panel]
                      Info] on Kind
                            & Success]
                                │
                                ▼
                        [Syntax Highlight
                         if Code Present]
                                │
                                ▼
                        [Display to User]
```

---

## 8. Error Handling Flow (Simplified)

```
        [Error Occurs]
              │
              ▼
        ┌──────────┐
        │ Source?  │
        └────┬─────┘
             │
    ┌────────┼────────┬───────────┐
    │        │        │           │
    ▼        ▼        ▼           ▼
[Tool]   [LLM API] [Config]  [Agent]
  Error    Error    Error     Error
    │        │        │           │
    ▼        │        ▼           ▼
[ToolResult  │   [ConfigError] [AgentEvent
 .error]     │        │         .error]
    │        │        ▼           │
    │        │   [Display &       │
    │        │    Exit(1)]        │
    │        │                    │
    │        ▼                    │
    │   [Rate/Connection?]        │
    │     Yes ↓    No ↓           │
    │   [Retry]  [StreamEvent     │
    │   with     .ERROR]          │
    │   Backoff]      │           │
    │        │        │           │
    │   [Retries      │           │
    │   Exhausted?]   │           │
    │   Yes ↓  No ↓   │           │
    │   [Error] [Retry]           │
    │        │    │               │
    └────────┴────┴───────────────┘
                  │
                  ▼
        [TUI Displays Error]
                  │
                  ▼
        [User Sees Message]
```

---

## 9. Interactive Mode Loop Flow (Simplified)

```
    [Start Interactive Mode]
              ↓
    [Display Welcome Banner]
              ↓
    [Initialize Agent Context]
              ↓
    ┌─────────────────────────┐
    │  ◄── MAIN LOOP ──►      │◄──────┐
    │                         │       │
    │ [Display Prompt: user>] │       │
    │          ↓              │       │
    │    [Read Input]         │       │
    │          ↓              │       │
    │    ┌──────────┐         │       │
    │    │ Input?   │         │       │
    │    └───┬──────┘         │       │
    │        │                │       │
    │   ┌────┼────┬───────┐   │       │
    │   │    │    │       │   │       │
    │   ▼    ▼    ▼       ▼   │       │
    │ [Empty][Cmd][Message]   │       │
    │   │    │     │           │       │
    │  Skip  │     ▼           │       │
    │        │  [Process       │       │
    │        │   Message]      │       │
    │        │     ↓           │       │
    │        │  [Run Agent]    │       │
    │        │     ↓           │       │
    │        │  [Stream        │       │
    │        │   Events]       │       │
    │        │     ↓           │       │
    │        │  [Display]──────┼───────┘
    │        │                 │
    │        ▼                 │
    │   ┌────────┐             │
    │   │Command?│             │
    │   └────┬───┘             │
    │        │                 │
    │   ┌────┼────┬────┐       │
    │   │    │    │    │       │
    │   ▼    ▼    ▼    ▼       │
    │ [/exit][/help][/config]  │
    │   │    │       │         │
    │  BREAK └───────┼─────────┘
    │                │
    └────────────────┘
             │
             ▼
    [Display Goodbye]
             ↓
      [Close Agent]
             ↓
      [Exit Program]
```

---

## 10. Tool Registry Initialization Flow (Simplified)

```
    [Create Default Registry]
              ↓
    [Initialize Empty Registry]
              ↓
    [Get All Builtin Tools]
              ↓
    ┌─────────────────────────┐
    │  For Each Tool Class    │
    │          ↓              │
    │   [Instantiate Tool]    │
    │          ↓              │
    │   [Register in Dict]    │
    │          ↓              │
    │     [More Tools?]       │
    │    Yes ↓    No ↓        │
    │   (Loop)   Exit         │
    └─────────────┬───────────┘
                  ↓
          [Registry Ready]
                  ↓
        [Return to Agent]
                  ↓
        ┌─────────────────┐
        │ Tool Invocation │
        │     Request     │
        └────────┬────────┘
                 ▼
          [Get Tool by Name]
                 ↓
            [Exists?] ──No──► [Unknown Tool Error]
         Yes ↓                       ↓
    [Validate Parameters]            │
         Valid ↓  Invalid ↓           │
    [Create     [Validation          │
     Invocation] Error]              │
         ↓           ↓               │
    [Execute]        │               │
         ↓           │               │
    [ToolResult] ◄───┴───────────────┘
         ↓
    [Return to Agent]
```

---

## 11. Single Message Mode Flow (Simplified)

```
    [CLI: simhacli "question"]
              ↓
      [Parse Arguments]
              ↓
      [Load Configuration]
              ↓
      [Validate Config]
        Valid ↓  Invalid ↓
              │   [Display Errors]
              │          ↓
              │      [Exit(1)]
              ▼
    [Create SimhaCLI Instance]
              ↓
      [Run Single Mode]
              ↓
    [Create Agent Context]
              ↓
    [Add User Message]
              ↓
      [Run Agent Loop]
              ↓
    [Process Events]
              │
       ┌──────┼──────┐
       │      │      │
       ▼      ▼      ▼
    [TEXT] [TOOL] [AGENT_END]
    [Print] [Exec]     ↓
       │      │    [Complete]
       └──────┴────────┘
              ↓
        [Close Agent]
              ↓
      [Return Result]
              ↓
          [Exit(0)]
```

---

## Legend

### Event Types

- 🟢 **AGENT_START**: Agent begins processing
- 🔵 **TEXT_DELTA**: Streaming text chunk
- 🟡 **TEXT_COMPLETE**: Full response received
- 🟠 **TOOL_CALL_START**: Tool execution begins
- 🟣 **TOOL_CALL_COMPLETE**: Tool execution ends
- 🟢 **AGENT_END**: Agent completes successfully
- 🔴 **AGENT_ERROR**: Error occurred

### Tool Kinds (11 Builtin Tools - Updated!)

- 📖 **READ**: read_file, list_dir, glob, grep
- ✏️ **WRITE**: write_file, edit_file
- 🖥️ **SHELL**: shell (with 40+ blocked dangerous commands)
- 🌐 **NETWORK**: web_search, web_fetch
- 💾 **MEMORY**: todos (task management), memory (persistent key-value storage)

### Component Colors

- **Yellow/Gold**: User-facing elements
- **Cyan**: Read operations
- **Green**: Success states
- **Red**: Error states
- **Blue**: Network operations
- **White**: System operations

---

## 🆕 NEW: Session Architecture

```
┌───────────────────────────────────────────────────┐
│                    SESSION                        │
│  ┌──────────────────────────────────────────────┐ │
│  │  • session_id: UUID                          │ │
│  │  • created_at: timestamp                     │ │
│  │  • updated_at: timestamp                     │ │
│  │  • _turn_count: int                          │ │
│  └──────────────────────────────────────────────┘ │
│                                                   │
│  ┌──────────────────┐  ┌──────────────────┐     │
│  │  Context Manager │  │   LLM Client     │     │
│  │   (Messages +    │  │   (OpenAI API)   │     │
│  │   System Prompt  │  │                  │     │
│  │   + User Memory  │  │                  │     │
│  │   + Tool Docs)   │  │                  │     │
│  └──────────────────┘  └──────────────────┘     │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │          Tool Registry (11 Tools)           │ │
│  │  ┌─────────────────────────────────────┐   │ │
│  │  │ read_file, write_file, edit_file    │   │ │
│  │  │ shell, list_dir, glob, grep         │   │ │
│  │  │ web_search, web_fetch               │   │ │
│  │  │ todos, memory                       │   │ │
│  │  └─────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  Memory Loading:                                 │
│    → Loads from: user_memory.json                │
│    → Adds to System Prompt                       │
│    → Available to LLM context                    │
└───────────────────────────────────────────────────┘
```

### Key Changes:

1. **Session-based**: All components now inside Session object
2. **Turn tracking**: Each loop increments turn count
3. **Memory integration**: Loads user_memory.json → system prompt
4. **11 Tools**: Expanded from 1 tool to 11 builtin tools
5. **Tool safety**: Shell tool blocks 40+ dangerous commands
6. **Config injection**: Tools receive Config for better integration

---

## 🔧 Tool Safety & Features

### Shell Tool Safety

**Blocked Commands (40+):**

```
❌ rm -rf /, format c:, dd if=/dev/zero
❌ shutdown, reboot, poweroff
❌ chmod 777 /, icacls, takeown
❌ curl, wget, ssh, scp (network exfiltration)
❌ eval, exec, os.system (code execution)
❌ Fork bombs: :(){ :|:& };:
```

**Features:**

- Timeout protection (default 120s, max 600s)
- Working directory support
- stdout/stderr capture
- Exit code tracking

### Memory & Todos

**Memory Tool:** Persistent JSON storage

- Actions: set, get, delete, list, clear
- Location: `~/.simhacli/user_memory.json`
- Loaded into system prompt automatically

**Todos Tool:** In-memory task management

- Priorities: high 🔴, medium 🟡, low 🟢
- States: not_started, in_progress, completed
- Actions: add, start, complete, list, remove, clear
- 8-character UUID per task

### Web Tools

**web_search:** Search engine queries
**web_fetch:** Fetch and extract content from URLs

---

## 🔄 Updated Architecture Summary

**Entry Point:** `main.py` → CLI interface with Click
**Core Agent:** `agent/agent.py` → Orchestrates via Session
**Session:** `agent/session.py` → **NEW!** Encapsulates LLM + Context + Tools
**LLM Client:** `client/llm_client.py` → OpenAI API integration
**Context:** `context/manager.py` → Message history + memory management
**Tools:** `tools/` → **11 builtin tools** (up from 1!)
**UI:** `ui/tui.py` → Rich terminal interface
**Config:** `config/` → TOML-based configuration + data directory
**Events:** `agent/events.py` → Event-driven architecture
**Prompts:** `prompts/system.py` → System prompt + memory injection
**Utils:** `utils/` → Helper functions (paths, text, errors)

### Data Flow Summary (Updated)

```
User → CLI → Agent → Session (NEW!)
                       ↓
          ┌────────────┼────────────┐
          │            │            │
    Context     LLM Client    Tool Registry
  (+ Memory)                   (11 Tools)
          │            │            │
          └────────────┼────────────┘
                       ↓
                OpenAI API (with tools)
                       ↓
              Stream Events
                       ↓
          Parse & Execute Tools
                       ↓
          Add Results to Context
                       ↓
        Continue Loop (Turn++)
                       ↓
              TUI Display
```
