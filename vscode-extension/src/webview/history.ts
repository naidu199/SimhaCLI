// The in-panel chat history list: grouped by date, searchable, with delete.

import type { SessionSummary } from "../protocol";
import { button, el } from "./dom";
import { icons } from "./icons";

export interface HistoryCallbacks {
  open(session: SessionSummary): void;
  remove(session: SessionSummary): void;
}

export function relativeTime(iso: string, now = Date.now()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const minutes = Math.round((now - then) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function groupName(iso: string, now = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Older";
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = 24 * 60 * 60 * 1000;
  const time = date.getTime();
  if (time >= startOfToday) return "Today";
  if (time >= startOfToday - day) return "Yesterday";
  if (time >= startOfToday - 7 * day) return "Previous 7 days";
  return "Older";
}

function item(session: SessionSummary, callbacks: HistoryCallbacks): HTMLElement {
  const row = el("div", `history-item${session.isCurrent ? " current" : ""}`);
  row.setAttribute("role", "listitem");

  const open = el("button", "history-open");
  open.type = "button";
  open.title = session.title ?? "";
  const title = el("span", "history-item-title");
  title.append(el("span", "history-item-text", session.title ?? "Untitled chat"));
  const meta = el("span", "history-item-meta");
  const parts = [relativeTime(session.updatedAt), `${session.messageCount} message${session.messageCount === 1 ? "" : "s"}`];
  if (session.source && session.source !== "cli" && session.source !== "vscode") parts.push(session.source);
  meta.textContent = parts.filter(Boolean).join(" · ");
  open.append(title, meta);
  if (session.isCurrent) {
    title.append(el("span", "badge", "Current"));
  }
  open.addEventListener("click", () => callbacks.open(session));
  row.append(open);

  if (!session.isCurrent) {
    const remove = button("", "icon-button history-delete", () => {
      // Inline confirmation instead of a dialog
      const confirm = el("div", "history-confirm");
      confirm.append(
        el("span", "", "Delete this chat?"),
        button("Delete", "danger small", () => callbacks.remove(session)),
        button("Cancel", "secondary small", () => confirm.replaceWith(remove)),
      );
      remove.replaceWith(confirm);
    });
    remove.innerHTML = icons.trash();
    remove.title = "Delete chat";
    remove.setAttribute("aria-label", `Delete ${session.title ?? "chat"}`);
    row.append(remove);
  }
  return row;
}

export function renderHistory(
  list: HTMLElement,
  sessions: SessionSummary[],
  query: string,
  callbacks: HistoryCallbacks,
): void {
  list.replaceChildren();
  const needle = query.trim().toLowerCase();
  const shown = needle
    ? sessions.filter((s) => (s.title ?? "").toLowerCase().includes(needle))
    : sessions;

  if (shown.length === 0) {
    list.append(el("div", "history-empty", needle ? "No chats match your search." : "No saved chats yet."));
    return;
  }

  let currentGroup = "";
  for (const session of shown) {
    const group = groupName(session.updatedAt);
    if (group !== currentGroup) {
      currentGroup = group;
      list.append(el("div", "history-group", group));
    }
    list.append(item(session, callbacks));
  }
}
