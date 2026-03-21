# SimhaCLI MCP Setup Guide

## What is MCP?

**Model Context Protocol (MCP)** allows SimhaCLI to connect to external tools and services like GitHub, databases, deployment platforms, and more. Once configured, the AI agent can use these services automatically.

## Quick Start

1. Get credentials for the service you need (see below)
2. Edit `.simhacli/config.toml` in your project folder
3. Uncomment and configure the MCP server
4. Restart SimhaCLI

## Adding Custom MCP Servers

1. Open `.simhacli/config.toml`
2. Add a new section following one of the patterns:

   **Python (recommended):**

```toml
   [mcp_servers.my_tool]
   command = "uvx"
   args = ["mcp-server-package-name"]
   enabled = true
```

**Node:**

```toml
   [mcp_servers.my_tool]
   command = "npx"
   args = ["-y", "@scope/server-name"]
   enabled = true
```

3. Restart SimhaCLI
4. Browse more MCPs: https://github.com/modelcontextprotocol/servers

**Security:** Your `.simhacli/config.toml` is inside the `.simhacli/` folder which is automatically gitignored. API keys and tokens stored there are safe and will NOT be pushed to GitHub.

---

## Available MCP Servers

### GitHub MCP

Create repos, manage pull requests, issues, and workflows.

**Get your token:**

1. Go to https://github.com/settings/tokens
2. Click "Generate new token (classic)"
3. Select scopes: `repo`, `workflow`, `gist`
4. Copy the token

**Config:**

```toml
[mcp_servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
env = { GITHUB_PERSONAL_ACCESS_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" }
enabled = true
```

---

### PostgreSQL MCP

Query and manage PostgreSQL databases directly.

**Get your connection string:**

- Local: `postgresql://user:password@localhost:5432/mydb`
- Cloud (e.g., Supabase): Find in your project settings under "Database"

**Config:**

```toml
[mcp_servers.postgresql]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-postgres"]
env = { DATABASE_URL = "postgresql://postgres:password@db.abcdef.supabase.co:5432/postgres" }
enabled = true
```

---

### Supabase MCP

Manage Supabase projects, databases, edge functions, and auth.

**Get your keys:**

1. Go to https://supabase.com/dashboard
2. Select your project
3. Go to Settings → API
4. Copy the Project URL, anon key, and service role key

**Config:**

```toml
[mcp_servers.supabase]
command = "npx"
args = [
  "-y",
  "@supabase/mcp-server-supabase",
  "--access-token", "sbp_xxxxxxxxxxxx",
  "--project-ref", "abcdefghijklmnop"
]
enabled = true
```

---

### Vercel Deployment

Deploy applications to Vercel using CLI (no MCP required).

**Setup:**

```bash
npm install -g vercel
vercel login
```

When prompted, provide your Vercel token from: https://vercel.com/account/tokens

---

### Playwright MCP

Browser automation and end-to-end testing.

**No credentials needed.**

**Config:**

```toml
[mcp_servers.playwright]
command = "npx"
args = ["-y", "@playwright/mcp"]
```

---

### Sequential Thinking MCP

Provides an explicit reasoning scratchpad for complex multi-step tasks. The agent can break down problems, think step-by-step, and maintain a persistent thought process.

**No credentials needed.**

**Config:**

```toml
[mcp_servers.sequential_thinking]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-sequentialthinking"]
enabled = true
```

---

### Memory MCP

Persists a knowledge graph across sessions — stores project conventions, your preferences, recurring patterns, and decisions made. The agent can remember and recall information across different conversations.

**No credentials needed.**

**Config:**

```toml
[mcp_servers.memory]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-memory"]
enabled = true
```

**Optional:** Pin where the knowledge graph file lives on disk:

```toml
env = { MEMORY_FILE_PATH = "D:/mine/SimhaCLI/.simhacli/memory.json" }
```

---

### Fetch MCP

Lets the agent pull live documentation, READMEs, API references, and Stack Overflow answers during a task. Useful for looking up current information without leaving the conversation.

**No credentials needed.**

**Config:**

```toml
[mcp_servers.fetch]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-fetch"]
enabled = true
```

**Optional tuning:**

```toml
env = {
  FETCH_MAX_RESPONSE_SIZE = "512000",   # bytes, default 5MB — trim for speed
  FETCH_TIMEOUT_MS = "10000"            # 10s timeout per request
}
```

---

## Using MCPs with SimhaCLI

Once configured, just ask the AI agent in natural language. It will use the appropriate MCP automatically:

| What you say                          | What happens                                      |
| ------------------------------------- | ------------------------------------------------- |
| "Create a GitHub repo for my project" | Uses GitHub MCP to create repo                    |
| "Push my changes"                     | Uses git to commit and push                       |
| "Set up the database"                 | Uses PostgreSQL/Supabase MCP                      |
| "Deploy to Vercel"                    | Uses Vercel MCP to deploy                         |
| "Run tests on my app"                 | Uses Playwright MCP for E2E tests                 |
| "Deploy my full stack app"            | Runs full pipeline (GitHub → DB → Deploy → Tests) |

### Workflow Tool Actions

You can also use the workflow tool directly:

Just ask in natural language:

- "Create a GitHub repo for my project"
- "Push my changes"
- "Deploy to Vercel"
- "Set up the database"

OR

```bash
# Full stack deployment
{"action": "fullstack", "repo_name": "my-app", "db_name": "myapp_db", "project_path": "./my-app"}

# Individual actions
{"action": "github", "repo_name": "my-app"}
{"action": "push", "project_path": "./my-app", "commit_message": "Add feature"}
{"action": "install_deps", "project_path": "./my-app"}
{"action": "env_setup", "project_path": "./my-app", "env_vars": {"API_KEY": "xxx"}}
{"action": "build", "project_path": "./my-app"}
{"action": "readme", "project_path": "./my-app"}
{"action": "database", "db_name": "myapp_db"}
{"action": "deploy", "project_path": "./my-app"}
{"action": "tests", "test_url": "https://my-app.vercel.app"}
```

---

## Manual Setup (If MCP Not Available)

If you prefer not to use MCP or need to set up manually:

### GitHub (Manual)

```bash
git init
git remote add origin https://github.com/USERNAME/REPO.git
git add -A
git commit -m "Initial commit"
git push -u origin main
```

### Database (Manual)

```bash
psql "postgresql://user:pass@host:5432/dbname" -c "CREATE DATABASE mydb;"
```

### Vercel (Manual)

```bash
npm i -g vercel
vercel login
cd your-project
vercel --yes
```

### Playwright (Manual)

```bash
npm i -g @playwright/mcp
npx @playwright/mcp
```

---

## Troubleshooting

### MCP server not connecting

- Check that credentials are correct
- Ensure `enabled = true` is set
- Restart SimhaCLI after changes
- Check `hook.log` for errors

### "GitHub MCP server not connected"

- Add your `GITHUB_PERSONAL_ACCESS_TOKEN` to the config
- Uncomment the `[mcp_servers.github]` section
- Ensure the token has `repo` scope

### "No database MCP server connected"

- Add PostgreSQL or Supabase MCP config
- Ensure your connection string is valid
- Check database server is accessible

### "Vercel deployment failed"

- Set up Vercel MCP (recommended, see above)
- Or install CLI: `npm i -g vercel` then `vercel login`

---

## Security Best Practices

1. **Never commit credentials** - `.simhacli/` is gitignored automatically
2. **Use fine-grained tokens** - Limit scopes to only what's needed
3. **Rotate tokens regularly** - Especially if shared or compromised
4. **Don't share config files** - They contain your real keys
5. **Use environment variables** - For CI/CD, set keys via env vars instead

---

## File Structure

```
your-project/
├── .gitignore           # Auto-created, includes .simhacli/
├── .simhacli/
│   └── config.toml      # MCP configs and project settings (gitignored)
├── src/
└── ...
```
