# Workflow Orchestration for SimhaCLI

## Overview

The workflow system enables end-to-end application development by orchestrating multiple MCP servers and tools in a single workflow.

## Available Workflows

### `fullstack`

Complete application development workflow:

1. **Create GitHub Repository** (GitHub MCP)
   - Creates a new repository with specified name and description
   - Configures public/private visibility

2. **Setup PostgreSQL Database** (PostgreSQL MCP)
   - Creates a new database
   - Optionally applies SQL schema

3. **Deploy to Vercel** (Vercel CLI/MCP)
   - Deploys the application
   - Returns deployment URL

4. **Run Playwright Tests** (Playwright MCP)
   - Runs end-to-end tests against deployed app
   - Supports custom test scenarios

## Usage

### Via CLI Command

```bash
# Show available workflows
/workflow

# Run fullstack workflow
/workflow fullstack my-app myapp_db ./my-app

# With optional parameters
/workflow fullstack my-app myapp_db ./my-app --description "My awesome app" --private --test-url https://my-app.vercel.app
```

### Via Tool Call (AI Agent)

The AI agent can invoke the workflow tool directly:

```json
{
  "workflow": "fullstack",
  "repo_name": "my-app",
  "db_name": "myapp_db",
  "project_path": "./my-app",
  "repo_description": "My awesome application",
  "repo_private": false,
  "db_schema": "CREATE TABLE users (id SERIAL PRIMARY KEY, name VARCHAR(100));",
  "test_url": "https://my-app.vercel.app",
  "test_scenarios": [
    {
      "name": "page_loads",
      "action": "goto",
      "url": "https://my-app.vercel.app"
    },
    { "name": "title_check", "action": "get_title" }
  ]
}
```

## MCP Server Configuration

Enable the required MCP servers in `.simhacli/config.toml`:

```toml
[mcp_servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
enabled = true  # Set GITHUB_PERSONAL_ACCESS_TOKEN env var

[mcp_servers.postgres]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-postgres"]
enabled = true  # Set DATABASE_URL env var

[mcp_servers.playwright]
command = "npx"
args = ["-y", "@executeautomation/playwright-mcp-server"]
enabled = true
```

### Environment Variables

```bash
# Required for GitHub MCP
export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_xxxxxxxxxxxx

# Required for PostgreSQL MCP
export DATABASE_URL=postgresql://user:password@localhost:5432/dbname
```

## Architecture

```
tools/workflow/
├── __init__.py
├── engine.py        # Core workflow engine
├── steps.py         # Generic workflow steps
├── fullstack.py     # Fullstack workflow definition
├── workflow_tool.py # Tool interface for workflows
└── README.md
```

### Components

1. **WorkflowEngine** - Manages and executes workflows
2. **WorkflowStep** - Base class for individual steps
3. **MCPToolStep** - Generic MCP tool invocation step
4. **ShellCommandStep** - Shell command execution step
5. **WorkflowTool** - Tool interface for the AI agent

## Adding New Workflows

1. Create a new step class in `steps.py` or a new file
2. Define the workflow in a new file or extend `fullstack.py`
3. Register the workflow in `workflow_tool.py`

Example:

```python
class MyCustomStep(WorkflowStep):
    async def execute(self, context: dict[str, Any]) -> WorkflowStepResult:
        # Your step logic here
        pass

def create_my_workflow() -> Workflow:
    workflow = Workflow(name="my_workflow", description="My custom workflow")
    workflow.add_step(MyCustomStep())
    return workflow
```
