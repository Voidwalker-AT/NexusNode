# NexusNode CLI

![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)
![Zero Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)

Universal remote command-line client for NexusNode Mobile Server Appliance. Connects to any NexusNode server over HTTPS. No server source code required.

## Installation

```bash
pip install nexusnode-cli
```

## Quick Start

```bash
nexus connect https://your-nexusnode.example
```
You will be prompted for your username and password, after which you'll enter the interactive `nexus>` shell.

> **Windows Note:** If `nexus` is not immediately recognized in an already-open terminal after installation, open a fresh PowerShell/CMD window or run `nexus setup` (or `python -m nexus connect ...`).

## Features

- **Interactive REPL** with tab completion
- **Full RBAC-aware** command set
- **JSON output mode** (`--json`)
- **ANSI color terminal output** (`--no-color` to disable)
- **System status monitoring**
- **Vault file management** (list, upload, download, checksums)
- **Media download queue management**
- **AI model management and chat**
- **RAG document search**
- **Task lifecycle tracking**
- **Service supervision**
- **User administration**
- **Backup management**
- **Automation job scheduling**
- **Server diagnostics**
- **Log streaming**
- **Temporary share link management**
- **Settings configuration**
- **Database inspection**

## Command Reference

The following commands are available within the interactive shell or as single commands:

- `connect` - Connect to a NexusNode server
- `disconnect` - Disconnect from the current server
- `session` - Manage the current session
- `login` / `logout` - Authentication
- `whoami` - Show current user information
- `shell` - Enter the interactive REPL
- `status` - Show system status
- `vault` - Manage vault files
- `media` - Manage media queues
- `tasks` - Manage running tasks
- `ai` - Chat with AI models
- `rag` - Search RAG documents
- `shares` - Manage temporary share links
- `services` - Manage background services
- `models` - Manage AI models
- `diagnostics` - Run system diagnostics
- `logs` - View system logs
- `users` - Manage system users
- `backups` - Manage server backups
- `automation` - Schedule automation jobs
- `settings` - Configure server settings
- `database` - Inspect database contents

## Global Options

- `--server` - Specify the server URL
- `--user` - Specify the username
- `--json` - Output raw JSON responses
- `--no-color` - Disable ANSI color output
- `--debug` - Enable debug logging
- `--version` - Show package version

## Security Model

- **HTTPS only**: All connections are encrypted.
- **Token-based auth**: Secure session tokens are used after login.
- **No secrets stored**: No sensitive information is hardcoded or stored in the package.
- **RBAC enforcement**: Commands are gated by the server's Role-Based Access Control.

## Platform Support

- Windows
- macOS
- Linux
- Termux (Android)

## Requirements

- Python 3.8+
- Zero external dependencies (uses only Python standard library)

## Links

- [GitHub Repository](https://github.com/Voidwalker-AT/NexusNode)
