<div align="center">

# 🦁 SimhaCLI

### AI-Powered Coding Agent for Your Terminal

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

_Built by Narasimha Naidu Korrapti_

[Features](#-features) • [Installation](#-installation)

</div>

---

## 📖 Overview

**SimhaCLI** is a powerful terminal-based AI coding agent that brings the intelligence of Large Language Models directly into your development workflow. It seamlessly integrates with your codebase, understands context, and executes actions through a comprehensive set of builtin tools.

### Why SimhaCLI?

- 🚀 **Session-Based Architecture**: Persistent context and memory across interactions
- 🛠️ **11 Builtin Tools**: File operations, shell commands, web access, task management
- 🔒 **Safety First**: Shell command blocking prevents dangerous operations
- 💾 **Persistent Memory**: Remember user preferences and context
- 🎨 **Beautiful TUI**: Rich terminal interface with syntax highlighting
- ⚡ **Streaming Responses**: Real-time output as the agent thinks
- 🔄 **Event-Driven**: Observable agent actions with full transparency

---

## ✨ Features

### 🤖 Intelligent Agent

- **Agentic Loop**: Autonomous multi-turn conversations with tool usage
- **Context Management**: Tracks conversation history with token counting
- **Turn Tracking**: Session-based state management with UUIDs
- **Streaming Output**: Real-time response generation

### 🛠️ Comprehensive Toolset

11 builtin tools across 5 categories:

- **📖 Read**: `read_file`, `list_dir`, `glob`, `grep`
- **✏️ Write**: `write_file`, `edit_file`
- **🖥️ Shell**: `shell` (with 40+ blocked dangerous commands)
- **🌐 Web**: `web_search`, `web_fetch`
- **💾 Memory**: `todos` (task management), `memory` (persistent storage)

### 🔒 Safety & Security

- Command blocking for dangerous operations (rm -rf, format, etc.)
- Timeout protection on shell commands (120s default, 600s max)
- File validation and error handling
- Configurable working directory restrictions

### 💾 Persistent Storage

- **User Memory**: JSON-based key-value storage (`~/.simhacli/user_memory.json`)
- **Configuration**: System and project-level TOML configs
- **Session Tracking**: UUID-based session management with timestamps

### 🎨 Rich Terminal UI

- Syntax-highlighted code display
- Color-coded tool execution (cyan=read, yellow=write, white=shell)
- Live streaming text output
- Beautiful welcome banner and formatting
- Error panels with detailed information

---

## 🚀 Installation

### Prerequisites

- **Python 3.10+**
- **API Key** (OpenAI, Gemini, or compatible API)

### Option 1: Install from PyPI (Recommended)

```bash
pip install simhacli
```

After installation, you can run SimhaCLI from anywhere:

```bash
simhacli                    # Start interactive mode
simhacli "explain this code" # Run a single prompt
simhacli --help             # Show help
```

### Option 2: Install from Source

1. **Clone the repository**

   ```bash
   git clone https://github.com/naidu199/SimhaCLI.git
   cd SimhaCLI
   ```

2. **Install globally (access from anywhere)**

   ```bash
   pip install -e .
   ```

   Or install without editable mode:

   ```bash
   pip install .
   ```

3. **Now you can use `simhacli` from anywhere:**

   ```bash
   simhacli                    # Start interactive mode
   simhacli "your prompt"       # Run a single command
   simhacli --cwd /path/to/dir  # Set working directory
   ```

### Option 3: Development Setup

1. **Clone and create virtual environment**

   ```bash
   git clone https://github.com/naidu199/SimhaCLI.git
   cd SimhaCLI
   python -m venv venv

   # Windows
   venv\Scripts\activate

   # Linux/Mac
   source venv/bin/activate
   ```

2. **Install in editable mode**

   ```bash
   pip install -e .
   ```

3. **Run SimhaCLI**

   ```bash
   simhacli
   ```

### Configuration

Set up your API credentials using one of these methods:

**Method 1: Environment Variables**

```bash
# Windows (PowerShell)
$env:API_KEY = "your_api_key_here"
$env:API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# Windows (CMD)
set API_KEY=your_api_key_here
set API_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai

# Linux/Mac
export API_KEY=your_api_key_here
export API_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
```

**Method 2: Config File**

```bash
# Create config directory
mkdir -p ~/.simhacli

# Create/edit config.toml
```

---
