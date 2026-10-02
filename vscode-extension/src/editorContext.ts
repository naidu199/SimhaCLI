// Turns the active editor (file or selection) into a chat attachment.

import * as vscode from "vscode";

import type { PanelAttachment } from "./webviewMessages";

export type EditorAttachmentResult =
  | { attachment: PanelAttachment; unsaved: boolean }
  | { error: string };

export function activeEditorAttachment(): EditorAttachmentResult {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    return { error: "Open a file in the editor first." };
  }
  const document = editor.document;
  if (document.isUntitled || document.uri.scheme !== "file") {
    return { error: "Save the file first. SimhaCLI reads attached files from disk." };
  }

  const relative = vscode.workspace.asRelativePath(document.uri, false);
  const selection = editor.selection;
  if (selection.isEmpty) {
    return {
      attachment: { path: document.uri.fsPath, label: relative },
      unsaved: document.isDirty,
    };
  }

  const startLine = selection.start.line + 1;
  // A selection ending at column 0 doesn't include that last line
  const endLine =
    selection.end.character === 0 && selection.end.line > selection.start.line
      ? selection.end.line
      : selection.end.line + 1;
  return {
    attachment: {
      path: document.uri.fsPath,
      startLine,
      endLine,
      label: startLine === endLine ? `${relative}:${startLine}` : `${relative}:${startLine}-${endLine}`,
    },
    unsaved: document.isDirty,
  };
}
