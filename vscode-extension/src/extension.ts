import * as vscode from "vscode";

import { ChatViewProvider } from "./chatViewProvider";
import { BackendController } from "./controller";

let controller: BackendController | undefined;

/** Returned from activate(); used by integration tests, not a public API. */
export interface SimhaCliExtensionApi {
  controller: BackendController;
  chatView: ChatViewProvider;
}

export function activate(context: vscode.ExtensionContext): SimhaCliExtensionApi {
  const output = vscode.window.createOutputChannel("SimhaCLI");
  const version = String(context.extension.packageJSON.version ?? "0.0.0");

  controller = new BackendController(output, version);
  const chatView = new ChatViewProvider(context.extensionUri, controller, output);

  context.subscriptions.push(
    output,
    controller,
    chatView,
    vscode.window.registerWebviewViewProvider(ChatViewProvider.viewId, chatView, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
    vscode.commands.registerCommand("simhacli.restartBackend", () => controller?.restart()),
    vscode.commands.registerCommand("simhacli.showLogs", () => output.show()),
  );

  void controller.start();
  return { controller, chatView };
}

export async function deactivate(): Promise<void> {
  // Give the backend a chance to shut down cleanly (closes MCP servers)
  await controller?.stop();
  controller = undefined;
}
