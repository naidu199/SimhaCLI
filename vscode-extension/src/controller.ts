// Owns the `simhacli serve` process for this VS Code window: starts it for the
// first workspace folder, restarts it when settings change, and turns protocol
// traffic into events for the chat panel.

import * as os from "os";
import * as vscode from "vscode";

import { askApproval } from "./approvals";
import { Backend, BackendError, BackendExit } from "./backend";
import {
  AgentEventParams,
  ApprovalRequestParams,
  PROTOCOL_VERSION,
  ServerLogParams,
  TurnFinishedParams,
} from "./protocol";
import { expandVariables } from "./variables";
import type { PanelState } from "./webviewMessages";

const INSTALL_HINT =
  "Install SimhaCLI (pip install simhacli) or set the simhacli.command setting to its full path.";

export class BackendController implements vscode.Disposable {
  private backend: Backend | undefined;
  private state: PanelState = { status: "starting" };
  private readonly disposables: vscode.Disposable[] = [];

  private readonly stateEmitter = new vscode.EventEmitter<PanelState>();
  private readonly agentEventEmitter = new vscode.EventEmitter<AgentEventParams>();
  private readonly turnFinishedEmitter = new vscode.EventEmitter<TurnFinishedParams>();
  readonly onDidChangeState = this.stateEmitter.event;
  readonly onAgentEvent = this.agentEventEmitter.event;
  readonly onTurnFinished = this.turnFinishedEmitter.event;

  constructor(
    private readonly output: vscode.OutputChannel,
    private readonly clientVersion: string,
  ) {
    this.disposables.push(
      this.stateEmitter,
      this.agentEventEmitter,
      this.turnFinishedEmitter,
      vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration("simhacli.command") || e.affectsConfiguration("simhacli.args")) {
          void this.restart();
        }
      }),
      vscode.workspace.onDidChangeWorkspaceFolders(() => void this.restart()),
    );
  }

  get currentState(): PanelState {
    return this.state;
  }

  async start(): Promise<void> {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder || folder.uri.scheme !== "file") {
      this.setState({
        status: "noWorkspace",
        detail: "Open a folder to use SimhaCLI. The agent works inside that folder.",
      });
      return;
    }

    const settings = vscode.workspace.getConfiguration("simhacli");
    const cwd = folder.uri.fsPath;
    const variables = { workspaceFolder: cwd, userHome: os.homedir() };
    const backend = new Backend({
      command: expandVariables(settings.get<string>("command", "simhacli").trim() || "simhacli", variables),
      args: settings.get<string[]>("args", []).map((arg) => expandVariables(arg, variables)),
      cwd,
      log: (line) => this.output.appendLine(line),
    });
    this.backend = backend;

    backend.onNotification((method, params) => this.handleNotification(method, params));
    backend.onExit((exit) => this.handleExit(backend, exit));
    backend.setRequestHandler(async (method, params) => {
      if (method === "approval/request") {
        return { approved: await askApproval(params as ApprovalRequestParams) };
      }
      throw new Error(`Unsupported request: ${method}`);
    });

    this.setState({ status: "starting", detail: "Starting SimhaCLI…" });
    try {
      backend.start();
      const info = await backend.request("initialize", {
        cwd,
        clientName: "vscode",
        clientVersion: this.clientVersion,
        protocolVersion: PROTOCOL_VERSION,
      });
      if (this.backend !== backend) {
        return; // restarted meanwhile
      }
      this.output.appendLine(
        `Connected to SimhaCLI ${info.serverVersion} (model ${info.model}, approval ${info.approval})`,
      );
      this.setState({
        status: "ready",
        model: info.model,
        approval: info.approval,
        cwd: info.cwd,
        needsCredentials: info.needsCredentials,
        detail:
          info.protocolVersion !== PROTOCOL_VERSION
            ? `SimhaCLI speaks protocol v${info.protocolVersion}; this extension expects v${PROTOCOL_VERSION}. Update both to the same version.`
            : undefined,
      });
    } catch (error) {
      if (this.backend === backend) {
        this.output.appendLine(`Initialize failed: ${errorMessage(error)}`);
        // The exit handler reports a dead process; this covers a live one
        if (backend.running) {
          this.setState({ status: "stopped", detail: errorMessage(error) });
        }
      }
    }
  }

  async stop(): Promise<void> {
    const backend = this.backend;
    this.backend = undefined;
    await backend?.stop();
  }

  async restart(): Promise<void> {
    await this.stop();
    await this.start();
  }

  /** Start a turn. Resolves with its id; rejects with a user-facing error. */
  async send(text: string): Promise<string> {
    const backend = this.backend;
    if (!backend || this.state.status !== "ready") {
      throw new BackendError(this.state.detail ?? "SimhaCLI is not ready yet");
    }
    const { turnId } = await backend.request("chat/send", { text });
    this.setState({ ...this.state, turnId });
    return turnId;
  }

  async cancel(): Promise<void> {
    const turnId = this.state.turnId;
    if (this.backend && turnId) {
      await this.backend.request("chat/cancel", { turnId });
    }
  }

  dispose(): void {
    void this.stop();
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
  }

  // -------------------------------------------------------------------------

  private setState(state: PanelState): void {
    this.state = state;
    this.stateEmitter.fire(state);
  }

  private handleNotification(method: string, params: unknown): void {
    switch (method) {
      case "agent/event":
        this.agentEventEmitter.fire(params as AgentEventParams);
        break;
      case "turn/finished": {
        const finished = params as TurnFinishedParams;
        if (this.state.turnId === finished.turnId) {
          this.setState({ ...this.state, turnId: undefined });
        }
        this.turnFinishedEmitter.fire(finished);
        break;
      }
      case "server/log": {
        const log = params as ServerLogParams;
        this.output.appendLine(`[${log.level}] ${log.message}`);
        break;
      }
    }
  }

  private handleExit(backend: Backend, exit: BackendExit): void {
    if (this.backend !== backend) {
      return; // an old instance we already replaced
    }
    this.backend = undefined;
    if (exit.expected) {
      return;
    }
    const detail = exit.error
      ? `${exit.error}. ${INSTALL_HINT}`
      : `SimhaCLI stopped unexpectedly (exit code ${exit.code ?? exit.signal}).`;
    this.setState({ status: "stopped", detail });

    void vscode.window
      .showWarningMessage(detail, "Restart", "Show Logs")
      .then((choice) => {
        if (choice === "Restart") {
          void this.restart();
        } else if (choice === "Show Logs") {
          this.output.show();
        }
      });
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
