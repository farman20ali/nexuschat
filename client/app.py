import sys
import threading
import time
import webbrowser
from pathlib import Path
from queue import Empty
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client.chat_client import ChatClient
from client.theme import (
    ACCENT,
    ACCENT_BG,
    ACCENT_DARK,
    BG,
    BG_CARD,
    BG_INPUT,
    BG_RAISED,
    BG_SIDEBAR,
    BORDER,
    BORDER_SUBTLE,
    DANGER,
    FG,
    FG_MUTED,
    FG_SUBTLE,
    GOLD,
    OK,
    ONLINE,
    PURPLE,
    apply_theme,
    ui_font,
)
from shared.constants import DISCOVERY_PORT, EVERYONE, TCP_PORT
from shared.discovery import find_servers, local_ip


class ChatApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("⚡ NexusChat")
        self.geometry("560x650")
        self.minsize(500, 560)
        apply_theme(self)

        self.client = ChatClient()
        self._files = []
        self._admin_window = None
        self._file_explorer = None

        self.login = LoginFrame(self, self)
        self.chat = ChatFrame(self, self)
        self.login.pack(fill=tk.BOTH, expand=True)

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(50, self._drain_events)

    def show_chat(self, username, role, host, port):
        self.login.pack_forget()
        self.geometry("1040x720")
        self.minsize(880, 600)
        self.chat.pack(fill=tk.BOTH, expand=True)
        self.chat.set_session(username, role, host, port)

    def show_login(self, message=None):
        if self._admin_window and self._admin_window.winfo_exists():
            self._admin_window.destroy()
            self._admin_window = None
        if self._file_explorer and self._file_explorer.winfo_exists():
            self._file_explorer.destroy()
            self._file_explorer = None
        self.chat.pack_forget()
        self.geometry("560x650")
        self.minsize(500, 560)
        self.chat.clear()
        self.login.pack(fill=tk.BOTH, expand=True)
        if message:
            self.login.set_status(message, error=True)

    def open_admin_panel(self):
        if self.client.role != "admin":
            messagebox.showerror("Access Denied", "Administrator privileges required.")
            return
        if self._admin_window and self._admin_window.winfo_exists():
            self._admin_window.lift()
            return
        self._admin_window = AdminWindow(self, self)

    def open_file_explorer(self):
        if self._file_explorer and self._file_explorer.winfo_exists():
            self._file_explorer.lift()
            self._file_explorer.populate_files(self._files)
            return
        self._file_explorer = FileExplorerWindow(self, self)
        self._file_explorer.populate_files(self._files)

    def on_close(self):
        try:
            self.client.disconnect()
        except Exception:
            pass
        finally:
            try:
                self.destroy()
            except Exception:
                pass

    def _prompt_required_password_change(self, username):
        messagebox.showwarning(
            "Password Change Required",
            f"Hello @{username}, your password was reset and requires updating.",
            parent=self,
        )
        new_pw = simpledialog.askstring("New Password", "Enter new password (min 4 chars):", show="*", parent=self)
        if not new_pw or len(new_pw) < 4:
            messagebox.showerror("Error", "Password must be at least 4 characters.", parent=self)
            return
        conf_pw = simpledialog.askstring("Confirm Password", "Confirm new password:", show="*", parent=self)
        if new_pw != conf_pw:
            messagebox.showerror("Error", "Passwords do not match.", parent=self)
            return
        messagebox.showinfo("Password Noted", "Password update notice recorded. Contact admin or use recover to update.", parent=self)

    def _drain_events(self):
        try:
            while True:
                try:
                    kind, payload = self.client.events.get_nowait()
                except Empty:
                    break
                try:
                    self._handle_event(kind, payload)
                except Exception:
                    pass
            if self.winfo_exists():
                self.after(50, self._drain_events)
        except Exception:
            pass

    def _handle_event(self, kind, payload):
        if kind == "connected":
            self.show_chat(
                payload["username"],
                payload.get("role", "user"),
                payload["host"],
                payload["port"],
            )
            if payload.get("must_change_password"):
                self.after(500, lambda: self._prompt_required_password_change(payload["username"]))
        elif kind == "auth_fail":
            self.login.set_status(str(payload), error=True)
        elif kind == "disconnected":
            if self.chat.winfo_ismapped():
                self.show_login("Disconnected from server.")
        elif kind == "error":
            if self.chat.winfo_ismapped():
                self.chat.append_system(str(payload))
            else:
                self.login.set_status(str(payload), error=True)
        elif kind == "role_update":
            new_role = str(payload)
            self.client.role = new_role
            self.chat.update_role(new_role)
        elif kind == "user_list":
            users = payload.get("users") or []
            self.chat.set_users(users)
        elif kind == "typing":
            if self.chat.winfo_ismapped():
                self.chat.show_typing(payload.get("sender"), payload.get("recipient"))
        elif kind == "chat":
            self.chat.append_message(payload)
        elif kind == "history":
            self.chat.load_history(payload.get("messages") or [])
        elif kind == "history_deleted":
            room = payload.get("room")
            count = payload.get("count", 0)
            if room in (EVERYONE, "all"):
                self.chat._conversations[EVERYONE] = []
                if self.chat._current_recipient == EVERYONE:
                    self.chat.clear_messages()
                    self.chat.append_system(f"Global #general history was purged ({count} messages removed).")
            elif room:
                self.chat._conversations[room] = []
                if self.chat._current_recipient == room:
                    self.chat.clear_messages()
                    self.chat.append_system(f"Conversation with @{room} was cleared from your chat window ({count} messages).")
            else:
                self.chat._conversations.clear()
                self.chat._conversations[EVERYONE] = []
                self.chat.clear_messages()
                self.chat.append_system(f"Permanently removed {count} stored messages from your history.")
        elif kind == "file_list":
            self._files = payload.get("files") or []
            self.chat.set_files(self._files)
            if self._file_explorer and self._file_explorer.winfo_exists():
                self._file_explorer.populate_files(self._files)
        elif kind == "file_saved":
            self.chat.append_system(f"File successfully saved: {payload}")
        elif kind == "status":
            self.chat.append_system(str(payload))
        elif kind == "admin_users":
            if self._admin_window and self._admin_window.winfo_exists():
                self._admin_window.populate_users(payload.get("users") or [])
        elif kind == "admin_stats":
            if self._admin_window and self._admin_window.winfo_exists():
                self._admin_window.populate_stats(payload.get("stats") or {})
        elif kind == "admin_result":
            if self._admin_window and self._admin_window.winfo_exists():
                self._admin_window.handle_result(payload)


class LoginFrame(ttk.Frame):
    def __init__(self, master, app: ChatApp):
        super().__init__(master, padding=16)
        self.app = app
        self._mode = "login"  # "login" or "register"
        self._servers = []

        # 1. Docked Footer at the very bottom (GUARANTEED VISIBLE)
        footer = ttk.Frame(self)
        footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        self.status = ttk.Label(footer, text=f"Local IP: {local_ip()}", style="Muted.TLabel", wraplength=480)
        self.status.pack(anchor="w")

        # 2. Main content container
        content = ttk.Frame(self)
        content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Header Title
        header = ttk.Frame(content)
        header.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(header, text="⚡ NexusChat", style="Brand.TLabel").pack(anchor="center")
        ttk.Label(
            header,
            text="High-performance LAN messenger & secure file sharing",
            style="Muted.TLabel",
        ).pack(anchor="center", pady=(2, 0))

        # Card Container
        self.card = ttk.Frame(content, style="Card.TFrame", padding=16)
        self.card.pack(fill=tk.X, pady=(0, 10))

        # Mode Selector Buttons (Sign In vs Register Account)
        mode_row = ttk.Frame(self.card, style="Card.TFrame")
        mode_row.pack(fill=tk.X, pady=(0, 12))

        self.btn_mode_login = ttk.Button(
            mode_row,
            text="🔑 Sign In",
            style="Accent.TButton",
            command=lambda: self.switch_mode("login"),
        )
        self.btn_mode_login.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self.btn_mode_reg = ttk.Button(
            mode_row,
            text="📝 Register New Account",
            style="TButton",
            command=lambda: self.switch_mode("register"),
        )
        self.btn_mode_reg.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(4, 0))

        # Username Field
        ttk.Label(self.card, text="Username", style="SidebarMuted.TLabel").pack(anchor="w", pady=(2, 2))
        self.username = ttk.Entry(self.card)
        self.username.pack(fill=tk.X, pady=(0, 6))

        # Password Field
        ttk.Label(self.card, text="Password", style="SidebarMuted.TLabel").pack(anchor="w", pady=(2, 2))
        self.password = ttk.Entry(self.card, show="*")
        self.password.pack(fill=tk.X, pady=(0, 6))

        # Confirm Password Field (only shown in Register mode)
        self.confirm_label = ttk.Label(self.card, text="Confirm Password", style="SidebarMuted.TLabel")
        self.confirm_password = ttk.Entry(self.card, show="*")

        # Network Settings (Server IP & Port)
        net_row = ttk.Frame(self.card, style="Card.TFrame")
        net_row.pack(fill=tk.X, pady=(4, 10))

        ip_col = ttk.Frame(net_row, style="Card.TFrame")
        ip_col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Label(ip_col, text="Server IP", style="SidebarMuted.TLabel").pack(anchor="w")
        self.server_ip = ttk.Entry(ip_col)
        self.server_ip.pack(fill=tk.X, pady=(2, 0))

        port_col = ttk.Frame(net_row, style="Card.TFrame")
        port_col.pack(side=tk.RIGHT, fill=tk.X, padx=(6, 0))
        ttk.Label(port_col, text="Port", style="SidebarMuted.TLabel").pack(anchor="w")
        self.port = ttk.Entry(port_col, width=7)
        self.port.insert(0, str(TCP_PORT))
        self.port.pack(fill=tk.X, pady=(2, 0))

        # Action Button Row
        action_row = ttk.Frame(self.card, style="Card.TFrame")
        action_row.pack(fill=tk.X, pady=(4, 0))

        self.forgot_btn = ttk.Button(
            action_row,
            text="Forgot password?",
            command=self.forgot_password,
        )
        self.forgot_btn.pack(side=tk.LEFT)

        self.submit_btn = ttk.Button(
            action_row,
            text="Sign In ➤",
            style="Accent.TButton",
            command=self.submit,
        )
        self.submit_btn.pack(side=tk.RIGHT)

        # LAN Discovery Card
        discovery_card = ttk.Frame(content, style="Card.TFrame", padding=12)
        discovery_card.pack(fill=tk.BOTH, expand=True)

        disc_header = ttk.Frame(discovery_card, style="Card.TFrame")
        disc_header.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(disc_header, text="📡 LAN Auto-Discovery:", style="SidebarMuted.TLabel").pack(side=tk.LEFT)

        disc_ctrls = ttk.Frame(disc_header, style="Card.TFrame")
        disc_ctrls.pack(side=tk.RIGHT)
        ttk.Label(disc_ctrls, text="Beacon Port:", style="SidebarMuted.TLabel").pack(side=tk.LEFT, padx=(0, 4))
        self.discovery_port = ttk.Entry(disc_ctrls, width=6)
        self.discovery_port.insert(0, str(DISCOVERY_PORT))
        self.discovery_port.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            disc_ctrls,
            text="🔍 Scan Network",
            style="Small.TButton",
            command=self.discover,
        ).pack(side=tk.LEFT)

        self.found = tk.Listbox(
            discovery_card,
            height=3,
            bg=BG_INPUT,
            fg=FG,
            selectbackground=ACCENT,
            selectforeground="#11111b",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=BORDER_SUBTLE,
            font=ui_font(9),
        )
        self.found.pack(fill=tk.BOTH, expand=True)
        self.found.bind("<<ListboxSelect>>", self._pick_server)

    def switch_mode(self, mode):
        self._mode = mode
        if mode == "register":
            self.btn_mode_reg.configure(style="Accent.TButton")
            self.btn_mode_login.configure(style="TButton")
            self.confirm_label.pack(after=self.password, anchor="w", pady=(2, 2))
            self.confirm_password.pack(after=self.confirm_label, fill=tk.X, pady=(0, 6))
            self.submit_btn.configure(text="Create Account ➤")
            self.forgot_btn.pack_forget()
            self.set_status("Register a new account. Passwords must match.")
        else:
            self.btn_mode_login.configure(style="Accent.TButton")
            self.btn_mode_reg.configure(style="TButton")
            self.confirm_label.pack_forget()
            self.confirm_password.pack_forget()
            self.submit_btn.configure(text="Sign In ➤")
            self.forgot_btn.pack(side=tk.LEFT)
            self.set_status(f"Local IP: {local_ip()}")

    def set_status(self, text, error=False):
        self.status.configure(text=text, foreground=DANGER if error else FG_MUTED)

    def forgot_password(self):
        messagebox.showinfo(
            "Password Reset",
            "Passwords are securely encrypted on the server.\n\n"
            "How to recover access:\n"
            "1. Ask any active Admin to reset your password via the 'Admin Panel' inside NexusChat.\n"
            "2. Or the server host can run in their terminal:\n"
            "     nexuschat admin reset-password <username>\n"
            "   (Default server admin is 'admin' / 'admin123')",
            parent=self,
        )

    def discover(self):
        try:
            port = int(self.discovery_port.get().strip() or DISCOVERY_PORT)
        except ValueError:
            port = DISCOVERY_PORT
            self.discovery_port.delete(0, tk.END)
            self.discovery_port.insert(0, str(DISCOVERY_PORT))

        self.set_status(f"Scanning local network on UDP {port} for NexusChat servers...")

        def work():
            try:
                servers = find_servers(discovery_port=port, timeout=1.8)
            except Exception as exc:
                self.after(0, lambda: self.set_status(str(exc), error=True))
                return
            self.after(0, lambda: self._show_servers(servers))

        threading.Thread(target=work, daemon=True).start()

    def _show_servers(self, servers):
        self.found.delete(0, tk.END)
        self._servers = servers
        if not servers:
            self.set_status("No LAN servers responded. You can enter the server IP manually.", error=True)
            return
        for item in servers:
            self.found.insert(
                tk.END,
                f"📡 {item.get('ip')} : {item.get('port')}  ({item.get('host', 'Server')})",
            )
        self.set_status(f"Found {len(servers)} server(s). Select one to auto-fill IP and Port.")

    def _pick_server(self, _event):
        sel = self.found.curselection()
        if not sel or not getattr(self, "_servers", None):
            return
        item = self._servers[sel[0]]
        self.server_ip.delete(0, tk.END)
        self.server_ip.insert(0, item.get("ip") or "")
        self.port.delete(0, tk.END)
        self.port.insert(0, str(item.get("port") or ""))

    def submit(self):
        username = self.username.get().strip()
        password = self.password.get()
        host = self.server_ip.get().strip()
        try:
            port = int(self.port.get().strip())
        except ValueError:
            self.set_status("Port must be a valid number.", error=True)
            return

        if len(username) < 3:
            self.set_status("Username must be at least 3 characters long.", error=True)
            return
        if not password:
            self.set_status("Password cannot be empty.", error=True)
            return
        if not host:
            self.set_status("Server IP address is required.", error=True)
            return

        is_register = self._mode == "register"

        if is_register:
            confirm = self.confirm_password.get()
            if len(password) < 4:
                self.set_status("Password must be at least 4 characters long.", error=True)
                return
            if password != confirm:
                self.set_status("Passwords do not match! Please verify your password.", error=True)
                return
            self.set_status(f"Creating account '@{username}' on {host}:{port}...")
        else:
            self.set_status(f"Signing in as '@{username}' on {host}:{port}...")

        threading.Thread(
            target=self.app.client.connect,
            args=(host, port, username, password, is_register),
            daemon=True,
        ).start()


class ChatFrame(ttk.Frame):
    def __init__(self, master, app: ChatApp):
        super().__init__(master)
        self.app = app
        self._current_recipient = EVERYONE
        self._online_users = []
        self._conversations = {EVERYONE: []}
        self._unread_counts = {}
        self._last_typing_sent = 0.0

        # Paned layout: Sidebar (left) + Main Chat (right)
        self.paned = tk.PanedWindow(
            self,
            orient=tk.HORIZONTAL,
            bg=BORDER_SUBTLE,
            sashwidth=2,
            bd=0,
        )
        self.paned.pack(fill=tk.BOTH, expand=True)

        # Left Sidebar
        self.sidebar = ttk.Frame(self.paned, style="Sidebar.TFrame", padding=10)
        self.paned.add(self.sidebar, minsize=210, width=230)

        # Right Chat Area
        self.main_area = ttk.Frame(self.paned, padding=12)
        self.paned.add(self.main_area, minsize=480)

        self._build_sidebar()
        self._build_main_area()

    def _build_sidebar(self):
        # 1. Profile card docked at the bottom of the sidebar
        self.profile_card = ttk.Frame(self.sidebar, style="Card.TFrame", padding=8)
        self.profile_card.pack(side=tk.BOTTOM, fill=tk.X)

        prof_top = ttk.Frame(self.profile_card, style="Card.TFrame")
        prof_top.pack(fill=tk.X)
        self.prof_name = ttk.Label(prof_top, text="Not signed in", style="Sidebar.TLabel", font=ui_font(10, "bold"))
        self.prof_name.pack(side=tk.LEFT)
        self.prof_role_badge = ttk.Label(prof_top, text="USER", style="AdminBadge.TLabel")
        self.prof_role_badge.pack(side=tk.RIGHT)

        ttk.Button(
            self.profile_card,
            text="Disconnect",
            style="Danger.TButton",
            command=self.disconnect,
        ).pack(fill=tk.X, pady=(6, 0))

        # 2. Sidebar Brand & Channels
        ttk.Label(self.sidebar, text="⚡ NexusChat", style="SidebarTitle.TLabel").pack(anchor="w", pady=(2, 10))

        ttk.Label(self.sidebar, text="CHANNELS", style="Subtle.TLabel").pack(anchor="w", pady=(4, 2))
        self.channel_btn = ttk.Button(
            self.sidebar,
            text="📢 # general (Everyone)",
            command=lambda: self.select_recipient(EVERYONE),
        )
        self.channel_btn.pack(fill=tk.X, pady=(0, 10))

        # 3. Direct Messages Header & Live Search
        self.users_header = ttk.Label(self.sidebar, text="ONLINE USERS (0)", style="Subtle.TLabel")
        self.users_header.pack(anchor="w", pady=(4, 2))

        # Search / Filter Users Entry
        self.user_search = ttk.Entry(self.sidebar)
        self.user_search.insert(0, "🔍 Search users...")
        self.user_search.pack(fill=tk.X, pady=(2, 6))
        self.user_search.bind("<FocusIn>", self._on_user_search_focus_in)
        self.user_search.bind("<FocusOut>", self._on_user_search_focus_out)
        self.user_search.bind("<KeyRelease>", lambda e: self._filter_users())

        # Listbox for Users
        self.user_listbox = tk.Listbox(
            self.sidebar,
            bg=BG_INPUT,
            fg=FG,
            selectbackground=ACCENT,
            selectforeground="#11111b",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=BORDER_SUBTLE,
            font=ui_font(9),
        )
        self.user_listbox.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.user_listbox.bind("<<ListboxSelect>>", self._on_user_pick)

    def _on_user_search_focus_in(self, _event):
        if self.user_search.get() == "🔍 Search users...":
            self.user_search.delete(0, tk.END)

    def _on_user_search_focus_out(self, _event):
        if not self.user_search.get().strip():
            self.user_search.insert(0, "🔍 Search users...")
            self._filter_users()

    def _filter_users(self):
        query = self.user_search.get().strip().lower()
        if query == "🔍 search users...":
            query = ""
        self.user_listbox.delete(0, tk.END)
        matching = [u for u in self._online_users if query in u.lower()] if query else self._online_users
        for u in matching:
            unread = self._unread_counts.get(u, 0)
            badge = f" ({unread} new)" if unread > 0 else ""
            self.user_listbox.insert(tk.END, f"🟢 @{u}{badge}")
        self.users_header.configure(text=f"ONLINE USERS ({len(matching)}/{len(self._online_users)})")

        gen_unread = self._unread_counts.get(EVERYONE, 0)
        if gen_unread > 0 and self._current_recipient != EVERYONE:
            self.channel_btn.configure(text=f"📢 # general ({gen_unread} new)")
        else:
            self.channel_btn.configure(text="📢 # general (Everyone)")

    def _build_main_area(self):
        # 1. Header Bar at Top
        header = ttk.Frame(self.main_area, style="Header.TFrame", padding=10)
        header.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))

        title_box = ttk.Frame(header, style="Header.TFrame")
        title_box.pack(side=tk.LEFT)
        self.chat_title = ttk.Label(title_box, text="📢 # general", style="Title.TLabel")
        self.chat_title.pack(anchor="w")
        self.conn_hint = ttk.Label(title_box, text="Connected", style="SidebarMuted.TLabel")
        self.conn_hint.pack(anchor="w")

        actions_box = ttk.Frame(header, style="Header.TFrame")
        actions_box.pack(side=tk.RIGHT)

        self.admin_btn = ttk.Button(
            actions_box,
            text="🛡️ Admin Panel",
            style="Admin.TButton",
            command=self.app.open_admin_panel,
        )
        # Packed dynamically when role == 'admin'

        ttk.Button(actions_box, text="🔍 Search Room", style="Small.TButton", command=self.toggle_search_bar).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(actions_box, text="📜 History", style="Small.TButton", command=self.load_hist).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(actions_box, text="💾 Export", style="Small.TButton", command=self.export_chat).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(actions_box, text="🧹 Clear", style="Small.TButton", command=self.clear_messages).pack(
            side=tk.LEFT, padx=3
        )
        self.purge_btn = ttk.Button(
            actions_box,
            text="🔒 #general (Admin Only)",
            style="Danger.TButton",
            command=self.delete_hist,
        )
        self.purge_btn.pack(side=tk.LEFT, padx=3)

        # 2. In-Room Message Search Bar (collapsible)
        self.search_frame = ttk.Frame(self.main_area, style="Card.TFrame", padding=6)
        self.search_entry = ttk.Entry(self.search_frame)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.search_entry.bind("<Return>", lambda e: self._find_next())
        self.search_count_lbl = ttk.Label(self.search_frame, text="", style="SidebarMuted.TLabel")
        self.search_count_lbl.pack(side=tk.LEFT, padx=4)
        ttk.Button(self.search_frame, text="Next ↓", style="Small.TButton", command=self._find_next).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(self.search_frame, text="✕", style="Small.TButton", command=self.toggle_search_bar).pack(
            side=tk.LEFT, padx=2
        )

        # 3. DOCKED BOTTOM COMPOSER (GUARANTEED VISIBLE)
        composer = ttk.Frame(self.main_area)
        composer.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))

        # Status & Typing Indicator
        status_row = ttk.Frame(composer)
        status_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 2))
        self.typing_label = ttk.Label(status_row, text="", style="SidebarMuted.TLabel")
        self.typing_label.pack(side=tk.LEFT)

        # Composer Buttons Row
        comp_actions = ttk.Frame(composer)
        comp_actions.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))
        ttk.Button(comp_actions, text="📎 Attach File", command=self.send_file).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(comp_actions, text="🗜️ Attach Zip", command=self.send_zip).pack(side=tk.LEFT)

        ttk.Button(
            comp_actions,
            text="Send  (Ctrl+Enter) ➤",
            style="Accent.TButton",
            command=self.send,
        ).pack(side=tk.RIGHT)

        # Composer Text Entry
        self.entry = scrolledtext.ScrolledText(
            composer,
            wrap=tk.WORD,
            height=3,
            bg=BG_INPUT,
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=BORDER_SUBTLE,
            font=ui_font(10),
            padx=8,
            pady=6,
        )
        self.entry.pack(fill=tk.X)
        self.entry.bind("<Control-Return>", lambda e: self.send())
        self.entry.bind("<Key>", self._on_key_type)

        # 4. File Bar (above composer)
        file_bar = ttk.Frame(self.main_area, style="Card.TFrame", padding=6)
        file_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))

        ttk.Button(
            file_bar,
            text="📁 Search & Browse All Files 🔍",
            style="Accent.TButton",
            command=self.app.open_file_explorer,
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.files_combo = ttk.Combobox(file_bar, state="readonly", width=30)
        self.files_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(file_bar, text="⬇ Download", style="Small.TButton", command=self.download_file).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(file_bar, text="🗑 Delete", style="Danger.TButton", command=self.delete_file).pack(
            side=tk.LEFT, padx=2
        )

        # 5. Message Area (fills all remaining middle space)
        self.messages = scrolledtext.ScrolledText(
            self.main_area,
            wrap=tk.WORD,
            bg=BG_INPUT,
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=BORDER_SUBTLE,
            font=ui_font(10),
            padx=10,
            pady=10,
        )
        self.messages.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.messages.configure(state=tk.DISABLED)

        # Style tags
        self.messages.tag_configure("user_self", foreground=ACCENT, font=ui_font(10, "bold"))
        self.messages.tag_configure("user_other", foreground=PURPLE, font=ui_font(10, "bold"))
        self.messages.tag_configure("admin_badge", foreground=GOLD, font=ui_font(9, "bold"))
        self.messages.tag_configure("stamp", foreground=FG_SUBTLE, font=ui_font(8))
        self.messages.tag_configure("sys", foreground=FG_MUTED, font=ui_font(9))
        self.messages.tag_configure("file_box", foreground=GOLD, underline=True)
        self.messages.tag_configure("search_match", background="#fab387", foreground="#11111b")
        self.messages.tag_configure("link", foreground=ACCENT, underline=True)
        self.messages.tag_bind("link", "<Button-1>", self._open_link)
        self.messages.tag_bind("file_box", "<Button-1>", self._on_file_click)

    def _on_key_type(self, _event):
        now = time.time()
        if now - self._last_typing_sent > 2.5:
            self._last_typing_sent = now
            self.app.client.send_typing(self._current_recipient)

    def show_typing(self, sender, recipient):
        my_name = self.app.client.username
        if sender == my_name:
            return
        # Display typing if it matches current channel or DM
        if recipient == EVERYONE or recipient == my_name or sender == self._current_recipient:
            self.typing_label.configure(text=f"✏️ @{sender} is typing...")
            self.after(3000, lambda: self.typing_label.configure(text=""))

    def toggle_search_bar(self):
        if self.search_frame.winfo_ismapped():
            self.search_frame.pack_forget()
            self.messages.tag_remove("search_match", "1.0", tk.END)
        else:
            self.search_frame.pack(before=self.messages, fill=tk.X, pady=(0, 6))
            self.search_entry.focus_set()

    def _find_next(self):
        query = self.search_entry.get().strip()
        self.messages.tag_remove("search_match", "1.0", tk.END)
        if not query:
            self.search_count_lbl.configure(text="")
            return
        start = "1.0"
        count = 0
        first_pos = None
        while True:
            pos = self.messages.search(query, start, tk.END, nocase=True)
            if not pos:
                break
            if first_pos is None:
                first_pos = pos
            end_pos = f"{pos}+{len(query)}c"
            self.messages.tag_add("search_match", pos, end_pos)
            count += 1
            start = end_pos
        self.search_count_lbl.configure(text=f"{count} found")
        if first_pos:
            self.messages.see(first_pos)

    def set_session(self, username, role, host, port):
        self.prof_name.configure(text=f"@{username}")
        self.conn_hint.configure(text=f"🟢 Connected to {host}:{port}")
        self.update_role(role)
        self.append_system(f"Welcome, @{username}! Signed in with role [{role.upper()}].")

    def update_role(self, role):
        is_admin = role == "admin"
        self.prof_role_badge.configure(
            text="ADMIN" if is_admin else "USER",
            style="AdminBadge.TLabel" if is_admin else "Muted.TLabel",
        )
        if is_admin:
            self.admin_btn.pack(side=tk.LEFT, padx=(0, 6))
        else:
            self.admin_btn.pack_forget()

        if self._current_recipient == EVERYONE:
            self.purge_btn.configure(
                text="🗑️ Purge #general (Admin)" if is_admin else "🔒 #general (Admin Only)",
                state=tk.NORMAL if is_admin else tk.DISABLED,
            )

    def select_recipient(self, target):
        self._current_recipient = target
        self._unread_counts[target] = 0
        self._filter_users()

        is_admin = self.app.client.role == "admin"
        if target == EVERYONE:
            self.chat_title.configure(text="📢 # general (Global Chat)")
            self.purge_btn.configure(
                text="🗑️ Purge #general (Admin)" if is_admin else "🔒 #general (Admin Only)",
                state=tk.NORMAL if is_admin else tk.DISABLED,
            )
        else:
            self.chat_title.configure(text=f"🔒 Direct Message: @{target}")
            self.purge_btn.configure(text="🗑️ Clear Chat for Me", state=tk.NORMAL)

        self._refresh_room_view()

    def _on_user_pick(self, _event):
        sel = self.user_listbox.curselection()
        if not sel:
            return
        item_text = self.user_listbox.get(sel[0])
        clean_user = item_text.split(" (")[0].replace("🟢 @", "").strip()
        self.select_recipient(clean_user)

    def set_users(self, users):
        my_name = self.app.client.username
        self._online_users = [u for u in users if u != my_name]
        self._filter_users()

    def set_files(self, files):
        labels = [f"{item['id']}: {item['name']} ({item['uploader']})" for item in files]
        self.files_combo["values"] = labels
        if labels:
            self.files_combo.current(0)
        else:
            self.files_combo.set("")

    def clear(self):
        self.clear_messages()
        self._conversations = {EVERYONE: []}
        self._unread_counts = {}
        self.files_combo["values"] = []
        self.files_combo.set("")
        self._current_recipient = EVERYONE
        self.chat_title.configure(text="📢 # general")
        self.admin_btn.pack_forget()
        if self.search_frame.winfo_ismapped():
            self.search_frame.pack_forget()

    def disconnect(self):
        if messagebox.askokcancel("Disconnect", "Disconnect from NexusChat?", parent=self):
            self.app.client.disconnect()

    def append_system(self, text):
        self._write(f"ℹ  {text}\n\n", "sys")

    def _room_for_message(self, msg):
        recipient = msg.get("recipient") or EVERYONE
        sender = msg.get("sender") or ""
        my_name = self.app.client.username or ""
        if recipient in (EVERYONE, "all"):
            return EVERYONE
        if recipient == my_name:
            return sender
        return recipient

    def _render_message(self, msg):
        stamp = msg.get("created_at") or ""
        sender = msg.get("sender") or "?"
        recipient = msg.get("recipient") or EVERYONE
        body = msg.get("body") or ""
        is_self = sender == self.app.client.username

        sender_tag = "user_self" if is_self else "user_other"
        arrow = "→ #general" if recipient in (EVERYONE, "all") else f"→ @{recipient}"

        self._write(f"@{sender} {arrow}  ", sender_tag)
        self._write(f"{stamp}\n", "stamp")

        if msg.get("msg_type") == "file":
            file_id = msg.get("file_id")
            name = msg.get("filename") or body
            size_kb = f"{(int(msg.get('size', 0)) / 1024):.1f} KB" if msg.get("size") else ""
            self._write(f"  📦 File: {name} ({size_kb}) [Click to Download]\n\n", "file_box")
        else:
            self._write(f"  {body}\n\n")
            self._tag_links(body)

    def _refresh_room_view(self):
        self.clear_messages()
        room_msgs = self._conversations.get(self._current_recipient, [])
        if not room_msgs:
            if self._current_recipient == EVERYONE:
                self.append_system("Welcome to #general global chat! Only admins can purge this channel.")
            else:
                self.append_system(f"Direct message history with @{self._current_recipient}. Clearing chat only removes it from your own chat window.")
            return

        for msg in room_msgs:
            self._render_message(msg)

    def append_message(self, msg, store=True):
        room = self._room_for_message(msg)
        if store:
            if room not in self._conversations:
                self._conversations[room] = []
            self._conversations[room].append(msg)

        if room == self._current_recipient:
            self._render_message(msg)
        else:
            self._unread_counts[room] = self._unread_counts.get(room, 0) + 1
            self._filter_users()

    def load_history(self, rows):
        self._conversations = {EVERYONE: []}
        self._unread_counts = {}
        if not rows:
            self._refresh_room_view()
            return
        for row in rows:
            room = self._room_for_message(row)
            if room not in self._conversations:
                self._conversations[room] = []
            self._conversations[room].append(row)
        self._refresh_room_view()
        self._filter_users()

    def delete_hist(self):
        curr = self._current_recipient
        is_admin = self.app.client.role == "admin"

        if curr == EVERYONE:
            if not is_admin:
                messagebox.showerror(
                    "Permission Denied",
                    "Only Administrators can purge the global #general chat history.",
                    parent=self,
                )
                return
            if messagebox.askyesno(
                "Purge Global Chat",
                "As an Administrator, are you sure you want to permanently delete ALL global messages in #general for all users?\n\nThis action cannot be undone!",
                parent=self,
            ):
                self.app.client.delete_history(room=EVERYONE)
                self._conversations[EVERYONE] = []
                self.clear_messages()
                self.append_system("You permanently purged the global #general chat for everyone.")
        else:
            if messagebox.askyesno(
                "Clear Conversation (Delete for Me)",
                f"Delete this conversation with @{curr} from your chat window?\n\n"
                f"• This will remove the messages from your own chat view and history.\n"
                f"• @{curr}'s chat history will NOT be deleted.",
                parent=self,
            ):
                self.app.client.delete_history(room=curr)
                self._conversations[curr] = []
                self.clear_messages()
                self.append_system(f"Conversation with @{curr} was cleared from your chat window.")

    def export_chat(self):
        content = self.messages.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Export Chat", "There are no messages in the view to export.", parent=self)
            return
        dest = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".txt",
            filetypes=[("Text File", "*.txt"), ("Markdown File", "*.md"), ("All Files", "*.*")],
            title="Export Chat Conversation",
        )
        if dest:
            try:
                Path(dest).write_text(content, encoding="utf-8")
                messagebox.showinfo("Export Chat", f"Chat conversation exported successfully to:\n{dest}", parent=self)
            except Exception as exc:
                messagebox.showerror("Export Error", f"Failed to save file: {exc}", parent=self)

    def clear_messages(self):
        self.messages.configure(state=tk.NORMAL)
        self.messages.delete("1.0", tk.END)
        self.messages.configure(state=tk.DISABLED)

    def _write(self, text, tag=None):
        self.messages.configure(state=tk.NORMAL)
        if tag:
            self.messages.insert(tk.END, text, tag)
        else:
            self.messages.insert(tk.END, text)
        self.messages.see(tk.END)
        self.messages.configure(state=tk.DISABLED)

    def _tag_links(self, body):
        for part in body.split():
            if part.startswith("http://") or part.startswith("https://"):
                start = self.messages.search(part, "1.0", tk.END)
                if start:
                    end = f"{start}+{len(part)}c"
                    self.messages.configure(state=tk.NORMAL)
                    self.messages.tag_add("link", start, end)
                    self.messages.configure(state=tk.DISABLED)

    def _open_link(self, _event):
        try:
            idx = self.messages.index(f"@{_event.x},{_event.y}")
            ranges = self.messages.tag_prevrange("link", idx)
            if ranges:
                webbrowser.open(self.messages.get(*ranges))
        except Exception:
            pass

    def _on_file_click(self, _event):
        self.download_file()

    def send(self):
        text = self.entry.get("1.0", tk.END).strip()
        if not text:
            return
        self.entry.delete("1.0", tk.END)
        self.app.client.send_chat(self._current_recipient, text)

    def load_hist(self):
        self.app.client.request_history()

    def send_file(self):
        path = filedialog.askopenfilename()
        if not path:
            return
        self._run_upload(lambda: self.app.client.upload_path(path, self._current_recipient))

    def send_zip(self):
        paths = filedialog.askopenfilenames()
        if not paths:
            return
        name = simpledialog.askstring("Zip Archive", "Archive name (without .zip):", parent=self)
        if not name:
            return
        self._run_upload(lambda: self.app.client.upload_many(paths, f"{name}.zip", self._current_recipient))

    def _run_upload(self, fn):
        def work():
            try:
                fn()
            except Exception as exc:
                self.app.client.emit("error", str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _selected_file_id(self):
        val = self.files_combo.get()
        if not val or ":" not in val:
            return None
        try:
            return int(val.split(":", 1)[0])
        except ValueError:
            return None

    def download_file(self):
        file_id = self._selected_file_id()
        if file_id is None:
            messagebox.showinfo("Download", "Select a file from the dropdown or click 'Browse & Search Files'.", parent=self)
            return
        dest = filedialog.askdirectory(parent=self)
        if not dest:
            return
        self.app.client.start_download(file_id, dest)

    def delete_file(self):
        file_id = self._selected_file_id()
        if file_id is None:
            messagebox.showinfo("Select File", "Please select a file from the dropdown first.", parent=self)
            return
        file_meta = next((f for f in self.app._files if f.get("id") == file_id), None)
        uploader = file_meta.get("uploader") if file_meta else ""
        filename = file_meta.get("name") if file_meta else f"File #{file_id}"
        my_user = self.app.client.username or ""
        is_owner_or_admin = (uploader == my_user) or (self.app.client.role == "admin")

        mode = prompt_file_delete(self, filename, is_owner_or_admin)
        if mode:
            self.app.client.delete_file(file_id, mode=mode)


def prompt_file_delete(parent, filename, is_owner_or_admin):
    result = {"choice": None}
    dlg = tk.Toplevel(parent)
    dlg.title("Delete File Options")
    dlg.geometry("480x220")
    dlg.resizable(False, False)
    dlg.configure(bg=BG)
    dlg.transient(parent)
    dlg.grab_set()

    try:
        x = parent.winfo_rootx() + (parent.winfo_width() - 480) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - 220) // 2
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
    except Exception:
        pass

    content = ttk.Frame(dlg, padding=16)
    content.pack(fill=tk.BOTH, expand=True)

    ttk.Label(content, text=f"🗑️ Delete File: {filename}", style="Title.TLabel", wraplength=440).pack(anchor="w", pady=(0, 8))

    if is_owner_or_admin:
        desc = (
            "Choose a deletion mode:\n\n"
            "• Delete for Me: Hide this file from your list only.\n"
            "• Delete for Everyone: Permanently delete the file from the server disk and all users."
        )
    else:
        desc = (
            "Remove this file from your view?\n\n"
            "ℹ As a receiver, you can only delete for yourself. The file will remain on the server for other users."
        )

    ttk.Label(content, text=desc, style="Muted.TLabel", wraplength=440, justify=tk.LEFT).pack(anchor="w", pady=(0, 16))

    btn_row = ttk.Frame(content)
    btn_row.pack(side=tk.BOTTOM, fill=tk.X)

    def choose(val):
        result["choice"] = val
        dlg.destroy()

    ttk.Button(btn_row, text="Cancel", command=lambda: choose(None)).pack(side=tk.RIGHT, padx=(4, 0))

    if is_owner_or_admin:
        ttk.Button(
            btn_row,
            text="🌐 Delete for Everyone",
            style="Danger.TButton",
            command=lambda: choose("everyone"),
        ).pack(side=tk.RIGHT, padx=(4, 4))

    ttk.Button(
        btn_row,
        text="🗑️ Delete for Me",
        style="Accent.TButton",
        command=lambda: choose("me"),
    ).pack(side=tk.RIGHT, padx=(0, 4))

    dlg.wait_window()
    return result["choice"]


class FileExplorerWindow(tk.Toplevel):
    def __init__(self, master, app: ChatApp):
        super().__init__(master)
        self.app = app
        self.title("📁 NexusChat - Searchable File Explorer")
        self.geometry("780x500")
        self.minsize(640, 420)
        self.configure(bg=BG)

        self._all_files = []

        # Header with Search Box
        header = ttk.Frame(self, padding=12)
        header.pack(fill=tk.X)
        ttk.Label(header, text="📁 Shared Files Explorer", style="Title.TLabel").pack(side=tk.LEFT)

        search_box = ttk.Frame(header)
        search_box.pack(side=tk.RIGHT)
        ttk.Label(search_box, text="Filter:", style="SidebarMuted.TLabel").pack(side=tk.LEFT, padx=(0, 4))
        self.search_entry = ttk.Entry(search_box, width=24)
        self.search_entry.pack(side=tk.LEFT)
        self.search_entry.bind("<KeyRelease>", lambda e: self._filter_table())

        # Treeview table
        columns = ("id", "name", "size", "uploader", "date")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("id", text="ID", command=lambda: self._sort_col("id"))
        self.tree.heading("name", text="Filename", command=lambda: self._sort_col("name"))
        self.tree.heading("size", text="Size", command=lambda: self._sort_col("size"))
        self.tree.heading("uploader", text="Uploader", command=lambda: self._sort_col("uploader"))
        self.tree.heading("date", text="Uploaded Date", command=lambda: self._sort_col("date"))

        self.tree.column("id", width=50, anchor="center")
        self.tree.column("name", width=260)
        self.tree.column("size", width=90, anchor="center")
        self.tree.column("uploader", width=120)
        self.tree.column("date", width=160)

        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0), pady=(0, 12))
        scrollbar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12), pady=(0, 12))
        self.tree.bind("<Double-1>", lambda e: self.do_download())

        # Action Buttons Docked at Bottom
        actions = ttk.Frame(self, padding=12)
        actions.pack(side=tk.BOTTOM, fill=tk.X)

        self.count_lbl = ttk.Label(actions, text="0 files", style="SidebarMuted.TLabel")
        self.count_lbl.pack(side=tk.LEFT)

        ttk.Button(actions, text="Close", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(actions, text="🗑 Delete File", style="Danger.TButton", command=self.do_delete).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(actions, text="⬇ Download Selected", style="Accent.TButton", command=self.do_download).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(actions, text="🔄 Refresh", command=self.app.client.request_files).pack(side=tk.RIGHT, padx=4)

    def populate_files(self, files):
        self._all_files = files
        self._filter_table()

    def _filter_table(self):
        query = self.search_entry.get().strip().lower()
        for item in self.tree.get_children():
            self.tree.delete(item)

        matched = 0
        for f in self._all_files:
            name = str(f.get("name", "")).lower()
            uploader = str(f.get("uploader", "")).lower()
            if query and query not in name and query not in uploader:
                continue

            size_bytes = int(f.get("size", 0))
            if size_bytes > 1024 * 1024:
                size_str = f"{(size_bytes / (1024 * 1024)):.2f} MB"
            else:
                size_str = f"{(size_bytes / 1024):.1f} KB"

            self.tree.insert(
                "",
                tk.END,
                values=(f.get("id"), f.get("name"), size_str, f.get("uploader"), f.get("created_at")),
            )
            matched += 1
        self.count_lbl.configure(text=f"Showing {matched} of {len(self._all_files)} file(s)")

    def _selected_file(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Select File", "Please select a file from the table first.", parent=self)
            return None, None
        vals = self.tree.item(sel[0], "values")
        return int(vals[0]), vals[1]

    def do_download(self):
        file_id, name = self._selected_file()
        if file_id is None:
            return
        dest = filedialog.askdirectory(parent=self)
        if not dest:
            return
        self.app.client.start_download(file_id, dest)

    def do_delete(self):
        file_id, name = self._selected_file()
        if file_id is None:
            return
        file_meta = next((f for f in self._all_files if f.get("id") == file_id), None)
        uploader = file_meta.get("uploader") if file_meta else ""
        filename = file_meta.get("name") if file_meta else name
        my_user = self.app.client.username or ""
        is_owner_or_admin = (uploader == my_user) or (self.app.client.role == "admin")

        mode = prompt_file_delete(self, filename, is_owner_or_admin)
        if mode:
            self.app.client.delete_file(file_id, mode=mode)

    def _sort_col(self, col):
        pass


class AdminWindow(tk.Toplevel):
    def __init__(self, master, app: ChatApp):
        super().__init__(master)
        self.app = app
        self.title("🛡️ NexusChat Admin Control Panel")
        self.geometry("760x540")
        self.minsize(660, 440)
        self.configure(bg=BG)

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # Tab 1: User Management
        self.users_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.users_tab, text="👥 User Management")
        self._build_users_tab()

        # Tab 2: Server Metrics
        self.stats_tab = ttk.Frame(notebook, padding=16)
        notebook.add(self.stats_tab, text="📊 Server Statistics")
        self._build_stats_tab()

        # Initial fetch
        self.refresh_users()
        self.refresh_stats()

    def _build_users_tab(self):
        # 1. Search Bar for users
        top_bar = ttk.Frame(self.users_tab)
        top_bar.pack(side=tk.TOP, fill=tk.X, pady=(0, 8))
        ttk.Label(top_bar, text="Filter Users:", style="SidebarMuted.TLabel").pack(side=tk.LEFT, padx=(0, 6))
        self.admin_search_entry = ttk.Entry(top_bar, width=22)
        self.admin_search_entry.pack(side=tk.LEFT)
        self.admin_search_entry.bind("<KeyRelease>", lambda e: self._filter_admin_users())

        # 2. Action buttons docked at bottom
        actions = ttk.Frame(self.users_tab, padding=(0, 10, 0, 0))
        actions.pack(side=tk.BOTTOM, fill=tk.X)

        ttk.Button(actions, text="🔄 Refresh", command=self.refresh_users).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(actions, text="👑 Toggle Admin/User", command=self.toggle_role).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="🔑 Reset Password", command=self.reset_password).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="🚪 Kick User", command=self.kick_user).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="🗑 Delete User", style="Danger.TButton", command=self.delete_user).pack(
            side=tk.RIGHT, padx=4
        )

        # 3. Treeview for Users (fills middle)
        columns = ("id", "username", "role", "online", "created_at")
        self.tree = ttk.Treeview(self.users_tab, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("id", text="ID")
        self.tree.heading("username", text="Username")
        self.tree.heading("role", text="Role")
        self.tree.heading("online", text="Status")
        self.tree.heading("created_at", text="Registered Date")

        self.tree.column("id", width=40, anchor="center")
        self.tree.column("username", width=140)
        self.tree.column("role", width=80, anchor="center")
        self.tree.column("online", width=80, anchor="center")
        self.tree.column("created_at", width=180)

        scrollbar = ttk.Scrollbar(self.users_tab, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._raw_users = []

    def _build_stats_tab(self):
        header = ttk.Label(self.stats_tab, text="Server Metrics & Storage", style="Title.TLabel")
        header.pack(anchor="w", pady=(0, 16))

        grid = ttk.Frame(self.stats_tab)
        grid.pack(fill=tk.BOTH, expand=True)

        self.stat_online = self._stat_card(grid, "🟢 Online Users", "0", 0, 0)
        self.stat_users = self._stat_card(grid, "👥 Registered Accounts", "0", 0, 1)
        self.stat_messages = self._stat_card(grid, "💬 Total Messages", "0", 1, 0)
        self.stat_files = self._stat_card(grid, "📁 Stored Files", "0", 1, 1)
        self.stat_bytes = self._stat_card(grid, "💾 Storage Footprint", "0 KB", 2, 0)

        ttk.Button(self.stats_tab, text="🔄 Refresh Metrics", command=self.refresh_stats).pack(
            anchor="e", pady=(16, 0)
        )

    def _stat_card(self, parent, title, val, row, col):
        card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
        parent.grid_columnconfigure(col, weight=1)
        ttk.Label(card, text=title, style="Muted.TLabel").pack(anchor="w")
        label = ttk.Label(card, text=val, style="Title.TLabel")
        label.pack(anchor="w", pady=(6, 0))
        return label

    def refresh_users(self):
        self.app.client.admin_request_users()

    def refresh_stats(self):
        self.app.client.admin_request_stats()

    def populate_users(self, users):
        self._raw_users = users
        self._filter_admin_users()

    def _filter_admin_users(self):
        query = self.admin_search_entry.get().strip().lower()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for u in self._raw_users:
            uname = str(u.get("username", "")).lower()
            if query and query not in uname:
                continue
            status_text = "🟢 Online" if u.get("online") else "⚪ Offline"
            self.tree.insert(
                "",
                tk.END,
                values=(
                    u.get("id"),
                    u.get("username"),
                    (u.get("role") or "user").upper(),
                    status_text,
                    u.get("created_at"),
                ),
            )

    def populate_stats(self, stats):
        self.stat_online.configure(text=str(stats.get("online_users", 0)))
        self.stat_users.configure(text=str(stats.get("users", 0)))
        self.stat_messages.configure(text=str(stats.get("messages", 0)))
        self.stat_files.configure(text=str(stats.get("files", 0)))
        raw_bytes = int(stats.get("bytes", 0))
        if raw_bytes > 1024 * 1024:
            size_str = f"{(raw_bytes / (1024 * 1024)):.2f} MB"
        else:
            size_str = f"{(raw_bytes / 1024):.1f} KB"
        self.stat_bytes.configure(text=size_str)

    def _selected_user(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Admin Action", "Please select a user from the table first.", parent=self)
            return None, None
        vals = self.tree.item(sel[0], "values")
        return vals[1], vals[2].lower()

    def toggle_role(self):
        username, current_role = self._selected_user()
        if not username:
            return
        new_role = "user" if current_role == "admin" else "admin"
        if messagebox.askyesno(
            "Change Role",
            f"Change role for @{username} from {current_role.upper()} to {new_role.upper()}?",
            parent=self,
        ):
            self.app.client.admin_set_role(username, new_role)

    def reset_password(self):
        username, _ = self._selected_user()
        if not username:
            return
        new_pw = simpledialog.askstring(
            "Reset Password",
            f"Enter new password for @{username} (min 4 characters):",
            parent=self,
        )
        if new_pw:
            self.app.client.admin_reset_password(username, new_pw)

    def kick_user(self):
        username, _ = self._selected_user()
        if not username:
            return
        if messagebox.askyesno("Kick User", f"Kick @{username}'s active connection?", parent=self):
            self.app.client.admin_kick_user(username)

    def delete_user(self):
        username, _ = self._selected_user()
        if not username:
            return
        if messagebox.askyesno(
            "Delete User",
            f"Permanently delete @{username} and all their messages/files?\nThis cannot be undone!",
            parent=self,
        ):
            self.app.client.admin_delete_user(username)

    def handle_result(self, payload):
        action = payload.get("action")
        ok = payload.get("ok")
        err = payload.get("error")
        target = payload.get("target")

        if ok:
            messagebox.showinfo("Admin Success", f"Action '{action}' succeeded for @{target}.", parent=self)
            self.refresh_users()
            self.refresh_stats()
        else:
            messagebox.showerror("Admin Error", f"Action failed: {err or 'unknown error'}", parent=self)


def main():
    try:
        app = ChatApp()
        app.mainloop()
    except (KeyboardInterrupt, SystemExit):
        try:
            if 'app' in locals():
                app.on_close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
