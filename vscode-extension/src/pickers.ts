// Quick picks and input boxes for history, settings and reverting changes.

import * as path from "path";
import * as vscode from "vscode";

import type { BackendController } from "./controller";
import type { SessionSummary, TranscriptMessage, UndoChange } from "./protocol";

// Matches safety/approval.py. Destructive commands (rm -rf /, etc.) are
// refused under every policy except yolo.
const APPROVAL_DESCRIPTIONS: Record<string, string> = {
  on_request: "Ask for commands that aren't read-only and for risky file changes (default)",
  auto_edit: "Currently the same as on_request",
  always: "Ask before every tool that changes something",
  on_failure: "Run commands without asking; still ask for risky file changes",
  auto_approve: "Run commands without asking; still ask for risky file changes",
  yolo: "Never ask, even for destructive commands",
  never: "Never ask: block anything that would need approval (read-only commands still run)",
};

const PROVIDERS = [
  { label: "OpenRouter", url: "https://openrouter.ai/api/v1" },
  { label: "OpenAI", url: "https://api.openai.com/v1" },
];

/**
 * Path relative to the workspace. Backend paths are fully resolved (e.g.
 * /private/var/… on macOS) while VS Code may know the folder via a symlink,
 * so compare against the backend's own resolved cwd first.
 */
export function displayPath(filePath: string, controller: BackendController): string {
  const cwd = controller.currentState.cwd;
  if (cwd) {
    const relative = path.relative(cwd, filePath);
    if (relative && !relative.startsWith("..") && !path.isAbsolute(relative)) {
      return relative;
    }
  }
  return vscode.workspace.asRelativePath(filePath, false);
}

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) {
    return iso;
  }
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} d ago`;
  return new Date(iso).toLocaleDateString();
}

interface SessionItem extends vscode.QuickPickItem {
  session: SessionSummary;
}

export interface ResumedChat {
  title: string | null;
  messages: TranscriptMessage[];
  warning?: string;
}

/** Pick a saved chat to continue. Resolves with the resumed chat, if any. */
export async function pickSession(controller: BackendController): Promise<ResumedChat | undefined> {
  const { sessions } = await controller.call("sessions/list", { limit: 200 });
  if (sessions.length === 0) {
    void vscode.window.showInformationMessage("No saved chats yet.");
    return undefined;
  }
  const cwd = controller.currentState.cwd;
  const deleteButton: vscode.QuickInputButton = {
    iconPath: new vscode.ThemeIcon("trash"),
    tooltip: "Delete this chat",
  };
  const toItem = (session: SessionSummary): SessionItem => ({
    label: `${session.isCurrent ? "$(comment-discussion) " : ""}${session.title ?? "(no messages)"}`,
    description: `${relativeTime(session.updatedAt)} · ${session.messageCount} messages${
      session.source && session.source !== "cli" ? ` · ${session.source}` : ""
    }`,
    detail: session.cwd && session.cwd !== cwd ? session.cwd : undefined,
    buttons: session.isCurrent ? [] : [deleteButton],
    session,
  });

  const quickPick = vscode.window.createQuickPick<SessionItem>();
  quickPick.title = "SimhaCLI: Chat History";
  quickPick.placeholder = "Pick a chat to continue it";
  quickPick.matchOnDescription = true;
  quickPick.items = sessions.map(toItem);

  return new Promise<ResumedChat | undefined>((resolve) => {
    let settled = false;
    const finish = (value: ResumedChat | undefined) => {
      if (!settled) {
        settled = true;
        resolve(value);
        quickPick.dispose();
      }
    };
    quickPick.onDidTriggerItemButton(async ({ item }) => {
      try {
        await controller.call("sessions/delete", { id: item.session.id });
        quickPick.items = quickPick.items.filter((i) => i.session.id !== item.session.id);
      } catch (error) {
        void vscode.window.showErrorMessage(`Couldn't delete the chat: ${messageOf(error)}`);
      }
    });
    quickPick.onDidAccept(async () => {
      const item = quickPick.selectedItems[0];
      if (!item || item.session.isCurrent) {
        finish(undefined);
        return;
      }
      quickPick.busy = true;
      try {
        const result = await controller.call("sessions/resume", { id: item.session.id });
        finish({ title: result.title, messages: result.messages, warning: result.warning });
      } catch (error) {
        quickPick.busy = false;
        void vscode.window.showErrorMessage(`Couldn't open the chat: ${messageOf(error)}`);
      }
    });
    quickPick.onDidHide(() => finish(undefined));
    quickPick.show();
  });
}

export async function pickModel(controller: BackendController): Promise<void> {
  const current = controller.currentState.model ?? "";
  const name = await vscode.window.showInputBox({
    title: "SimhaCLI: Model",
    prompt: "Model name as your provider expects it (saved to this project's .simhacli/config.toml)",
    value: current,
    validateInput: (value) => (value.trim() ? undefined : "Enter a model name"),
  });
  if (name !== undefined && name.trim() !== current) {
    await controller.setModel(name.trim());
  }
}

export async function pickApproval(controller: BackendController): Promise<void> {
  const config = await controller.getConfig();
  const items = config.approvalPolicies.map((policy) => ({
    label: policy === config.approval ? `$(check) ${policy}` : policy,
    description: APPROVAL_DESCRIPTIONS[policy] ?? "",
    policy,
  }));
  const choice = await vscode.window.showQuickPick(items, {
    title: "SimhaCLI: Approval Policy",
    placeHolder: "When should SimhaCLI ask before running a tool?",
  });
  if (choice && choice.policy !== config.approval) {
    await controller.setApproval(choice.policy);
  }
}

export async function pickCredentials(controller: BackendController): Promise<boolean> {
  const config = await controller.getConfig();
  const urlItems: (vscode.QuickPickItem & { url?: string; custom?: boolean })[] = [
    ...PROVIDERS.map((p) => ({ label: p.label, description: p.url, url: p.url })),
    { label: "Other provider…", description: "Any OpenAI-compatible base URL", custom: true },
  ];
  if (config.apiBaseUrl && !PROVIDERS.some((p) => p.url === config.apiBaseUrl)) {
    urlItems.unshift({ label: "Keep current", description: config.apiBaseUrl, url: config.apiBaseUrl });
  }
  const urlChoice = await vscode.window.showQuickPick(urlItems, {
    title: "SimhaCLI: API Provider",
    placeHolder: "Which OpenAI-compatible API should SimhaCLI use?",
  });
  if (!urlChoice) {
    return false;
  }
  let baseUrl = urlChoice.url;
  if (urlChoice.custom) {
    baseUrl = await vscode.window.showInputBox({
      title: "SimhaCLI: API Base URL",
      value: config.apiBaseUrl ?? "",
      placeHolder: "https://…/v1",
      validateInput: (value) => (/^https?:\/\/\S+$/.test(value.trim()) ? undefined : "Enter an http(s) URL"),
    });
    if (baseUrl === undefined) {
      return false;
    }
  }

  const apiKey = await vscode.window.showInputBox({
    title: "SimhaCLI: API Key",
    prompt: config.hasApiKey
      ? "Leave empty to keep the current key. Saved to your SimhaCLI config file (readable only by you)."
      : "Saved to your SimhaCLI config file (readable only by you).",
    password: true,
    ignoreFocusOut: true,
    validateInput: (value) => (config.hasApiKey || value.trim() ? undefined : "Enter an API key"),
  });
  if (apiKey === undefined) {
    return false;
  }
  await controller.setCredentials(apiKey.trim() || undefined, baseUrl?.trim() || undefined);
  return true;
}

/** Let the user pick which of the latest turn's changes to revert. */
export async function pickRevert(controller: BackendController): Promise<string | undefined> {
  const { changes } = await controller.call("undo/list", {});
  if (changes.length === 0) {
    return "Nothing to revert: the latest reply didn't change any files (or they were already reverted).";
  }
  const items = changes.map((change: UndoChange) => ({
    label: displayPath(change.path, controller),
    description: change.isNewFile ? "new file (will be deleted)" : "edited (will be restored)",
    picked: true,
    change,
  }));
  const picked = await vscode.window.showQuickPick(items, {
    title: "SimhaCLI: Revert Changes",
    placeHolder: "Files changed by the latest reply. Uncheck any you want to keep.",
    canPickMany: true,
  });
  if (!picked || picked.length === 0) {
    return undefined;
  }

  const reverted: string[] = [];
  const skipped: string[] = [];
  if (picked.length === changes.length) {
    const result = await controller.call("undo/revert", { all: true });
    reverted.push(...result.reverted);
    skipped.push(...result.skipped.map((s) => `${displayPath(s.path, controller)}: ${s.reason ?? s.status}`));
  } else {
    // Highest index first so the remaining indices stay valid
    for (const item of [...picked].sort((a, b) => b.change.index - a.change.index)) {
      const result = await controller.call("undo/revert", { index: item.change.index });
      reverted.push(...result.reverted);
      skipped.push(...result.skipped.map((s) => `${displayPath(s.path, controller)}: ${s.reason ?? s.status}`));
    }
  }
  const parts = [];
  if (reverted.length) {
    parts.push(`Reverted ${reverted.map((p) => displayPath(p, controller)).join(", ")}.`);
  }
  if (skipped.length) {
    parts.push(`Not reverted: ${skipped.join("; ")}.`);
  }
  return parts.join(" ");
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
