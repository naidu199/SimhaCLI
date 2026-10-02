// Tool approval prompts for `approval/request` from the backend.

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

/** Ask the user; closing the dialog counts as a denial. */
export async function askApproval(request: ApprovalRequestParams): Promise<boolean> {
  const choice = await vscode.window.showWarningMessage(
    `SimhaCLI wants to use ${request.tool}`,
    { modal: true, detail: describe(request) },
    APPROVE,
  );
  return choice === APPROVE;
}
