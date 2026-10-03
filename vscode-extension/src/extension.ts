import * as vscode from "vscode";

import { ChatActions } from "./actions";
import { ApprovalCoordinator } from "./approvals";
import { ChatPositionManager } from "./chatPosition";
import { ChatViewProvider } from "./chatViewProvider";
import { SimhaCodeActionProvider } from "./codeActions";
import { BackendController } from "./controller";
import { DiffContentProvider } from "./diffs";
import { EditorTracker } from "./editorTracker";

let controller: BackendController | undefined;

const SHOWN_KEY = "simhacli.chatShownOnce";

/** Returned from activate(); used by integration tests, not a public API. */
export interface SimhaCliExtensionApi {
  controller: BackendController;
  chatView: ChatViewProvider;
  approvals: ApprovalCoordinator;
  actions: ChatActions;
  editors: EditorTracker;
  position: ChatPositionManager;
  statusItem: vscode.StatusBarItem;
  /** This extension's `vscode.window`, so tests can answer its dialogs. */
  window: typeof vscode.window;
}

export function activate(context: vscode.ExtensionContext): SimhaCliExtensionApi {
  const output = vscode.window.createOutputChannel("SimhaCLI");
  const version = String(context.extension.packageJSON.version ?? "0.0.0");

  controller = new BackendController(output, version);
  const editors = new EditorTracker();
  const chatView = new ChatViewProvider(context.extensionUri, controller, output, editors);
  const approvals = new ApprovalCoordinator(chatView);
  const diffs = new DiffContentProvider();
  const actions = new ChatActions(controller, chatView, approvals, diffs);
  chatView.connect(actions, approvals);
  controller.setApprovalHandler(approvals.handle);
  const position = new ChatPositionManager(context.globalState, ChatViewProvider.viewId);

  const command = (id: string, run: () => unknown) => vscode.commands.registerCommand(id, run);
  context.subscriptions.push(
    output,
    controller,
    position,
    editors,
    chatView,
    diffs,
    vscode.languages.registerCodeActionsProvider(
      [{ scheme: "file" }, { scheme: "untitled" }],
      new SimhaCodeActionProvider(),
      SimhaCodeActionProvider.metadata,
    ),
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
    command("simhacli.openChat", () => vscode.commands.executeCommand(`${ChatViewProvider.viewId}.focus`)),
    command("simhacli.newChat", () => actions.newChat()),
    command("simhacli.history", () => actions.showHistory()),
    command("simhacli.askAboutSelection", () => actions.askWithSelection("modify")),
    vscode.commands.registerCommand("simhacli.modifySelection", (uri?: vscode.Uri, range?: vscode.Range) =>
      actions.askWithSelection("modify", uri, range),
    ),
    vscode.commands.registerCommand("simhacli.reviewSelection", (uri?: vscode.Uri, range?: vscode.Range) =>
      actions.askWithSelection("review", uri, range),
    ),
    vscode.commands.registerCommand("simhacli.explainSelection", (uri?: vscode.Uri, range?: vscode.Range) =>
      actions.askWithSelection("explain", uri, range),
    ),
    command("simhacli.addFileToChat", () => actions.attachActiveEditor()),
    command("simhacli.changeModel", () => actions.changeModel()),
    command("simhacli.changeApproval", () => actions.changeApproval()),
    command("simhacli.setCredentials", () => actions.setCredentials()),
    command("simhacli.revertChanges", () => actions.revertChanges()),
    command("simhacli.moveChatLeft", () => position.choose("left")),
    command("simhacli.moveChatRight", () => position.choose("right")),
    command("simhacli.restartBackend", () => controller?.restart()),
    command("simhacli.showLogs", () => output.show()),
  );

  // Always-visible entry point (the chat may be in a closed side bar)
  const statusItem = vscode.window.createStatusBarItem("simhacli.open", vscode.StatusBarAlignment.Right, 100);
  statusItem.name = "SimhaCLI";
  statusItem.text = "$(sparkle) SimhaCLI";
  statusItem.tooltip = "Open the SimhaCLI chat";
  statusItem.command = "simhacli.openChat";
  statusItem.show();
  context.subscriptions.push(statusItem);

  void (async () => {
    await position.apply();
    // Show the chat once after install, so people can find it on the right
    if (!context.globalState.get<boolean>(SHOWN_KEY)) {
      await context.globalState.update(SHOWN_KEY, true);
      await vscode.commands.executeCommand(`${ChatViewProvider.viewId}.focus`);
    }
  })();
  return { controller, chatView, approvals, actions, editors, position, statusItem, window: vscode.window };
}

export async function deactivate(): Promise<void> {
  // Give the backend a chance to shut down cleanly (closes MCP servers)
  await controller?.stop();
  controller = undefined;
}
