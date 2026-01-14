<div align="center">

# 🦁 SimhaCLI

### AI-Powered Coding Agent for Your Terminal

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

_Built by Narasimha Naidu Korrapti_

[Features](#-features) • [Installation](#-installation) • [Usage](#-usage) • [Tools](#-builtin-tools) • [Architecture](#-architecture) • [Documentation](#-documentation)

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
- **OpenAI API Key** (or compatible API)

### Steps

1. **Clone the repository**

   ```bash
   git clone https://github.com/naidu199/SimhaCLI.git
   cd SimhaCLI
   ```

2. **Create virtual environment**

   ```bash
   python -m venv venv

   # Windows
   venv\Scripts\activate

   # Linux/Mac
   source venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**

   ```bash
   # Windows
   set API_KEY=your_api_key_here
   set API_BASE_URL=https://api.openai.com/v1

   # Linux/Mac
   export API_KEY=your_api_key_here
   export API_BASE_URL=https://api.openai.com/v1
   ```

5. **Configure (Optional)**
   ```bash
   # Create system config
   mkdir -p ~/.simhacli
   # Edit ~/.simhacli/config.toml
   ```

---
