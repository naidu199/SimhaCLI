// Message contract between the chat panel (webview) and the extension.
// The panel only ever talks to the extension through these messages, so it
// can be rewritten (e.g. with a UI framework) without touching anything else.

import type {
  AgentEventType,
  ApprovalRequestParams,
  SessionSummary,
  TranscriptMessage,
  TurnStatus,
} from "./protocol";

export type BackendStatus = "starting" | "ready" | "stopped" | "noWorkspace";

export interface PanelState {
  status: BackendStatus;
  /** Human-readable detail for the status (error text, hints). */
  detail?: string;
  model?: string;
  approval?: string;
  cwd?: string;
  needsCredentials?: boolean;
  /** Turn currently running, if any. */
  turnId?: string;
}

/** A file (or part of one) attached to the next message. */
export interface PanelAttachment {
  path: string;
  startLine?: number;
  endLine?: number;
  /** Short label shown on the chip, e.g. "app.py:10-24". */
  label: string;
}

export type NoticeKind = "info" | "error";

/** Extension → panel. */
export type ToPanel =
  | { type: "state"; state: PanelState }
  | { type: "turnStarted"; turnId: string; text: string }
  | { type: "sendFailed"; text: string; message: string }
  | { type: "agentEvent"; turnId: string; event: AgentEventType; data: Record<string, unknown> }
  | { type: "turnFinished"; turnId: string; status: TurnStatus; error?: string; undoCount: number }
  | { type: "approvalRequest"; id: string; request: ApprovalRequestParams }
  | { type: "approvalResolved"; id: string; approved: boolean; reason?: string }
  | { type: "addAttachment"; attachment: PanelAttachment }
  | { type: "focusInput" }
  | { type: "loadTranscript"; title: string | null; messages: TranscriptMessage[]; warning?: string }
  | { type: "cleared" }
  | { type: "notice"; text: string; kind: NoticeKind }
  | { type: "history"; sessions: SessionSummary[] };

/** Panel → extension. */
export type FromPanel =
  | { type: "ready" }
  | { type: "send"; text: string; attachments: PanelAttachment[] }
  | { type: "cancel" }
  | { type: "restartBackend" }
  | { type: "showLogs" }
  | { type: "approvalResponse"; id: string; approved: boolean }
  | { type: "viewDiff"; id: string }
  | { type: "attachActiveEditor" }
  | { type: "copy"; text: string }
  | { type: "openLink"; href: string }
  | { type: "pickModel" }
  | { type: "pickApproval" }
  | { type: "setCredentials" }
  | { type: "revertChanges" }
  | { type: "newChat" }
  | { type: "showHistory" }
  | { type: "resumeSession"; id: string }
  | { type: "deleteSession"; id: string }
  | { type: "setApproval"; policy: string };
