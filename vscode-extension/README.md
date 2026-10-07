# SimhaCLI for VS Code

Chat with the [SimhaCLI](https://github.com/naidu199/SimhaCLI) AI coding agent from the VS Code side bar. It's the same agent as the `simhacli` terminal app, with the same tools, approvals, saved chats, models and API key. It reads, edits and runs code in your workspace, and asks before anything risky.

## Requirements

- **VS Code 1.106 or newer.**
- **SimhaCLI with the `simhacli serve` command.** Check with `simhacli serve --help`. Older versions don't have it; update with `pip install -U simhacli`.
- **An API key** for any OpenAI-compatible provider (OpenRouter, OpenAI, …). If none is configured, the chat asks for one.
- **A trusted folder.** The extension is disabled in Restricted Mode, because the agent can edit files and run commands.

## Getting started

1. Open a folder in VS Code.
2. Click **✦ SimhaCLI** in the status bar, or run **SimhaCLI: Open Chat**. The chat opens on the right (the Secondary Side Bar).
3. Ask something, for example *"Explain how this project is organised"*.

## Features

- **Chat** with streamed replies, Markdown and highlighted code (with a Copy button), the model's thinking (collapsed), and each tool call as a row you can expand.
- **Your selection, automatically.** Select code in the editor and it shows up in the message box (e.g. `app.py:33-46 · 14 lines`) and is sent with your next message, including unsaved edits. Click the chip to leave it out. With no selection, click the file chip to send the whole file.
- **Modify / Review / Explain with SimhaCLI** in the editor's code-action menu (the 💡 or ✨ next to a selection, or **Cmd+.** / **Ctrl+.**) and in the **SimhaCLI** right-click submenu.
- **Approvals** as cards in the chat: Approve, Deny, or **View diff** in VS Code's diff editor before deciding.
- **Approval modes** from the chip under the message box, colour-coded by how much the agent may do on its own (green: Always ask / Never run, blue: Ask, orange: Auto-approve, red: YOLO).
- **Revert** the files changed by the latest reply.
- **Chat history** inside the panel: every chat is saved automatically (shared with the `simhacli` terminal app), grouped by date and searchable.
- **Attach any file** with the paperclip.
- **Left or right**: the chat starts on the right; move it with **SimhaCLI: Move Chat to the Left Side Bar** or the `simhacli.chatPosition` setting, or drag it.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `simhacli.command` | `simhacli` | Command that starts SimhaCLI. Use a full path for a virtualenv install. |
| `simhacli.args` | `[]` | Extra arguments placed before `serve`. |
| `simhacli.chatPosition` | `right` | `right` (Secondary Side Bar) or `left` (Activity Bar). |

`${workspaceFolder}` and `${userHome}` are expanded in `simhacli.command` and `simhacli.args`.

**SimhaCLI in a virtualenv:**

```json
{ "simhacli.command": "${workspaceFolder}/.venv/bin/simhacli" }
```

On Windows: `"${workspaceFolder}\\.venv\\Scripts\\simhacli.exe"`.

**SimhaCLI from a source checkout:**

```json
{
  "simhacli.command": "python3",
  "simhacli.args": ["/path/to/SimhaCLI/main.py"]
}
```

The model, approval policy, MCP servers and API key come from SimhaCLI's own configuration (`.simhacli/config.toml` in your project, plus your global SimhaCLI config), so the terminal app and the extension stay in sync. You can also change the model, approval mode and API key from the chat.

## Troubleshooting

The chat explains start-up problems and offers **Restart backend** and **Show logs**:

| Message | Fix |
|---|---|
| *Command not found: simhacli* | Install SimhaCLI, or set `simhacli.command` to its full path. |
| *Your SimhaCLI is too old for the VS Code extension* | `pip install -U simhacli`, or point `simhacli.command` at a newer install. |
| *the Python module '…' is missing* | Reinstall SimhaCLI in the Python environment that `simhacli.command` uses. |
| *Add an API key to start chatting* | Click **Set API key**, or run **SimhaCLI: Set API Key and Provider**. |
| *Open a folder to use SimhaCLI* | The agent works inside a folder; open one first. |

**SimhaCLI: Show Logs** opens the backend's output.

## Privacy and safety

The agent runs on your machine. Your messages, attached files and selections, and tool results are sent to the model provider you configured. Commands and file changes follow your approval mode. In the default **Ask** mode, SimhaCLI asks before running commands that aren't read-only and before risky file changes.

## License

MIT. See [LICENSE](LICENSE). Third-party software and icons are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
