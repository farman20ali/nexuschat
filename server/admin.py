"""Server administration CLI and standalone UI tool."""
import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.database import Database
from server import settings


from shared.auth import create_jwt_token, verify_jwt_token

SESSION_FILE = Path.home() / ".nexuschat_admin_session"


def save_session(username, role="admin"):
    token = create_jwt_token({"sub": username, "role": role, "token_type": "admin_session"}, expires_in=86400)
    try:
        SESSION_FILE.write_text(token, encoding="utf-8")
    except Exception:
        pass


def clear_session():
    try:
        SESSION_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def is_admin_logged_in(db):
    if not SESSION_FILE.is_file():
        return False
    try:
        token = SESSION_FILE.read_text(encoding="utf-8").strip()
        valid, payload = verify_jwt_token(token)
        if not valid or payload.get("token_type") != "admin_session":
            return False
        username = payload.get("sub")
        if not username:
            return False
        role = db.get_user_role(username)
        return role == "admin"
    except Exception:
        return False


def cmd_login(db):
    print("\n--- 🛡️ NexusChat Server Admin Login ---")
    username = input("Admin Username [admin]: ").strip() or "admin"
    password = getpass.getpass(f"Password for @{username}: ").strip()
    
    ok, error, role, must_change = db.authenticate(username, password)
    if ok and role == "admin":
        if must_change:
            print(f"\n[NOTICE] Password change is required for @{username} on first login.")
            while True:
                new_pw = getpass.getpass("Enter your new password: ").strip()
                conf_pw = getpass.getpass("Confirm new password: ").strip()
                if not new_pw or len(new_pw) < 4:
                    print("Error: Password must be at least 4 characters.")
                    continue
                if new_pw != conf_pw:
                    print("Error: Passwords do not match. Try again.")
                    continue
                if new_pw == password:
                    print("Error: New password must be different from current password.")
                    continue
                db.reset_password(username, new_pw, must_change=False)
                password = new_pw
                print("[OK] Password successfully updated!")
                break

        save_session(username, role)
        print(f"\n[OK] Successfully logged in as Administrator '@{username}'.")
        print("JWT session created. You can now execute admin CLI commands.\n")
    elif ok and role != "admin":
        print(f"\n[ERROR] User '@{username}' does not have administrator privileges.")
        sys.exit(1)
    else:
        print(f"\n[ERROR] Authentication failed: {error or 'invalid credentials'}")
        sys.exit(1)


def cmd_logout():
    clear_session()
    print("\n[OK] Admin CLI session logged out successfully.\n")


def cmd_list_users(db):
    users = db.list_all_users()
    if not users:
        print("No users registered in database.")
        return
    print(f"\n{'ID':<5} {'Username':<20} {'Role':<10} {'Registered At':<22}")
    print("-" * 60)
    for u in users:
        print(f"{u['id']:<5} {u['username']:<20} {u['role']:<10} {u['created_at']:<22}")
    print(f"\nTotal: {len(users)} user(s)\n")


def cmd_reset_password(db, username, password=None, require_change=False):
    logged_in = is_admin_logged_in(db)

    # Security check: If not logged in, ONLY allow resetting root 'admin' account!
    if not logged_in and username != "admin":
        print("\n" + "=" * 68)
        print(" [ERROR] Administrator login required to reset user accounts!")
        print("=" * 68)
        print(" Un-gated CLI password reset is strictly restricted to root 'admin' recovery.")
        print(" Please log in first: nexuschat admin login\n")
        sys.exit(1)

    # Security verification: Check if security questions exist for target user
    q1, q2, configured = db.get_security_questions(username)
    if configured:
        print(f"\n--- 🛡️ Security Verification for @{username} ---")
        print(f" Question 1: {q1}")
        ans1 = getpass.getpass(" Answer 1: ").strip()
        print(f" Question 2: {q2}")
        ans2 = getpass.getpass(" Answer 2: ").strip()
        ok_ver, err_ver = db.verify_security_answers(username, ans1, ans2)
        if not ok_ver:
            print(f"\n[ERROR] Security verification failed: {err_ver}")
            sys.exit(1)
        print("[OK] Security questions verified successfully!")
    elif not logged_in and username == "admin":
        import os
        master_env = os.environ.get("NEXUS_MASTER_KEY")
        if master_env:
            provided_key = getpass.getpass(" Enter NEXUS_MASTER_KEY: ").strip()
            if provided_key != master_env:
                print("\n[ERROR] Invalid Master Key.")
                sys.exit(1)

    if not password:
        password = getpass.getpass(f"Enter new password for {username}: ")
        confirm = getpass.getpass("Confirm new password: ")
        if password != confirm:
            print("Error: Passwords do not match.")
            sys.exit(1)

    ok, err = db.reset_password(username, password, must_change=require_change)
    if ok:
        flag_str = " (user forced to change password on next login)" if require_change else ""
        print(f"Password successfully reset for '{username}'{flag_str}.")
    else:
        print(f"Error resetting password: {err or 'user not found'}")
        sys.exit(1)


def cmd_setup_security_questions(db, target_username=None):
    user = target_username or input("Username to configure recovery questions for [admin]: ").strip() or "admin"
    print(f"\n--- 🛡️ Configure Security Questions for @{user} ---")
    
    # Require current password confirmation to authorize setting/updating security questions
    cur_pw = getpass.getpass(f"Enter current password for @{user} to authorize changes: ").strip()
    ok_auth, err_auth, _, _ = db.authenticate(user, cur_pw)
    if not ok_auth:
        print(f"\n[ERROR] Authorization failed: {err_auth or 'Incorrect password'}\n")
        sys.exit(1)
    print("1. What was the name of your first pet?")
    print("2. What city were you born in?")
    print("3. What was the name of your first school?")
    print("4. Custom Question 1")

    opt1 = input("Select Question #1 [1-4, default 1]: ").strip() or "1"
    if opt1 == "1":
        q1 = "What was the name of your first pet?"
    elif opt1 == "2":
        q1 = "What city were you born in?"
    elif opt1 == "3":
        q1 = "What was the name of your first school?"
    else:
        q1 = input("Enter Custom Question #1: ").strip() or "Custom Security Question #1"

    a1 = getpass.getpass(f"Answer for '{q1}': ").strip()

    print("\n1. What is your favorite book/movie?")
    print("2. What was your mother's maiden name?")
    print("3. What was your first car?")
    print("4. Custom Question 2")

    opt2 = input("Select Question #2 [1-4, default 1]: ").strip() or "1"
    if opt2 == "1":
        q2 = "What is your favorite book/movie?"
    elif opt2 == "2":
        q2 = "What was your mother's maiden name?"
    elif opt2 == "3":
        q2 = "What was your first car?"
    else:
        q2 = input("Enter Custom Question #2: ").strip() or "Custom Security Question #2"

    a2 = getpass.getpass(f"Answer for '{q2}': ").strip()

    ok, err = db.set_security_questions(user, q1, a1, q2, a2)
    if ok:
        print(f"\n[OK] Security questions configured and bcrypt-hashed for @{user}.\n")
    else:
        print(f"\n[ERROR] Failed to set security questions: {err}")
        sys.exit(1)


def cmd_recover_password(db, username=None):
    user = username or input("Username to recover password for: ").strip()
    if not user:
        print("Error: Username is required.")
        sys.exit(1)

    q1, q2, configured = db.get_security_questions(user)
    if not configured:
        print(f"\n[ERROR] Security questions are not configured for user '@{user}'.")
        print("Please contact a server administrator or reset password via CLI admin.\n")
        sys.exit(1)

    print(f"\n--- 🔑 Self-Service Password Recovery for @{user} ---")
    print(f" Question 1: {q1}")
    a1 = getpass.getpass(" Answer 1: ").strip()
    print(f" Question 2: {q2}")
    a2 = getpass.getpass(" Answer 2: ").strip()

    ok_ver, err_ver = db.verify_security_answers(user, a1, a2)
    if not ok_ver:
        print(f"\n[ERROR] Recovery failed: {err_ver}")
        sys.exit(1)

    print("\n[OK] Security questions verified successfully!")
    new_pw = getpass.getpass(f"Enter new password for @{user}: ")
    confirm_pw = getpass.getpass("Confirm new password: ")
    if new_pw != confirm_pw:
        print("Error: Passwords do not match.")
        sys.exit(1)

    ok_rst, err_rst = db.reset_password(user, new_pw, must_change=False)
    if ok_rst:
        print(f"\n[OK] Password successfully recovered and updated for @{user}!\n")
    else:
        print(f"\n[ERROR] Failed to update password: {err_rst}")
        sys.exit(1)


def cmd_set_role(db, username, role):
    ok, err = db.set_user_role(username, role)
    if ok:
        print(f"User '{username}' role updated to '{role}'.")
    else:
        print(f"Error updating role: {err or 'user not found'}")
        sys.exit(1)


def cmd_delete_user(db, username):
    confirm = input(f"Are you sure you want to permanently delete '{username}'? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return
    ok = db.delete_user(username)
    if ok:
        print(f"User '{username}' and associated messages/files deleted.")
    else:
        print(f"Error: User '{username}' not found.")
        sys.exit(1)


def cmd_stats(db):
    stats = db.get_stats()
    raw_bytes = stats["bytes"]
    if raw_bytes > 1024 * 1024:
        size_str = f"{(raw_bytes / (1024 * 1024)):.2f} MB"
    else:
        size_str = f"{(raw_bytes / 1024):.1f} KB"
    print("\n--- ⚡ NexusChat Server Metrics ---")
    print(f"Registered Users: {stats['users']}")
    print(f"Total Messages:   {stats['messages']}")
    print(f"Stored Files:     {stats['files']}")
    print(f"Disk Storage:     {size_str} ({raw_bytes} bytes)")
    print(f"Storage Path:     {settings.FILE_DIR}\n")


def cmd_ui(db):
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog
    from client.theme import apply_theme, BG, ui_font

    root = tk.Tk()
    root.title("🛡️ NexusChat Server Admin")
    root.geometry("700x480")
    apply_theme(root)

    header = ttk.Frame(root, padding=12)
    header.pack(fill=tk.X)
    ttk.Label(header, text="🛡️ NexusChat Server Admin", style="Title.TLabel").pack(side=tk.LEFT)
    ttk.Label(header, text=f"DB: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}", style="Muted.TLabel").pack(side=tk.RIGHT)

    columns = ("id", "username", "role", "created_at")
    tree = ttk.Treeview(root, columns=columns, show="headings")
    tree.heading("id", text="ID")
    tree.heading("username", text="Username")
    tree.heading("role", text="Role")
    tree.heading("created_at", text="Registered")
    tree.column("id", width=50, anchor="center")
    tree.column("username", width=160)
    tree.column("role", width=90, anchor="center")
    tree.column("created_at", width=200)
    tree.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)

    def load_users():
        for item in tree.get_children():
            tree.delete(item)
        for u in db.list_all_users():
            tree.insert("", tk.END, values=(u["id"], u["username"], u["role"].upper(), u["created_at"]))

    actions = ttk.Frame(root, padding=12)
    actions.pack(fill=tk.X)

    def get_selected():
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Select User", "Please select a user first.")
            return None, None
        vals = tree.item(sel[0], "values")
        return vals[1], vals[2].lower()

    def do_reset_pw():
        u, _ = get_selected()
        if not u:
            return
        pw = simpledialog.askstring("Reset Password", f"New password for {u}:", parent=root)
        if pw:
            ok, err = db.reset_password(u, pw, must_change=False)
            if ok:
                messagebox.showinfo("Success", f"Password reset for {u}.")
            else:
                messagebox.showerror("Error", err or "Failed.")

    def do_toggle_role():
        u, r = get_selected()
        if not u:
            return
        new_r = "user" if r == "admin" else "admin"
        ok, err = db.set_user_role(u, new_r)
        if ok:
            load_users()
        else:
            messagebox.showerror("Error", err or "Failed.")

    def do_delete():
        u, _ = get_selected()
        if not u:
            return
        if messagebox.askyesno("Delete User", f"Permanently delete {u}?", parent=root):
            if db.delete_user(u):
                load_users()
            else:
                messagebox.showerror("Error", "Could not delete user.")

    ttk.Button(actions, text="🔄 Refresh", command=load_users).pack(side=tk.LEFT, padx=4)
    ttk.Button(actions, text="👑 Toggle Admin", command=do_toggle_role).pack(side=tk.LEFT, padx=4)
    ttk.Button(actions, text="🔑 Reset Password", command=do_reset_pw).pack(side=tk.LEFT, padx=4)
    ttk.Button(actions, text="🗑 Delete User", style="Danger.TButton", command=do_delete).pack(side=tk.RIGHT, padx=4)

    load_users()
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="NexusChat Server Admin Tool")
    subparsers = parser.add_subparsers(dest="command", help="Admin command to execute")

    subparsers.add_parser("login", help="Authenticate and start admin CLI session")
    subparsers.add_parser("logout", help="End current admin CLI session")
    subparsers.add_parser("list-users", help="List all registered users")
    subparsers.add_parser("stats", help="Show database and storage metrics")
    subparsers.add_parser("ui", help="Open standalone Tkinter Admin GUI")

    pw_parser = subparsers.add_parser("reset-password", help="Reset a user's password (un-gated root recovery tool)")
    pw_parser.add_argument("username", help="Username to reset")
    pw_parser.add_argument("password", nargs="?", default=None, help="New password (optional, prompted if omitted)")
    pw_parser.add_argument("--require-change", action="store_true", help="Force user to change password on next login")

    sec_parser = subparsers.add_parser("setup-security-questions", help="Configure recovery security questions for a user")
    sec_parser.add_argument("username", nargs="?", default=None, help="Username to configure")

    rec_parser = subparsers.add_parser("recover-password", help="Self-service password recovery using security questions")
    rec_parser.add_argument("username", nargs="?", default=None, help="Username to recover")

    role_parser = subparsers.add_parser("set-role", help="Set user role (admin or user)")
    role_parser.add_argument("username", help="Username")
    role_parser.add_argument("role", choices=["admin", "user"], help="Role to assign")

    del_parser = subparsers.add_parser("delete-user", help="Delete a user and their data")
    del_parser.add_argument("username", help="Username to delete")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "logout":
        cmd_logout()
        return

    try:
        db = Database()
        try:
            db.connect()
        except Exception as exc:
            print(f"Error connecting to database: {exc}")
            sys.exit(1)

        try:
            if args.command == "login":
                cmd_login(db)
                return
            elif args.command == "recover-password":
                cmd_recover_password(db, args.username)
                return

            # Gate all commands except reset-password, recover-password, and setup-security-questions behind active admin login session
            if args.command not in ("reset-password", "recover-password", "setup-security-questions"):
                if not is_admin_logged_in(db):
                    print("\n" + "=" * 64)
                    print(" [ERROR] Administrator login required!")
                    print("=" * 64)
                    print(" You must log in first to execute admin commands.")
                    print(" Run: nexuschat admin login\n")
                    sys.exit(1)

            if args.command == "list-users":
                cmd_list_users(db)
            elif args.command == "reset-password":
                cmd_reset_password(db, args.username, args.password, require_change=args.require_change)
            elif args.command == "setup-security-questions":
                cmd_setup_security_questions(db, args.username)
            elif args.command == "set-role":
                cmd_set_role(db, args.username, args.role)
            elif args.command == "delete-user":
                cmd_delete_user(db, args.username)
            elif args.command == "stats":
                cmd_stats(db)
            elif args.command == "ui":
                try:
                    cmd_ui(db)
                except (KeyboardInterrupt, SystemExit):
                    pass
        finally:
            db.close()
    except (KeyboardInterrupt, SystemExit):
        print("\n[INFO] Admin operation cancelled.")
        sys.exit(0)


if __name__ == "__main__":
    main()
