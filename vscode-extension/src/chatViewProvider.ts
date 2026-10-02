// The sidebar chat panel: hosts the webview and bridges it to the controller.

import * as crypto from "crypto";
import * as vscode from "vscode";

import type { ChatActions } from "./actions";
import type { ApprovalCoordinator, ApprovalSurface } from "./approvals";
import { BackendController, errorMessage } from "./controller";
import type { EditorTracker } from "./editorTracker";
import type { ApprovalRequestParams, Attachment, SessionSummary, TranscriptMessage } from "./protocol";
import type { EditorContextUse, FromPanel, NoticeKind, PanelAttachment, ToPanel } from "./webviewMessages";

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
    private readonly editors: EditorTracker,
  ) {
    this.disposables.push(
      this.postedEmitter,
      editors.onDidChange((context) => this.post({ type: "editorContext", context })),
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

  /** Resolves once the panel has loaded (or after a timeout). */
  async whenReady(timeoutMs = 10000): Promise<boolean> {
    await this.reveal();
    const deadline = Date.now() + timeoutMs;
    while (!this.ready && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    return this.ready;
  }

  /**
   * Same path as the panel's Send button. `editorContext` adds the active
   * editor's selection (or file), read fresh from the editor at send time.
   */
  async send(
    text: string,
    attachments: (PanelAttachment | Attachment)[] = [],
    editorContext: EditorContextUse = "none",
  ): Promise<void> {
    try {
      const fromEditor = this.editors.attachment(editorContext);
      const all: Attachment[] = [
        ...(fromEditor ? [fromEditor] : []),
        ...attachments.map(({ path, startLine, endLine, content }: Attachment) => ({ path, startLine, endLine, content })),
      ];
      const turnId = await this.controller.send(text, all);
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

  showHistory(sessions: SessionSummary[]): void {
    this.postUi({ type: "history", sessions });
  }

  /** Send a message on the user's behalf (e.g. "Review with SimhaCLI"). */
  async sendFromExtension(text: string, attachment: Attachment, label: string): Promise<void> {
    await this.whenReady();
    this.postUi({ type: "userMessage", text, labels: [label] });
    await this.send(text, [attachment], "none");
  }

  /** Put text in the message box and focus it (the user finishes the request). */
  prefill(text: string): void {
    this.postUi({ type: "prefill", text });
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
        this.post({ type: "editorContext", context: this.editors.current });
        for (const queued of this.queued.splice(0)) {
          this.post(queued);
        }
        break;
      case "send":
        await this.send(message.text, message.attachments ?? [], message.editorContext ?? "none");
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
      case "attachFiles":
        await actions?.pickFilesToAttach();
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
      case "resumeSession":
        await actions?.resumeSession(message.id);
        break;
      case "deleteSession":
        await actions?.deleteSession(message.id);
        break;
      case "setApproval":
        await actions?.setApproval(message.policy);
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
  <section id="chatView" class="view">
    <main id="messages" class="messages" aria-live="polite"></main>
    <form id="composer" class="composer">
      <div id="modeMenu" class="menu" role="menu" hidden></div>
      <div class="composer-box">
        <div id="attachments" class="attachments" hidden></div>
        <textarea id="input" rows="1" placeholder="Ask SimhaCLI anything…" aria-label="Message"></textarea>
        <div class="composer-toolbar">
          <button id="attach" type="button" class="icon-button" title="Attach files" aria-label="Attach files"></button>
          <button id="model" type="button" class="pill" title="Change model"></button>
          <button id="mode" type="button" class="pill mode" title="Approval mode" aria-haspopup="menu"></button>
          <span class="spacer"></span>
          <button id="stop" type="button" class="send-button stop" title="Stop" aria-label="Stop" hidden></button>
          <button id="send" type="submit" class="send-button" title="Send (Enter)" aria-label="Send"></button>
        </div>
      </div>
      <div class="composer-hint">Enter to send · Shift+Enter new line · <code>@path</code> adds a file</div>
    </form>
  </section>
  <section id="historyView" class="view history" hidden>
    <header class="history-header">
      <button id="historyBack" type="button" class="icon-button" title="Back to chat" aria-label="Back to chat"></button>
      <span class="history-title">Chat history</span>
    </header>
    <div class="history-search">
      <input id="historySearch" type="search" placeholder="Search chats" aria-label="Search chats">
    </div>
    <div id="historyList" class="history-list" role="list"></div>
  </section>
  <script nonce="${nonce}" src="${script}"></script>
</body>
</html>`;
  }
}
