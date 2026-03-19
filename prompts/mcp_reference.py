"""MCP Server setup reference - loaded on-demand when workflow tool needs it."""

MCP_SETUP_REFERENCE = """## MCP Server Setup Reference

Config location: `.simhacli/config.toml` (gitignored, safe for API keys)

### GitHub MCP
```toml
[mcp_servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
env = { GITHUB_PERSONAL_ACCESS_TOKEN = "ghp_xxx" }
```
Token: https://github.com/settings/tokens (scopes: repo, workflow, gist)

### PostgreSQL MCP
```toml
[mcp_servers.postgresql]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-postgres"]
env = { DATABASE_URL = "postgresql://user:pass@host:5432/db" }
```

### Supabase MCP
```toml
[mcp_servers.supabase]
command = "npx"
args = ["-y", "@supabase/mcp-server-supabase", "--access-token", "sbp_xxx", "--project-ref", "abc123"]
```
Access token: https://supabase.com/dashboard → Account → Access Tokens

### Vercel (CLI)
```bash
npm install -g vercel && vercel login
```
Token: https://vercel.com/account/tokens

### Playwright MCP
```toml
[mcp_servers.playwright]
command = "npx"
args = ["-y", "@playwright/mcp"]
```

Restart SimhaCLI after configuring any MCP server."""


def get_mcp_setup_reference() -> str:
    """Return MCP setup reference docs."""
    return MCP_SETUP_REFERENCE
