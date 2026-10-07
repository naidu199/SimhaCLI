// Expands ${workspaceFolder} and ${userHome} in the simhacli.command / simhacli.args
// settings (VS Code doesn't substitute variables in extension settings).

export interface VariableValues {
  workspaceFolder: string;
  userHome: string;
}

export function expandVariables(value: string, values: VariableValues): string {
  return value
    .replace(/\$\{workspaceFolder\}/g, values.workspaceFolder)
    .replace(/\$\{userHome\}/g, values.userHome);
}
