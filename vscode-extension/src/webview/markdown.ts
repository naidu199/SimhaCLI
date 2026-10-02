// Markdown rendering for assistant replies.
// Raw HTML in model output is NOT rendered (html: false), and markdown-it
// rejects javascript:/vbscript:/data: links, so replies can't inject markup.

import hljs from "highlight.js/lib/common";
import MarkdownIt from "markdown-it";

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function highlight(code: string, language: string): string {
  const lang = language.trim().split(/\s+/)[0]?.toLowerCase() ?? "";
  try {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
    }
  } catch {
    // fall through to plain text
  }
  return escapeHtml(code);
}

const md = new MarkdownIt({ html: false, linkify: true, breaks: false });

// Fenced code blocks get a header with the language and a Copy button
md.renderer.rules.fence = (tokens, index) => {
  const token = tokens[index];
  const language = token.info.trim().split(/\s+/)[0] ?? "";
  const label = language ? escapeHtml(language) : "code";
  return (
    `<div class="code-block"><div class="code-header"><span>${label}</span>` +
    `<button type="button" class="code-copy" title="Copy code">Copy</button></div>` +
    `<pre><code class="hljs">${highlight(token.content, language)}</code></pre></div>`
  );
};

// Open links through the extension (the webview can't navigate)
const defaultLinkOpen =
  md.renderer.rules.link_open ?? ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options));
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet("data-href", tokens[idx].attrGet("href") ?? "");
  tokens[idx].attrSet("title", tokens[idx].attrGet("href") ?? "");
  return defaultLinkOpen(tokens, idx, options, env, self);
};

export function renderMarkdown(text: string): string {
  return md.render(text);
}
