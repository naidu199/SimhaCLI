// Message contract between the chat panel (webview) and the extension.
// The panel only ever talks to the extension through these messages, so it
// can be rewritten (e.g. with a UI framework) without touching anything else.

import type { AgentEventType, TurnStatus } from "./protocol";

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

/** Extension → panel. */
export type ToPanel =
  | { type: "state"; state: PanelState }
  | { type: "turnStarted"; turnId: string; text: string }
  | { type: "sendFailed"; text: string; message: string }
  | { type: "agentEvent"; turnId: string; event: AgentEventType; data: Record<string, unknown> }
  | { type: "turnFinished"; turnId: string; status: TurnStatus; error?: string; undoCount: number };

/** Panel → extension. */
export type FromPanel =
  | { type: "ready" }
  | { type: "send"; text: string }
  | { type: "cancel" }
  | { type: "restartBackend" }
  | { type: "showLogs" };
