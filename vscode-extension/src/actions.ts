// User actions shared by commands (palette, view title, editor menu) and the
// chat panel's buttons.

import * as path from "path";
import * as vscode from "vscode";

import type { ApprovalCoordinator } from "./approvals";
import type { ChatViewProvider } from "./chatViewProvider";
import type { BackendController } from "./controller";
import type { DiffContentProvider } from "./diffs";
import { activeEditorAttachment } from "./editorContext";
import { messageOf, pickApproval, pickCredentials, pickModel, pickRevert, pickSession } from "./pickers";

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

  async showHistory(): Promise<void> {
    await this.run("open chat history", async () => {
      const resumed = await pickSession(this.controller);
      if (resumed) {
        await this.chatView.reveal();
        this.chatView.showTranscript(resumed.title, resumed.messages, resumed.warning);
      }
    });
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
