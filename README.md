# ⚡ NexusChat

> **A high-performance, cross-platform LAN messenger and secure file sharing application built with Python, Tkinter, and PostgreSQL.**

![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-blue)
![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

---

## 🌟 Key Highlights

* **Professional Branding**: **NexusChat** — clean, modern, and memorable.
* **True Cross-Platform**: Runs natively on **Windows**, **Ubuntu / Linux**, and **macOS**.
* **Zero Client Config**: The client connects purely over TCP. It never touches database credentials or writes cache files to the client machine.
* **Explicit Sign In & Register**:
  * **Sign In Tab**: Fast login for existing users.
  * **Register Tab**: Account creation with **Confirm Password validation** to prevent typos.
* **Built-in Default Admin Account**:
  * Default admin: `admin` / `admin123`.
  * Instantly changeable via CLI: `nexuschat admin reset-password admin <new_password>`.
* **In-App `🛡️ Admin Panel`**:
  * Admins can view user tables, live online/offline badges, toggle roles, reset passwords, kick sessions, and monitor disk storage.
* **LAN Auto-Discovery**: Automatically discovers servers on the local network via UDP beaconing (port `8083`).
* **Binary Packet Framing**: Custom length-prefixed TCP protocol streaming both JSON control messages and 64KB binary file chunks.
* **Unified CLI**: Run client, server, migrations, or admin tools using `nexuschat` (with backward-compatible alias `bahlchat`).

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Client Machine                     │
│  NexusChat UI (Tkinter)                                 │
│  └─ ChatClient (Thread-safe Queue & Socket Worker)     │
└────────────┬───────────────────────────────▲────────────┘
             │ (1) UDP Beacon :8083          │ (2) Framed TCP :8082
             ▼                               ▼
┌─────────────────────────────────────────────────────────┐
│                      Server Machine                     │
│  ChatServer (Multi-threaded Connection Pool)            │
│  ├─ LAN Advertiser Thread (UDP Beacon)                  │
│  ├─ Database Layer ──────► PostgreSQL (Users, Roles,    │
│  │                                     Messages, Files) │
│  └─ Disk File Store ─────► data/files/ (Binary storage) │
└─────────────────────────────────────────────────────────┘
```

### Framing Protocol (TCP :8082)
Every packet contains a 5-byte header:
* `Byte 0`: Frame Type (`0x01` = JSON, `0x02` = Binary Stream)
* `Bytes 1–4`: Payload Length (32-bit unsigned big-endian integer)
* `Payload`: The exact UTF-8 JSON or binary file chunk

---

## 🚀 Quick Start & Installation

### 1. Install as a Python Package

Clone the repository and install in editable mode:

```bash
git clone https://github.com/your-username/nexuschat.git
cd nexuschat
pip install -e .
```

*(On Ubuntu / Debian, ensure Tkinter is installed: `sudo apt install -y python3-tk`)*

---

### 2. Configure Database & Start Server

Run the interactive setup wizard to configure PostgreSQL credentials:

```bash
nexuschat setup-db
```

Then start the chat server daemon:

```bash
nexuschat server
```

*(Options: `nexuschat server --host 0.0.0.0 --port 8082`)*

---

### 3. Start the Chat Client

On any computer connected to the same LAN / Wi-Fi:

```bash
nexuschat client
# or simply:
nexuschat
```

* Click **🔍 Scan Network** to auto-detect the server IP.
* Choose **🔑 Sign In** or **📝 Register New Account**.
* Log in as the default administrator: `admin` / `admin123`.

---

## 🛡️ Administration & User Management

### In-App GUI Admin Panel
If you are logged in as an Admin, a **`🛡️ Admin Panel`** button will appear in your top navigation bar:
* **User Management**: View all accounts, registration timestamps, and live online/offline badges.
* **Password Reset**: Reset forgotten passwords with one click.
* **Role Management**: Promote users to `admin` or demote to `user`.
* **Kick / Delete**: Terminate rogue connections or delete inactive accounts.
* **Server Metrics**: Real-time stats on active users, total messages, stored files, and disk usage.

### Server-Side CLI Admin Tools
The server host can manage accounts directly from the terminal without opening the client:

```bash
# List all registered users
nexuschat admin list-users

# Reset a user's password (e.g. for default admin)
nexuschat admin reset-password admin <new_password>

# Change user role
nexuschat admin set-role alice admin

# Delete a user and their messages
nexuschat admin delete-user bob

# Show server storage & message statistics
nexuschat admin stats

# Open standalone server admin GUI
nexuschat admin ui
```

---

## 🛠️ Project Management & Release Automation (`manage.py`)

A centralized automation tool is provided in the project root:

### 1. Build Desktop Standalone Executables
```bash
python manage.py build --client
```
* Generates standalone binary for your OS (`NexusChat.exe` on Windows or `NexusChat` on Linux/macOS).
* Automatically produces a ready-to-share portable archive: `dist/NexusChat-windows.zip` or `dist/NexusChat-linux.tar.gz`.

### 2. Build PyPI Distribution (Wheel & Source)
```bash
python manage.py build --pypi
```
* Compiles `nexuschat-1.0.0.tar.gz` and `nexuschat-1.0.0-py3-none-any.whl` into `dist/`.

### 3. Publish to PyPI
```bash
# Upload to TestPyPI:
python manage.py publish --pypi --test

# Upload to Official Production PyPI:
python manage.py publish --pypi
```

### 4. Version Management & Release Notes Creation
```bash
# Check version synchronization status across tracked files
python manage.py version

# Bump version (major, minor, or patch) and create release notes template
python manage.py version --bump patch

# Manually generate/verify release notes in docs/release_notes/
python manage.py release-notes
```

### 5. Automated GitHub Releases via GitHub Actions
When a version tag is pushed (e.g. `v1.0.0`), the GitHub Actions workflow (`.github/workflows/release.yml`) automatically:
1. Builds PyPI source distributions (`.tar.gz` & `.whl`).
2. Builds standalone Windows (`.zip`) and Linux (`.tar.gz`) client packages.
3. Extracts release notes from `docs/release_notes/RELEASE_NOTES_V<VERSION>.md`.
4. Creates a official GitHub Release attaching all binary packages and changelog notes.

```bash
git tag v1.0.0
git push origin v1.0.0
```

### 6. Clean Workspace Artifacts
```bash
python manage.py clean
```
* Removes all temporary builds, `dist/`, `build/`, `*.egg-info`, and `__pycache__` artifacts.

---

## 🔒 Security & Best Practices

1. **Password Security**: All user passwords are salted and hashed with **bcrypt**. Plaintext passwords are never stored.
2. **Default Admin**: Change the default admin password on production servers:
   ```bash
   nexuschat admin reset-password admin <new_secure_password>
   ```
3. **Path Traversal Protection**: Uploaded file names are strictly sanitized (`shared.files.safe_filename`) to prevent directory traversal attacks.
4. **Database Isolation**: Clients never open direct database connections. Only the server interacts with PostgreSQL.
5. **Firewall Rules**: If a firewall is active on the server machine, permit:
   * **TCP Port `8082`** (Chat & File Streaming)
   * **UDP Port `8083`** (LAN Beacon Discovery)

---

## 📄 License
MIT License. Feel free to use, modify, and distribute.
