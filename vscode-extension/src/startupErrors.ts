// Turns a backend exit (plus its last stderr lines) into a message that says
// what went wrong and how to fix it. Free of the `vscode` API so it can be
// unit-tested.

import type { BackendExit } from "./backend";

export const INSTALL_HINT =
  "Install SimhaCLI (pip install simhacli) or set the simhacli.command setting to its full path.";

const UPDATE_HINT =
  "Update it with `pip install -U simhacli`, or point the simhacli.command setting at a newer install.";

function lastMeaningfulLine(lines: string[]): string | undefined {
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim();
    if (line && !/^(Traceback|File "|\^+$|During handling)/.test(line)) {
      return line;
    }
  }
  return undefined;
}

export function explainExit(exit: BackendExit, stderr: string[], wasReady: boolean): string {
  if (exit.error) {
    return `${exit.error}. ${INSTALL_HINT}`;
  }
  const text = stderr.join("\n");

  if (/No such command ['"]?serve['"]?/i.test(text)) {
    return `Your SimhaCLI is too old for the VS Code extension: it has no \`simhacli serve\` command. ${UPDATE_HINT}`;
  }
  const missingModule = text.match(/ModuleNotFoundError: No module named ['"]([^'"]+)['"]/);
  if (missingModule) {
    return (
      `SimhaCLI couldn't start: the Python module '${missingModule[1]}' is missing. ` +
      "Reinstall SimhaCLI in the Python environment that simhacli.command uses (`pip install -U simhacli`)."
    );
  }
  if (/permission denied/i.test(text)) {
    return `SimhaCLI couldn't start: permission denied. Check that simhacli.command points to an executable file.`;
  }

  const code = exit.signal ? `signal ${exit.signal}` : `exit code ${exit.code}`;
  const line = lastMeaningfulLine(stderr);
  const reason = line && !/[.!?]$/.test(line) ? `${line}.` : line;
  if (!wasReady) {
    return `SimhaCLI exited while starting (${code})${reason ? `: ${reason}` : "."} Show Logs has the details.`;
  }
  return `SimhaCLI stopped unexpectedly (${code})${reason ? `: ${reason}` : "."}`;
}
