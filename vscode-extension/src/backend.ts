// Runs `simhacli serve` and speaks its newline-delimited JSON protocol.
// Deliberately free of the `vscode` API so it can be tested from plain Node.

import { ChildProcessWithoutNullStreams, spawn } from "child_process";
import * as readline from "readline";

import type {
  MethodName,
  Methods,
  NotificationMessage,
  RequestMessage,
  ResponseMessage,
  RpcError,
} from "./protocol";

export interface BackendOptions {
  command: string;
  /** Arguments placed before `serve` (e.g. a script path for `python3`). */
  args: string[];
  cwd: string;
  env?: NodeJS.ProcessEnv;
  /** Receives the server's stderr lines and protocol diagnostics. */
  log: (line: string) => void;
  /** Receives only the server's stderr lines. */
  stderr?: (line: string) => void;
}

export interface BackendExit {
  code: number | null;
  signal: NodeJS.Signals | null;
  /** Set when the process could not be started (e.g. command not found). */
  error?: string;
  /** True when the exit was requested through `stop()`. */
  expected: boolean;
}

/** An error response from the server, or the backend going away. */
export class BackendError extends Error {
  constructor(
    message: string,
    readonly code?: number,
  ) {
    super(message);
    this.name = "BackendError";
  }
}

type Listener<T> = (value: T) => void;

const EXIT_GRACE_MS = 150;

/** Quote an argument for cmd.exe (only used for .cmd/.bat commands on Windows). */
export function quoteForCmd(arg: string): string {
  return /[\s"&|<>^()%!]/.test(arg) ? `"${arg.replace(/"/g, '""')}"` : arg;
}
type RequestHandler = (method: string, params: unknown) => Promise<unknown>;

interface Pending {
  method: string;
  resolve: (result: unknown) => void;
  reject: (error: Error) => void;
}

export class Backend {
  private proc: ChildProcessWithoutNullStreams | undefined;
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  private readonly notificationListeners = new Set<
    (method: string, params: unknown) => void
  >();
  private readonly exitListeners = new Set<Listener<BackendExit>>();
  private requestHandler: RequestHandler | undefined;
  private stopping = false;
  private exited = false;
  private markExitHandled!: () => void;
  /** Resolves once the exit has been fully processed (listeners notified). */
  private readonly exitHandled = new Promise<void>((resolve) => (this.markExitHandled = resolve));

  constructor(private readonly options: BackendOptions) {}

  get running(): boolean {
    return this.proc !== undefined && !this.exited;
  }

  start(): void {
    if (this.proc) {
      throw new Error("Backend already started");
    }
    const { command, args, cwd, env, log } = this.options;
    const fullArgs = [...args, "serve", "--cwd", cwd];
    log(`Starting: ${command} ${fullArgs.join(" ")}`);

    // Windows can only run .cmd/.bat files through the shell
    const viaShell = process.platform === "win32" && /\.(cmd|bat)$/i.test(command);
    const proc = spawn(viaShell ? quoteForCmd(command) : command, viaShell ? fullArgs.map(quoteForCmd) : fullArgs, {
      cwd,
      env: { ...process.env, ...env, PYTHONUNBUFFERED: "1" },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      shell: viaShell,
    });
    this.proc = proc;

    readline
      .createInterface({ input: proc.stdout })
      .on("line", (line) => this.handleLine(line));
    readline
      .createInterface({ input: proc.stderr })
      .on("line", (line) => {
        log(line);
        this.options.stderr?.(line);
      });

    // Writing after the process died raises EPIPE asynchronously
    proc.stdin.on("error", (error) => log(`stdin error: ${error.message}`));

    proc.on("error", (error: NodeJS.ErrnoException) => {
      const message =
        error.code === "ENOENT"
          ? `Command not found: ${command}`
          : `Could not start ${command}: ${error.message}`;
      this.handleExit({ code: null, signal: null, error: message, expected: false });
    });
    proc.on("exit", (code, signal) => {
      // Give stderr a moment to deliver its last lines (used to explain the exit)
      setTimeout(() => this.handleExit({ code, signal, expected: this.stopping }), EXIT_GRACE_MS);
    });
  }

  /** Send a request and resolve with its result (rejects with BackendError). */
  request<M extends MethodName>(
    method: M,
    params: Methods[M][0],
  ): Promise<Methods[M][1]> {
    if (!this.running) {
      return Promise.reject(new BackendError("SimhaCLI backend is not running"));
    }
    const id = this.nextId++;
    return new Promise<Methods[M][1]>((resolve, reject) => {
      this.pending.set(id, {
        method,
        resolve: resolve as (result: unknown) => void,
        reject,
      });
      this.write({ id, method, params } satisfies RequestMessage);
    });
  }

  /** Listen for server notifications. Returns an unsubscribe function. */
  onNotification(listener: (method: string, params: unknown) => void): () => void {
    this.notificationListeners.add(listener);
    return () => this.notificationListeners.delete(listener);
  }

  /** Listen for the process exiting. Returns an unsubscribe function. */
  onExit(listener: Listener<BackendExit>): () => void {
    this.exitListeners.add(listener);
    return () => this.exitListeners.delete(listener);
  }

  /** Answer server-initiated requests (e.g. `approval/request`). */
  setRequestHandler(handler: RequestHandler): void {
    this.requestHandler = handler;
  }

  /** Ask the server to shut down; kill it if it doesn't exit in time. */
  async stop(timeoutMs = 5000): Promise<void> {
    const proc = this.proc;
    if (!proc || this.exited) {
      return;
    }
    this.stopping = true;
    const timeout = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

    await Promise.race([this.request("shutdown", {}).catch(() => undefined), timeout(timeoutMs)]);
    proc.stdin.end();
    await Promise.race([this.exitHandled, timeout(timeoutMs)]);
    if (!this.exited && proc.exitCode === null && proc.signalCode === null) {
      proc.kill();
    }
    await Promise.race([this.exitHandled, timeout(1000 + EXIT_GRACE_MS)]);
  }

  // -------------------------------------------------------------------------

  private write(message: RequestMessage | ResponseMessage): void {
    if (!this.proc || this.exited) {
      return;
    }
    this.proc.stdin.write(JSON.stringify(message) + "\n");
  }

  private handleLine(line: string): void {
    if (!line.trim()) {
      return;
    }
    let message: Record<string, unknown>;
    try {
      message = JSON.parse(line);
    } catch {
      this.options.log(`Ignoring non-JSON output: ${line}`);
      return;
    }
    if (typeof message !== "object" || message === null) {
      return;
    }

    const hasId = message.id !== undefined && message.id !== null;
    if (typeof message.method === "string") {
      if (hasId) {
        void this.answerRequest(message as unknown as RequestMessage);
      } else {
        const note = message as unknown as NotificationMessage;
        for (const listener of this.notificationListeners) {
          listener(note.method, note.params);
        }
      }
      return;
    }

    const response = message as unknown as ResponseMessage;
    const pending =
      typeof response.id === "number" ? this.pending.get(response.id) : undefined;
    if (!pending) {
      if (response.error) {
        this.options.log(`Server error: ${response.error.message}`);
      }
      return;
    }
    this.pending.delete(response.id as number);
    if (response.error) {
      const error: RpcError = response.error;
      pending.reject(new BackendError(error.message, error.code));
    } else {
      pending.resolve(response.result);
    }
  }

  private async answerRequest(request: RequestMessage): Promise<void> {
    if (!this.requestHandler) {
      this.write({
        id: request.id,
        error: { code: -32601, message: `Client can't handle ${request.method}` },
      });
      return;
    }
    try {
      const result = await this.requestHandler(request.method, request.params);
      this.write({ id: request.id, result });
    } catch (error) {
      this.write({
        id: request.id,
        error: { code: -32000, message: error instanceof Error ? error.message : String(error) },
      });
    }
  }

  private handleExit(exit: BackendExit): void {
    if (this.exited) {
      return;
    }
    this.exited = true;
    const reason = exit.error ?? `SimhaCLI backend exited (code ${exit.code ?? exit.signal})`;
    for (const pending of this.pending.values()) {
      pending.reject(new BackendError(reason));
    }
    this.pending.clear();
    this.options.log(
      exit.error ?? `Backend exited with ${exit.signal ? `signal ${exit.signal}` : `code ${exit.code}`}`,
    );
    for (const listener of this.exitListeners) {
      listener(exit);
    }
    this.markExitHandled();
  }
}
