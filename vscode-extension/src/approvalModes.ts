// Approval policies as shown in the UI (shared by the extension and the panel).
// Descriptions match safety/approval.py. Destructive commands (rm -rf /, …)
// are refused under every policy except yolo.

/** How much the policy lets the agent do without asking. */
export type ModeRisk = "safe" | "standard" | "risky" | "danger";

export interface ApprovalMode {
  policy: string;
  label: string;
  description: string;
  risk: ModeRisk;
}

export const APPROVAL_MODES: ApprovalMode[] = [
  {
    policy: "on_request",
    label: "Ask",
    description: "Ask for commands that aren't read-only and for risky file changes (default)",
    risk: "standard",
  },
  {
    policy: "auto_edit",
    label: "Auto-edit",
    description: "Currently the same as Ask",
    risk: "standard",
  },
  {
    policy: "always",
    label: "Always ask",
    description: "Ask before every tool that changes something",
    risk: "safe",
  },
  {
    policy: "never",
    label: "Never run",
    description: "Block anything that would need approval (read-only commands still run)",
    risk: "safe",
  },
  {
    policy: "on_failure",
    label: "On failure",
    description: "Run commands without asking; still ask for risky file changes",
    risk: "risky",
  },
  {
    policy: "auto_approve",
    label: "Auto-approve",
    description: "Run commands without asking; still ask for risky file changes",
    risk: "risky",
  },
  {
    policy: "yolo",
    label: "YOLO",
    description: "Never ask, even for destructive commands",
    risk: "danger",
  },
];

export function approvalMode(policy: string | undefined): ApprovalMode {
  return (
    APPROVAL_MODES.find((mode) => mode.policy === policy) ?? {
      policy: policy ?? "",
      label: policy ?? "",
      description: "",
      risk: "standard",
    }
  );
}
