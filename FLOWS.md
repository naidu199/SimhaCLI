# SimhaCLI Flow Diagrams 🦁

Visual representation of how SimhaCLI processes user requests, executes tools, and manages the complete agent lifecycle.

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
                  │  Initialize Agent    │
                  └──────────┬───────────┘
                             │
                ┌────────────┼────────────┐
                │            │            │
                ▼            ▼            ▼
    ┌─────────────────┐  ┌──────────┐  ┌──────────────┐
    │ Context Manager │  │   LLM    │  │     Tool     │
    │   (Messages)    │  │  Client  │  │   Registry   │
    └────────┬────────┘  └────┬─────┘  └──────┬───────┘
             │                │               │
             └────────────────┼───────────────┘
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
        │  Display Final       │
        │   Response           │
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

### Tool Kinds

- 📖 **READ**: Read-only operations (read_file)
- ✏️ **WRITE**: Write operations (write_file)
- 🖥️ **SHELL**: Shell command execution
- 🌐 **NETWORK**: Network requests
- 💾 **MEMORY**: Memory operations
- 🔌 **MCP**: Model Context Protocol tools

### Component Colors

- **Yellow/Gold**: User-facing elements
- **Cyan**: Read operations
- **Green**: Success states
- **Red**: Error states
- **Blue**: Network operations
- **White**: System operations
