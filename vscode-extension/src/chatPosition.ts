// Keeps the chat on the side the user chose (setting simhacli.chatPosition):
// "right" = Secondary Side Bar (the chat's home in package.json), "left" =
// the Activity Bar container. Users can also drag the chat themselves; this
// only moves it when the setting changes.

import * as vscode from "vscode";

export type ChatPosition = "right" | "left";

const CONTAINERS: Record<ChatPosition, string> = {
  right: "workbench.view.extension.simhacli-right",
  left: "workbench.view.extension.simhacli",
};
const APPLIED_KEY = "simhacli.appliedChatPosition";

export class ChatPositionManager implements vscode.Disposable {
  private readonly listener: vscode.Disposable;

  constructor(
    private readonly state: vscode.Memento,
    private readonly viewId: string,
  ) {
    this.listener = vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("simhacli.chatPosition")) {
        void this.apply(true);
      }
    });
  }

  get setting(): ChatPosition {
    return vscode.workspace.getConfiguration("simhacli").get<string>("chatPosition") === "left" ? "left" : "right";
  }

  /** Move the chat if the setting differs from where we last put it. */
  async apply(reveal = false): Promise<void> {
    const wanted = this.setting;
    if (this.state.get<ChatPosition>(APPLIED_KEY, "right") === wanted) {
      return;
    }
    await vscode.commands.executeCommand("vscode.moveViews", {
      viewIds: [this.viewId],
      destinationId: CONTAINERS[wanted],
    });
    await this.state.update(APPLIED_KEY, wanted);
    if (reveal) {
      await vscode.commands.executeCommand(`${this.viewId}.focus`);
    }
  }

  /** Commands "Move Chat to the Left/Right Side Bar": persist the choice. */
  async choose(position: ChatPosition): Promise<void> {
    if (this.setting === position) {
      // Setting unchanged (e.g. the user dragged the chat away): move it back anyway
      await this.state.update(APPLIED_KEY, position === "left" ? "right" : "left");
      await this.apply(true);
      return;
    }
    await vscode.workspace
      .getConfiguration("simhacli")
      .update("chatPosition", position, vscode.ConfigurationTarget.Global);
  }

  dispose(): void {
    this.listener.dispose();
  }
}
