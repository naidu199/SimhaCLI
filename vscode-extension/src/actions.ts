// User actions shared by commands (palette, view title, editor menu) and the
// chat panel's buttons.

import * as path from "path";
import * as vscode from "vscode";

import type { ApprovalCoordinator } from "./approvals";
import type { ChatViewProvider } from "./chatViewProvider";
import type { SelectionIntent } from "./codeActions";
import type { BackendController } from "./controller";
import type { DiffContentProvider } from "./diffs";
import { activeEditorAttachment } from "./editorContext";
import { rangeAttachment, rangeLabel } from "./editorTracker";
import { messageOf, pickApproval, pickCredentials, pickModel, pickRevert } from "./pickers";

const SELECTION_PROMPTS: Record<Exclude<SelectionIntent, "modify">, string> = {
  review:
    "Review this code. Point out bugs, edge cases, and readability or performance problems, most important first. Don't change any files.",
  explain: "Explain what this code does, step by step, and call out anything surprising.",
};

const ATTACH_EXCLUDE = "{**/node_modules/**,**/.git/**,**/__pycache__/**,**/.venv/**,**/venv/**,**/dist/**,**/build/**}";

export class ChatActions {
  constructor(
    private readonly controller: BackendController,
    private readonly chatView: ChatViewProvider,
    private readonly approvals: ApprovalCoordinator,
    private readonly diffs: DiffContentProvider,
  ) {}

  async newChat(): Promise<void> {
    await this.run("start a new chat", async () => {
      await this.controller.call("sessions/new", {});
      this.chatView.showCleared();
    });
  }

  /** Show saved chats inside the panel. */
  async showHistory(): Promise<void> {
    await this.run("open chat history", async () => {
      await this.chatView.reveal();
      const { sessions } = await this.controller.call("sessions/list", { limit: 200 });
      this.chatView.showHistory(sessions);
    });
  }

  async resumeSession(id: string): Promise<void> {
    await this.run("open the chat", async () => {
      const result = await this.controller.call("sessions/resume", { id });
      this.chatView.showTranscript(result.title, result.messages, result.warning);
    });
  }

  async deleteSession(id: string): Promise<void> {
    await this.run("delete the chat", async () => {
      await this.controller.call("sessions/delete", { id });
      const { sessions } = await this.controller.call("sessions/list", { limit: 200 });
      this.chatView.showHistory(sessions);
    });
  }

  async setApproval(policy: string): Promise<void> {
    await this.run("change the approval policy", () => this.controller.setApproval(policy));
  }

  /** Attach the active file or selection to the next message. */
  async attachActiveEditor(): Promise<void> {
    const result = activeEditorAttachment();
    if ("error" in result) {
      void vscode.window.showInformationMessage(result.error);
      return;
    }
    await this.chatView.reveal();
    this.chatView.addAttachment(result.attachment);
    if (result.unsaved) {
      this.chatView.showNotice(
        `${path.basename(result.attachment.path)} has unsaved changes. SimhaCLI reads the saved version.`,
      );
    }
    this.chatView.focusInput();
  }

  /** Modify / Review / Explain the selected code (code-action menu, commands). */
  async askWithSelection(intent: SelectionIntent, uri?: vscode.Uri, range?: vscode.Range): Promise<void> {
    await this.run("use the selection", async () => {
      const editor = vscode.window.activeTextEditor;
      const document = uri ? await vscode.workspace.openTextDocument(uri) : editor?.document;
      const selection = range ?? editor?.selection;
      if (!document || !selection || selection.isEmpty) {
        void vscode.window.showInformationMessage("Select some code first.");
        return;
      }
      if (intent === "modify") {
        // The selection is already shown in the composer (tracked automatically);
        // the user only has to say what to change.
        await this.chatView.whenReady();
        this.chatView.prefill("Change this code to ");
        return;
      }
      await this.chatView.sendFromExtension(
        SELECTION_PROMPTS[intent],
        rangeAttachment(document, selection),
        rangeLabel(document, selection),
      );
    });
  }

  /** Paperclip: pick any workspace files to attach to the next message. */
  async pickFilesToAttach(): Promise<void> {
    await this.run("attach files", async () => {
      const files = await vscode.workspace.findFiles("**/*", ATTACH_EXCLUDE, 5000);
      const activePath = vscode.window.activeTextEditor?.document.uri.fsPath;
      const items = files
        .map((uri) => {
          const relative = vscode.workspace.asRelativePath(uri, false);
          return {
            label: path.basename(relative),
            description: path.dirname(relative) === "." ? "" : path.dirname(relative),
            relative,
            uri,
          };
        })
        .sort((a, b) =>
          a.uri.fsPath === activePath ? -1 : b.uri.fsPath === activePath ? 1 : a.relative.localeCompare(b.relative),
        );
      const picked = await vscode.window.showQuickPick(items, {
        title: "SimhaCLI: Attach Files",
        placeHolder: "Search files to attach to your message",
        canPickMany: true,
        matchOnDescription: true,
      });
      if (!picked?.length) {
        return;
      }
      for (const item of picked) {
        this.chatView.addAttachment({ path: item.uri.fsPath, label: item.relative });
      }
      this.chatView.focusInput();
    });
  }

  async changeModel(): Promise<void> {
    await this.run("change the model", () => pickModel(this.controller));
  }

  async changeApproval(): Promise<void> {
    await this.run("change the approval policy", () => pickApproval(this.controller));
  }

  async setCredentials(): Promise<void> {
    await this.run("save the credentials", async () => {
      if (await pickCredentials(this.controller)) {
        this.chatView.showNotice("Credentials saved.");
      }
    });
  }

  async revertChanges(): Promise<void> {
    await this.run("revert the changes", async () => {
      const summary = await pickRevert(this.controller);
      if (summary) {
        this.chatView.showNotice(summary);
      }
    });
  }

  async viewDiff(approvalId: string): Promise<void> {
    const change = this.approvals.get(approvalId)?.fileChange;
    if (change) {
      await this.diffs.open(change);
    }
  }

  async copy(text: string): Promise<void> {
    await vscode.env.clipboard.writeText(text);
    vscode.window.setStatusBarMessage("$(check) Copied", 2000);
  }

  /** Open a link from the chat: web links in the browser, file paths in the editor. */
  async openLink(href: string): Promise<void> {
    if (/^(https?|mailto):/i.test(href)) {
      await vscode.env.openExternal(vscode.Uri.parse(href));
      return;
    }
    const cwd = this.controller.currentState.cwd;
    if (!cwd || /^[a-z][a-z0-9+.-]*:/i.test(href)) {
      return; // other schemes (javascript:, command:, …) are ignored
    }
    const [file, line] = decodeURIComponent(href).split("#L");
    const target = vscode.Uri.file(path.resolve(cwd, file));
    try {
      const editor = await vscode.window.showTextDocument(target, { preview: true });
      const lineNumber = Number.parseInt(line ?? "", 10);
      if (lineNumber > 0) {
        const position = new vscode.Position(lineNumber - 1, 0);
        editor.selection = new vscode.Selection(position, position);
        editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
      }
    } catch {
      void vscode.window.showInformationMessage(`Couldn't open ${file}`);
    }
  }

  private async run(what: string, action: () => Promise<unknown>): Promise<void> {
    try {
      await action();
    } catch (error) {
      void vscode.window.showErrorMessage(`SimhaCLI couldn't ${what}: ${messageOf(error)}`);
    }
  }
}
