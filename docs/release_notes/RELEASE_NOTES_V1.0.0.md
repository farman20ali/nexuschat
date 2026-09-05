# NexusChat v1.0.0 Release Notes

Welcome to the initial release of **NexusChat v1.0.0** — a high-performance, cross-platform LAN messenger and secure file sharing application built with Python Tkinter and supported by a PostgreSQL backend.

---

## 🌟 Highlights & Key Features

- 💬 **Real-time Messaging**: Multi-room chat, private direct messaging, and instant broadcast support across local networks.
- 📁 **Fast File Transfers**: Direct peer-to-peer file sharing with progress tracking and integrity checks.
- 🔒 **End-to-End Security**: User authentication powered by `bcrypt` password hashing and secure token sessions.
- 🗄️ **PostgreSQL Integration**: Persistent message archives, user credentials, and room management.
- 🎨 **Modern Tkinter UI**: Lightweight, responsive desktop client interface compatible with Windows, Linux, and macOS.
- 🛠️ **CLI & Developer Automation**: Full-featured `manage.py` automation tool for database initialization, version bumping, PyPI packaging, and client binary compilation.

---

## 📦 Downloads & Installation

### Option 1: Standalone Client Executable
Download the pre-compiled standalone binary archive for your OS from the **Assets** section below:
- **Windows**: `NexusChat-windows.zip`
- **Linux**: `NexusChat-linux.tar.gz`

Extract the package and run `NexusChat.exe` (Windows) or `./NexusChat` (Linux).

### Option 2: Installed via Pip
```bash
pip install nexuschat
```

Run client or server directly from terminal:
```bash
nexuschat client
nexuschat server
```

---

## 📋 Changelog (v1.0.0)

### Initial Release
- Initial project structure with `nexuschat`, `client`, `server`, and `shared` modules.
- Added `manage.py` unified CLI for environment setup, packaging, version sync, and execution.
- Added automated CI and GitHub Actions release packaging workflows.

---

*For bug reports and feedback, please submit an issue on the repository issue tracker.*
