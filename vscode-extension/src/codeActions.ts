// "Modify / Review / Explain with SimhaCLI" in the editor's code-action menu
// (the lightbulb or ✨ menu next to a selection, and Cmd+. / Ctrl+.). They are
// grouped under "Rewrite", next to other AI actions such as Copilot's.

import * as vscode from "vscode";

export type SelectionIntent = "modify" | "review" | "explain";

export const SELECTION_COMMANDS: Record<SelectionIntent, { command: string; title: string }> = {
  modify: { command: "simhacli.modifySelection", title: "Modify with SimhaCLI" },
  review: { command: "simhacli.reviewSelection", title: "Review with SimhaCLI" },
  explain: { command: "simhacli.explainSelection", title: "Explain with SimhaCLI" },
};

export class SimhaCodeActionProvider implements vscode.CodeActionProvider {
  static readonly kind = vscode.CodeActionKind.RefactorRewrite.append("simhacli");
  static readonly metadata: vscode.CodeActionProviderMetadata = {
    providedCodeActionKinds: [SimhaCodeActionProvider.kind],
  };

  provideCodeActions(document: vscode.TextDocument, range: vscode.Range | vscode.Selection): vscode.CodeAction[] {
    if (range.isEmpty) {
      return [];
    }
    return (Object.keys(SELECTION_COMMANDS) as SelectionIntent[]).map((intent) => {
      const { command, title } = SELECTION_COMMANDS[intent];
      const action = new vscode.CodeAction(title, SimhaCodeActionProvider.kind);
      action.command = { command, title, arguments: [document.uri, range] };
      return action;
    });
  }
}
