import * as vscode from "vscode";

import { ChatActions } from "./actions";
import { ApprovalCoordinator } from "./approvals";
import { ChatViewProvider } from "./chatViewProvider";
import { BackendController } from "./controller";
import { DiffContentProvider } from "./diffs";

let controller: BackendController | undefined;

/** Returned from activate(); used by integration tests, not a public API. */
export interface SimhaCliExtensionApi {
  controller: BackendController;
  chatView: ChatViewProvider;
  approvals: ApprovalCoordinator;
  actions: ChatActions;
  /** This extension's `vscode.window`, so tests can answer its dialogs. */
  window: typeof vscode.window;
}

export function activate(context: vscode.ExtensionContext): SimhaCliExtensionApi {
  const output = vscode.window.createOutputChannel("SimhaCLI");
  const version = String(context.extension.packageJSON.version ?? "0.0.0");

  controller = new BackendController(output, version);
  const chatView = new ChatViewProvider(context.extensionUri, controller, output);
  const approvals = new ApprovalCoordinator(chatView);
  const diffs = new DiffContentProvider();
  const actions = new ChatActions(controller, chatView, approvals, diffs);
  chatView.connect(actions, approvals);
  controller.setApprovalHandler(approvals.handle);

  const command = (id: string, run: () => unknown) => vscode.commands.registerCommand(id, run);
  context.subscriptions.push(
    output,
    controller,
    chatView,
    diffs,
    vscode.window.registerWebviewViewProvider(ChatViewProvider.viewId, chatView, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
    // Open approvals can't be answered once their turn or the backend is gone
    controller.onTurnFinished((finished) => approvals.cancelForTurn(finished.turnId)),
    controller.onDidChangeState((state) => {
      if (state.status !== "ready") {
        approvals.cancelAll();
      }
    }),
    command("simhacli.newChat", () => actions.newChat()),
    command("simhacli.history", () => actions.showHistory()),
    command("simhacli.askAboutSelection", () => actions.attachActiveEditor()),
    command("simhacli.addFileToChat", () => actions.attachActiveEditor()),
    command("simhacli.changeModel", () => actions.changeModel()),
    command("simhacli.changeApproval", () => actions.changeApproval()),
    command("simhacli.setCredentials", () => actions.setCredentials()),
    command("simhacli.revertChanges", () => actions.revertChanges()),
    command("simhacli.restartBackend", () => controller?.restart()),
    command("simhacli.showLogs", () => output.show()),
  );

  void controller.start();
  return { controller, chatView, approvals, actions, window: vscode.window };
}

export async function deactivate(): Promise<void> {
  // Give the backend a chance to shut down cleanly (closes MCP servers)
  await controller?.stop();
  controller = undefined;
}
