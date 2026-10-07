// Follows the active editor and its selection, so the chat panel can show
// (and send) what the user is looking at without any extra clicks.

import * as vscode from "vscode";

import type { Attachment } from "./protocol";
import type { EditorContextUse, PanelEditorContext } from "./webviewMessages";

const SCHEMES = new Set(["file", "untitled"]);
const DEBOUNCE_MS = 120;

/** 1-based inclusive line range of a selection (a trailing column-0 line is excluded). */
export function selectionLines(selection: vscode.Range): { start: number; end: number } {
  const start = selection.start.line + 1;
  const end =
    selection.end.character === 0 && selection.end.line > selection.start.line
      ? selection.end.line
      : selection.end.line + 1;
  return { start, end };
}

function fileLabel(document: vscode.TextDocument): string {
  return document.isUntitled ? document.fileName : vscode.workspace.asRelativePath(document.uri, false);
}

export function rangeLabel(document: vscode.TextDocument, range: vscode.Range): string {
  const { start, end } = selectionLines(range);
  return start === end ? `${fileLabel(document)}:${start}` : `${fileLabel(document)}:${start}-${end}`;
}

/** Attachment for a range of a document, using the editor's (possibly unsaved) text. */
export function rangeAttachment(document: vscode.TextDocument, range: vscode.Range): Attachment {
  const { start, end } = selectionLines(range);
  const full = new vscode.Range(start - 1, 0, end - 1, document.lineAt(end - 1).text.length);
  return { path: document.uri.fsPath, startLine: start, endLine: end, content: document.getText(full) + "\n" };
}

/** Attachment for a whole document (sends the text only when it has unsaved edits). */
export function fileAttachment(document: vscode.TextDocument): Attachment {
  return document.isDirty || document.isUntitled
    ? { path: document.uri.fsPath, content: document.getText() }
    : { path: document.uri.fsPath };
}

export class EditorTracker implements vscode.Disposable {
  private editor: vscode.TextEditor | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private readonly disposables: vscode.Disposable[] = [];
  private readonly emitter = new vscode.EventEmitter<PanelEditorContext | null>();
  /** Fires (debounced) when the tracked file or selection changes. */
  readonly onDidChange = this.emitter.event;

  constructor() {
    const active = vscode.window.activeTextEditor;
    this.track(active && SCHEMES.has(active.document.uri.scheme) ? active : undefined);
    this.disposables.push(
      this.emitter,
      vscode.window.onDidChangeActiveTextEditor((editor) => {
        if (editor && SCHEMES.has(editor.document.uri.scheme)) {
          this.track(editor);
        } else if (this.editor && !vscode.window.visibleTextEditors.includes(this.editor)) {
          // Focus moved elsewhere (chat panel, output, …): keep the last file
          // editor while it's still on screen
          this.track(undefined);
        }
      }),
      vscode.window.onDidChangeTextEditorSelection((event) => {
        const editor = event.textEditor;
        if (SCHEMES.has(editor.document.uri.scheme) && (editor === this.editor || editor === vscode.window.activeTextEditor)) {
          this.track(editor);
        }
      }),
      vscode.workspace.onDidCloseTextDocument((document) => {
        if (this.editor?.document === document) {
          this.track(undefined);
        }
      }),
    );
  }

  /** The editor context as shown in the panel, or null when there's no file. */
  get current(): PanelEditorContext | null {
    const editor = this.editor;
    if (!editor || editor.document.isClosed) {
      return null;
    }
    const document = editor.document;
    const selection = editor.selection;
    const hasSelection = !selection.isEmpty;
    const { start, end } = selectionLines(selection);
    return {
      fileLabel: fileLabel(document),
      label: hasSelection ? rangeLabel(document, selection) : fileLabel(document),
      hasSelection,
      lineCount: hasSelection ? end - start + 1 : 0,
    };
  }

  /** Attachment to send for the requested use, read fresh from the editor. */
  attachment(use: EditorContextUse | undefined): Attachment | undefined {
    const editor = this.editor;
    if (!editor || editor.document.isClosed || !use || use === "none") {
      return undefined;
    }
    if (use === "selection" && !editor.selection.isEmpty) {
      return rangeAttachment(editor.document, editor.selection);
    }
    return use === "file" ? fileAttachment(editor.document) : undefined;
  }

  dispose(): void {
    if (this.timer) clearTimeout(this.timer);
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
  }

  private track(editor: vscode.TextEditor | undefined): void {
    this.editor = editor;
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.emitter.fire(this.current), DEBOUNCE_MS);
  }
}
