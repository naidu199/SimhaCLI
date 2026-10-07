// Tool approvals for `approval/request` from the backend.
//
// Approvals are shown as cards in the chat panel (Approve / Deny / View diff),
// so the user can inspect the diff without a modal dialog blocking the window.
// If the panel isn't available, a modal dialog is used instead.

import * as vscode from "vscode";

import type { ApprovalRequestParams } from "./protocol";

const APPROVE = "Approve";

function describe(request: ApprovalRequestParams): string {
  const lines = [request.description];
  if (request.command && !request.description.includes(request.command)) {
    lines.push(`Command: ${request.command}`);
  }
  if (request.paths.length > 0) {
    lines.push(`Files: ${request.paths.join(", ")}`);
  }
  if (request.isDangerous) {
    lines.push("", "⚠ SimhaCLI flagged this action as potentially destructive.");
  }
  return lines.join("\n");
}

/** Ask with a modal dialog; closing the dialog counts as a denial. */
export async function askApprovalModal(request: ApprovalRequestParams): Promise<boolean> {
  const choice = await vscode.window.showWarningMessage(
    `SimhaCLI wants to use ${request.tool}`,
    { modal: true, detail: describe(request) },
    APPROVE,
  );
  return choice === APPROVE;
}

/** What the coordinator needs from the chat panel. */
export interface ApprovalSurface {
  /** True when the panel can show an approval card right now. */
  readonly canShowApprovals: boolean;
  showApproval(id: string, request: ApprovalRequestParams): void;
  resolveApproval(id: string, approved: boolean, reason?: string): void;
}

interface PendingApproval {
  request: ApprovalRequestParams;
  resolve: (approved: boolean) => void;
}

export class ApprovalCoordinator {
  private readonly pending = new Map<string, PendingApproval>();
  private nextId = 1;

  constructor(private readonly surface: ApprovalSurface) {}

  /** Approval handler for the backend controller. */
  readonly handle = (request: ApprovalRequestParams): Promise<boolean> => {
    if (!this.surface.canShowApprovals) {
      return askApprovalModal(request);
    }
    const id = `a${this.nextId++}`;
    return new Promise<boolean>((resolve) => {
      this.pending.set(id, { request, resolve });
      this.surface.showApproval(id, request);
    });
  };

  get(id: string): ApprovalRequestParams | undefined {
    return this.pending.get(id)?.request;
  }

  /** The user clicked Approve or Deny in the panel. */
  respond(id: string, approved: boolean): void {
    this.settle(id, approved);
  }

  /** The turn ended (e.g. cancelled) while approvals were open: deny them. */
  cancelForTurn(turnId: string): void {
    for (const [id, pending] of this.pending) {
      if (pending.request.turnId === turnId) {
        this.settle(id, false, "cancelled");
      }
    }
  }

  /** The backend went away: deny everything still open. */
  cancelAll(): void {
    for (const id of [...this.pending.keys()]) {
      this.settle(id, false, "cancelled");
    }
  }

  private settle(id: string, approved: boolean, reason?: string): void {
    const pending = this.pending.get(id);
    if (!pending) {
      return;
    }
    this.pending.delete(id);
    pending.resolve(approved);
    this.surface.resolveApproval(id, approved, reason);
  }
}
