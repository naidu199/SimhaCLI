// Shows proposed file changes in VS Code's diff editor, using in-memory
// documents (scheme `simhacli-diff`) for the before/after contents.

import * as path from "path";
import * as vscode from "vscode";

import type { FileChange } from "./protocol";

export const DIFF_SCHEME = "simhacli-diff";

export class DiffContentProvider implements vscode.TextDocumentContentProvider, vscode.Disposable {
  private readonly contents = new Map<string, string>();
  private nextId = 1;
  private readonly registration: vscode.Disposable;

  constructor() {
    this.registration = vscode.workspace.registerTextDocumentContentProvider(DIFF_SCHEME, this);
  }

  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.contents.get(uri.query) ?? "";
  }

  /** Open a side-by-side diff of a proposed change. */
  async open(change: FileChange): Promise<void> {
    const name = path.basename(change.path);
    const before = this.store(change.path, "before", change.oldContent);
    const after = this.store(change.path, "after", change.newContent);
    const title = change.isNewFile
      ? `${name} (new file, proposed by SimhaCLI)`
      : `${name} (current ↔ proposed by SimhaCLI)`;
    await vscode.commands.executeCommand("vscode.diff", before, after, title, { preview: true });
  }

  dispose(): void {
    this.registration.dispose();
    this.contents.clear();
  }

  private store(filePath: string, side: string, content: string): vscode.Uri {
    const key = `${this.nextId++}`;
    this.contents.set(key, content);
    // Keep the real file name so the editor picks the right language
    return vscode.Uri.from({ scheme: DIFF_SCHEME, path: `/${side}/${path.basename(filePath)}`, query: key });
  }
}
