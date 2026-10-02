// Types for the `simhacli serve` protocol (SIMHACLI_SERVER_PLAN.md, section 3).
// Newline-delimited JSON over the server's stdin/stdout.

export const PROTOCOL_VERSION = 1;

export const ErrorCode = {
  ParseError: -32700,
  MethodNotFound: -32601,
  InvalidParams: -32602,
  ServerError: -32000,
  NotInitialized: -32001,
  TurnRunning: -32002,
  CredentialsMissing: -32003,
} as const;

// ---------------------------------------------------------------------------
// Wire messages
// ---------------------------------------------------------------------------

export interface RpcError {
  code: number;
  message: string;
}

export interface RequestMessage {
  id: number | string;
  method: string;
  params?: unknown;
}

export interface ResponseMessage {
  id: number | string | null;
  result?: unknown;
  error?: RpcError;
}

export interface NotificationMessage {
  method: string;
  params?: unknown;
}

// ---------------------------------------------------------------------------
// Extension → server
// ---------------------------------------------------------------------------

export interface InitializeParams {
  cwd?: string;
  clientName?: string;
  clientVersion?: string;
  protocolVersion?: number;
}

export interface InitializeResult {
  serverVersion: string;
  protocolVersion: number;
  cwd: string;
  model: string;
  approval: string;
  sessionId: string;
  needsCredentials: boolean;
}

export interface Attachment {
  path: string;
  startLine?: number;
  endLine?: number;
}

export interface ChatSendParams {
  text: string;
  attachments?: Attachment[];
}

export interface ChatSendResult {
  turnId: string;
}

export interface ToolCallSummary {
  name: string;
  arguments: Record<string, unknown> | string;
}

export interface TranscriptMessage {
  role: "user" | "assistant";
  text: string;
  toolCalls: ToolCallSummary[];
}

export interface SessionSummary {
  id: string;
  title: string | null;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
  cwd: string | null;
  model: string | null;
  source: string | null;
  isCurrent: boolean;
}

export interface ConfigResult {
  model: string;
  approval: string;
  approvalPolicies: string[];
  cwd: string;
  autoSaveSessions: boolean;
  apiBaseUrl: string | null;
  hasApiKey: boolean;
}

export interface UndoChange {
  index: number;
  path: string;
  isNewFile: boolean;
}

export interface UndoRevertResult {
  reverted: string[];
  skipped: { path: string; status: string; reason: string | null }[];
  remaining: number;
}

/** Request method → [params, result]. */
export interface Methods {
  initialize: [InitializeParams, InitializeResult];
  "chat/send": [ChatSendParams, ChatSendResult];
  "chat/cancel": [{ turnId: string }, { cancelled: boolean }];
  "sessions/list": [{ limit?: number }, { sessions: SessionSummary[] }];
  "sessions/history": [
    { id?: string },
    { id: string; title: string | null; messages: TranscriptMessage[] },
  ];
  "sessions/resume": [
    { id: string },
    { sessionId: string; title: string | null; messages: TranscriptMessage[]; warning?: string },
  ];
  "sessions/new": [Record<string, never>, { sessionId: string }];
  "sessions/delete": [{ id: string }, { deleted: boolean }];
  "config/get": [Record<string, never>, ConfigResult];
  "model/set": [{ name: string }, { model: string; savedTo?: string; saveError?: string }];
  "approval/set": [{ policy: string }, { approval: string; savedTo?: string; saveError?: string }];
  "credentials/set": [{ apiKey?: string; baseUrl?: string }, { needsCredentials: boolean }];
  "undo/list": [Record<string, never>, { changes: UndoChange[] }];
  "undo/revert": [{ index: number } | { all: true }, UndoRevertResult];
  shutdown: [Record<string, never>, Record<string, never>];
}

export type MethodName = keyof Methods;

// ---------------------------------------------------------------------------
// Server → extension
// ---------------------------------------------------------------------------

export type AgentEventType =
  | "agent_start"
  | "agent_end"
  | "agent_error"
  | "text_delta"
  | "text_complete"
  | "thinking_delta"
  | "thinking_complete"
  | "tool_call_start"
  | "tool_call_complete"
  | "loop_detected";

export interface AgentEventParams {
  turnId: string;
  type: AgentEventType;
  data: Record<string, unknown>;
}

export type TurnStatus = "completed" | "cancelled" | "error";

export interface TurnFinishedParams {
  turnId: string;
  status: TurnStatus;
  undoCount: number;
  error?: string;
}

export interface ServerLogParams {
  level: string;
  message: string;
}

export interface ApprovalRequestParams {
  turnId: string | null;
  tool: string;
  description: string;
  params: Record<string, unknown>;
  command: string | null;
  paths: string[];
  diff: string | null;
  isDangerous: boolean;
}

export interface ApprovalResult {
  approved: boolean;
}
