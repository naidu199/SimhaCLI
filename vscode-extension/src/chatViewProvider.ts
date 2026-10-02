// The sidebar chat panel: hosts the webview and bridges it to the controller.

import * as crypto from "crypto";
import * as vscode from "vscode";

import type { ChatActions } from "./actions";
import type { ApprovalCoordinator, ApprovalSurface } from "./approvals";
import { BackendController, errorMessage } from "./controller";
import type { ApprovalRequestParams, TranscriptMessage } from "./protocol";
import type { FromPanel, NoticeKind, PanelAttachment, ToPanel } from "./webviewMessages";

const TITLE_LENGTH = 40;

export class ChatViewProvider implements vscode.WebviewViewProvider, ApprovalSurface, vscode.Disposable {
  static readonly viewId = "simhacli.chat";

  private view: vscode.WebviewView | undefined;
  private ready = false;
  /** UI messages sent before the panel was ready (agent events are not queued). */
  private queued: ToPanel[] = [];
  private actions: ChatActions | undefined;
  private approvals: ApprovalCoordinator | undefined;
  private chatTitle: string | undefined;
  private readonly disposables: vscode.Disposable[] = [];
  private readonly postedEmitter = new vscode.EventEmitter<ToPanel>();
  /** Fires for every message sent to the panel (used by integration tests). */
  readonly onDidPostMessage = this.postedEmitter.event;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly controller: BackendController,
    private readonly output: vscode.OutputChannel,
  ) {
    this.disposables.push(
      this.postedEmitter,
      controller.onDidChangeState((state) => this.post({ type: "state", state })),
      controller.onAgentEvent((e) =>
        this.post({ type: "agentEvent", turnId: e.turnId, event: e.type, data: e.data }),
      ),
      controller.onTurnFinished((f) =>
        this.post({
          type: "turnFinished",
          turnId: f.turnId,
          status: f.status,
          error: f.error,
          undoCount: f.undoCount,
        }),
      ),
    );
  }

  connect(actions: ChatActions, approvals: ApprovalCoordinator): void {
    this.actions = actions;
    this.approvals = approvals;
  }

  get isReady(): boolean {
    return this.ready;
  }

  get canShowApprovals(): boolean {
    return this.ready;
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    this.ready = false;
    const mediaRoots = [
      vscode.Uri.joinPath(this.extensionUri, "dist"),
      vscode.Uri.joinPath(this.extensionUri, "media"),
    ];
    view.webview.options = { enableScripts: true, localResourceRoots: mediaRoots };
    view.webview.html = this.html(view.webview);
    view.description = this.chatTitle;

    this.disposables.push(
      view.webview.onDidReceiveMessage((message: FromPanel) => void this.handle(message)),
      view.onDidDispose(() => {
        this.view = undefined;
        this.ready = false;
      }),
    );
  }

  /** Show the panel (opening the sidebar if needed). */
  async reveal(): Promise<void> {
    if (this.view) {
      this.view.show(true);
    } else {
      await vscode.commands.executeCommand(`${ChatViewProvider.viewId}.focus`);
    }
  }

  /** Same path as the panel's Send button. */
  async send(text: string, attachments: PanelAttachment[] = []): Promise<void> {
    try {
      const turnId = await this.controller.send(
        text,
        attachments.map(({ path, startLine, endLine }) => ({ path, startLine, endLine })),
      );
      if (!this.chatTitle) {
        this.setTitle(text);
      }
      this.post({ type: "turnStarted", turnId, text });
    } catch (error) {
      this.post({ type: "sendFailed", text, message: errorMessage(error) });
    }
  }

  showApproval(id: string, request: ApprovalRequestParams): void {
    void this.reveal();
    this.post({ type: "approvalRequest", id, request });
  }

  resolveApproval(id: string, approved: boolean, reason?: string): void {
    this.post({ type: "approvalResolved", id, approved, reason });
  }

  addAttachment(attachment: PanelAttachment): void {
    this.postUi({ type: "addAttachment", attachment });
  }

  focusInput(): void {
    this.postUi({ type: "focusInput" });
  }

  showTranscript(title: string | null, messages: TranscriptMessage[], warning?: string): void {
    this.setTitle(title ?? undefined);
    this.postUi({ type: "loadTranscript", title, messages, warning });
  }

  showCleared(): void {
    this.setTitle(undefined);
    this.postUi({ type: "cleared" });
  }

  showNotice(text: string, kind: NoticeKind = "info"): void {
    this.postUi({ type: "notice", text, kind });
  }

  dispose(): void {
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
  }

  // -------------------------------------------------------------------------

  private async handle(message: FromPanel): Promise<void> {
    const actions = this.actions;
    switch (message.type) {
      case "ready":
        this.ready = true;
        this.post({ type: "state", state: this.controller.currentState });
        for (const queued of this.queued.splice(0)) {
          this.post(queued);
        }
        break;
      case "send":
        await this.send(message.text, message.attachments ?? []);
        break;
      case "cancel":
        try {
          await this.controller.cancel();
        } catch (error) {
          this.output.appendLine(`Cancel failed: ${errorMessage(error)}`);
        }
        break;
      case "restartBackend":
        await this.controller.restart();
        break;
      case "showLogs":
        this.output.show();
        break;
      case "approvalResponse":
        this.approvals?.respond(message.id, message.approved);
        break;
      case "viewDiff":
        await actions?.viewDiff(message.id);
        break;
      case "attachActiveEditor":
        await actions?.attachActiveEditor();
        break;
      case "copy":
        await actions?.copy(message.text);
        break;
      case "openLink":
        await actions?.openLink(message.href);
        break;
      case "pickModel":
        await actions?.changeModel();
        break;
      case "pickApproval":
        await actions?.changeApproval();
        break;
      case "setCredentials":
        await actions?.setCredentials();
        break;
      case "revertChanges":
        await actions?.revertChanges();
        break;
      case "newChat":
        await actions?.newChat();
        break;
      case "showHistory":
        await actions?.showHistory();
        break;
    }
  }

  private setTitle(text: string | undefined): void {
    const oneLine = text?.replace(/\s+/g, " ").trim();
    this.chatTitle =
      oneLine && oneLine.length > TITLE_LENGTH ? `${oneLine.slice(0, TITLE_LENGTH - 1)}…` : oneLine || undefined;
    if (this.view) {
      this.view.description = this.chatTitle;
    }
  }

  private post(message: ToPanel): void {
    this.postedEmitter.fire(message);
    if (this.view && this.ready) {
      void this.view.webview.postMessage(message);
    }
  }

  /** Like post(), but kept until the panel is ready if it isn't yet. */
  private postUi(message: ToPanel): void {
    if (this.view && this.ready) {
      this.post(message);
    } else {
      this.queued.push(message);
      this.postedEmitter.fire(message);
    }
  }

  private html(webview: vscode.Webview): string {
    const nonce = crypto.randomBytes(16).toString("base64");
    const script = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "dist", "webview.js"));
    const style = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "media", "chat.css"));
    const csp = [
      "default-src 'none'",
      `style-src ${webview.cspSource}`,
      `img-src ${webview.cspSource} data:`,
      `font-src ${webview.cspSource}`,
      `script-src 'nonce-${nonce}'`,
    ].join("; ");

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="${csp}">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="${style}">
  <title>SimhaCLI</title>
</head>
<body>
  <div id="status" class="status" hidden></div>
  <main id="messages" class="messages" aria-live="polite">
    <div id="empty" class="empty">
      <p class="empty-title">Ask SimhaCLI to read, change or run things in this workspace.</p>
      <p>Attach the current file or selection with the paperclip, or type <code>@path</code> in your message.</p>
    </div>
  </main>
  <form id="composer" class="composer">
    <div id="attachments" class="attachments" hidden></div>
    <textarea id="input" rows="3" placeholder="Ask SimhaCLI… (Enter to send, Shift+Enter for a new line)" aria-label="Message"></textarea>
    <div class="composer-actions">
      <button id="attach" type="button" class="icon" title="Attach the current file or selection" aria-label="Attach the current file or selection">
        <!-- Lucide "paperclip" icon, https://lucide.dev, ISC License -->
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m16 6-8.414 8.586a2 2 0 0 0 2.829 2.829l8.414-8.586a4 4 0 1 0-5.657-5.657l-8.379 8.551a6 6 0 1 0 8.485 8.485l8.379-8.551"/></svg>
      </button>
      <button id="model" type="button" class="link" title="Change model"></button>
      <button id="approval" type="button" class="link" title="Change approval policy"></button>
      <span class="spacer"></span>
      <button id="stop" type="button" class="secondary" hidden>Stop</button>
      <button id="send" type="submit">Send</button>
    </div>
  </form>
  <script nonce="${nonce}" src="${script}"></script>
</body>
</html>`;
  }
}
