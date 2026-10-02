// The sidebar chat panel: hosts the webview and bridges it to the controller.

import * as crypto from "crypto";
import * as vscode from "vscode";

import { BackendController, errorMessage } from "./controller";
import type { FromPanel, ToPanel } from "./webviewMessages";

export class ChatViewProvider implements vscode.WebviewViewProvider, vscode.Disposable {
  static readonly viewId = "simhacli.chat";

  private view: vscode.WebviewView | undefined;
  private ready = false;
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

  get isReady(): boolean {
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

    this.disposables.push(
      view.webview.onDidReceiveMessage((message: FromPanel) => void this.handle(message)),
      view.onDidDispose(() => {
        this.view = undefined;
        this.ready = false;
      }),
    );
  }

  /** Same path as the panel's Send button. */
  async send(text: string): Promise<void> {
    try {
      const turnId = await this.controller.send(text);
      this.post({ type: "turnStarted", turnId, text });
    } catch (error) {
      this.post({ type: "sendFailed", text, message: errorMessage(error) });
    }
  }

  dispose(): void {
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
  }

  // -------------------------------------------------------------------------

  private async handle(message: FromPanel): Promise<void> {
    switch (message.type) {
      case "ready":
        this.ready = true;
        this.post({ type: "state", state: this.controller.currentState });
        break;
      case "send":
        await this.send(message.text);
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
    }
  }

  private post(message: ToPanel): void {
    this.postedEmitter.fire(message);
    if (this.view && this.ready) {
      void this.view.webview.postMessage(message);
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
  <main id="messages" class="messages" aria-live="polite"></main>
  <form id="composer" class="composer">
    <textarea id="input" rows="3" placeholder="Ask SimhaCLI… (Enter to send, Shift+Enter for a new line)"></textarea>
    <div class="composer-actions">
      <span id="meta" class="meta"></span>
      <button id="stop" type="button" class="secondary" hidden>Stop</button>
      <button id="send" type="submit">Send</button>
    </div>
  </form>
  <script nonce="${nonce}" src="${script}"></script>
</body>
</html>`;
  }
}
