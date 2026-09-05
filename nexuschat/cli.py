"""Unified CLI for NexusChat (Client, Server, Setup, and Admin)."""
import argparse
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_client():
    from client.app import main as client_main
    try:
        client_main()
    except (KeyboardInterrupt, SystemExit):
        pass


def print_db_error_help(exc):
    from server import settings
    print("\n" + "=" * 68)
    print(" [ERROR] Failed to connect to PostgreSQL database!")
    print("=" * 68)
    print(f" Target Host: {settings.DB_HOST}:{settings.DB_PORT}")
    print(f" Database:    {settings.DB_NAME}")
    print(f" User:        {settings.DB_USER}")
    print(f" Error:       {exc}\n")
    print(" [HOW TO FIX]:")
    print(" 1. Ensure your PostgreSQL service is running:")
    print("    * Windows: Start 'PostgreSQL' in Windows Services,")
    print("               or run in terminal: net start postgresql-x64-16")
    print("    * Linux:   sudo systemctl start postgresql")
    print("    * Docker:  docker start <postgres_container>")
    print(" 2. Configure credentials with the setup wizard:")
    print("    nexuschat setup-db")
    print(" 3. Or verify/edit your .env file in the project root:")
    print("    CHAT_DB_HOST=localhost")
    print("    CHAT_DB_PORT=5433  (or 5432)")
    print("    CHAT_DB_NAME=tkinter")
    print("    CHAT_DB_USER=postgres")
    print("    CHAT_DB_PASSWORD=your_password")
    print("=" * 68 + "\n")


def run_server(host="0.0.0.0", port=None, discovery_port=None, file_dir=None):
    from server.chat_server import ChatServer
    from server import settings
    import logging
    import signal

    if file_dir:
        settings.set_file_dir(file_dir)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    tcp_port = int(port) if port else settings.TCP_PORT
    disc_port = int(discovery_port) if discovery_port else settings.DISCOVERY_PORT
    server = ChatServer(host=host, port=tcp_port, discovery_port=disc_port)

    def _sig_handler(signum, _frame):
        logging.info("Received signal %s, shutting down...", signum)
        server.stop()

    try:
        signal.signal(signal.SIGINT, _sig_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _sig_handler)
    except (ValueError, OSError):
        pass

    logging.info("Starting NexusChat Server on %s:%s (Discovery UDP %s)...", host, tcp_port, disc_port)
    logging.info("Storage directory: %s", settings.FILE_DIR)
    try:
        server.start()
    except (KeyboardInterrupt, SystemExit):
        logging.info("NexusChat Server stopped by interrupt signal.")
        server.stop()
        print("\n[INFO] NexusChat Server stopped.")
        sys.exit(0)
    except Exception as exc:
        err_msg = str(exc).lower()
        if "connection refused" in err_msg or "password authentication" in err_msg or "operationalerror" in str(type(exc)).lower() or "does not exist" in err_msg:
            print_db_error_help(exc)
            sys.exit(1)
        if "already in use" in err_msg or "10048" in err_msg or "address already in use" in err_msg:
            print("\n" + "=" * 68)
            print(" [ERROR] Port Conflict Detected!")
            print("=" * 68)
            print(f" {exc}\n")
            print(" [HOW TO FIX]:")
            print(" 1. Another NexusChat server or service is already bound to this port.")
            print(" 2. Start this server with custom ports:")
            print(f"    nexuschat server --port {tcp_port + 1} --discovery-port {disc_port + 1}")
            print(" 3. Or check running tasks and stop the previous server.")
            print("=" * 68 + "\n")
            sys.exit(1)
        raise


def run_setup_db():
    print("\n--- NexusChat Database Setup Wizard ---")
    try:
        host = input("PostgreSQL Host [localhost]: ").strip() or "localhost"
        port = input("PostgreSQL Port [5433]: ").strip() or "5433"
        dbname = input("Database Name [tkinter]: ").strip() or "tkinter"
        user = input("Database User [postgres]: ").strip() or "postgres"
        import getpass
        password = getpass.getpass("Database Password [admin123]: ").strip() or "admin123"

        env_content = (
            "# ==============================================================================\n"
            "# NexusChat Server Configuration (.env)\n"
            "# ==============================================================================\n"
            "# The client never reads these values and never connects directly to PostgreSQL.\n\n"
            "# --- Database Connection (PostgreSQL) ---\n"
            f"CHAT_DB_HOST={host}\n"
            f"CHAT_DB_PORT={port}\n"
            f"CHAT_DB_NAME={dbname}\n"
            f"CHAT_DB_USER={user}\n"
            f"CHAT_DB_PASSWORD={password}\n\n"
            "# --- Networking Ports ---\n"
            "CHAT_TCP_PORT=8082\n"
            "CHAT_DISCOVERY_PORT=8083\n\n"
            "# --- Server Storage Paths ---\n"
            "CHAT_DATA_DIR=./data\n"
            "CHAT_FILE_DIR=./data/files\n\n"
            "# --- Security & Administration ---\n"
            "NEXUS_ADMIN_PASSWORD=admin123\n"
            "NEXUS_JWT_SECRET=nexuschat_secret_key_change_in_production_2026\n"
            "NEXUS_MASTER_KEY=master_recovery_key_123\n"
        )

        env_path = ROOT / ".env"
        env_path.write_text(env_content, encoding="utf-8")
        print(f"\nSaved settings to: {env_path}")

        print("\nTesting connection and running migrations...")
        os.environ["CHAT_DB_HOST"] = host
        os.environ["CHAT_DB_PORT"] = port
        os.environ["CHAT_DB_NAME"] = dbname
        os.environ["CHAT_DB_USER"] = user
        os.environ["CHAT_DB_PASSWORD"] = password

        from server.database import Database
        db = Database()
        try:
            db.connect()
            print(f"\n[OK] Successfully connected to PostgreSQL!")
            print(f"[OK] Tables created and verified for database '{dbname}'.")
            print("[OK] Default Admin account ready: username='admin', password='admin123'")
            print("     (Change password anytime via: nexuschat admin reset-password admin <new_password>)")
        except Exception as exc:
            print(f"\n[ERROR] Database connection failed: {exc}")
            sys.exit(1)
        finally:
            db.close()
        print("\nSetup complete! You can now start the server with: nexuschat server\n")
    except (KeyboardInterrupt, SystemExit):
        print("\n\n[INFO] Database setup wizard cancelled.")
        sys.exit(0)


def run_admin(args):
    from server.admin import main as admin_main
    sys.argv = [sys.argv[0]] + args
    try:
        admin_main()
    except (KeyboardInterrupt, SystemExit):
        print("\n[INFO] Admin command cancelled.")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        prog="nexuschat",
        description="NexusChat - High-Performance Cross-Platform LAN Messenger & File Sharing",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Command to run")

    subparsers.add_parser("client", help="Launch NexusChat GUI Client (default)")

    srv_parser = subparsers.add_parser("server", help="Launch NexusChat Server daemon")
    srv_parser.add_argument("--host", default="0.0.0.0", help="Listen host (default: 0.0.0.0)")
    srv_parser.add_argument("--port", type=int, default=None, help="TCP port (default from .env or 8082)")
    srv_parser.add_argument("--discovery-port", type=int, default=None, help="UDP discovery port (default from .env or 8083)")
    srv_parser.add_argument("--file-dir", default=None, help="Custom storage directory for uploaded files")

    subparsers.add_parser("setup-db", help="Interactive PostgreSQL setup wizard")
    subparsers.add_parser("recover", help="Self-service password recovery using security questions")

    admin_parser = subparsers.add_parser("admin", help="Server administration & user management")
    admin_parser.add_argument("admin_args", nargs=argparse.REMAINDER, help="Admin subcommands (login, logout, list-users, reset-password, setup-security-questions, recover-password, set-role, stats, ui)")

    try:
        # If no arguments provided, default to client
        if len(sys.argv) == 1:
            run_client()
            return

        args = parser.parse_args()

        if args.subcommand == "client" or not args.subcommand:
            run_client()
        elif args.subcommand == "server":
            run_server(host=args.host, port=args.port, discovery_port=args.discovery_port, file_dir=args.file_dir)
        elif args.subcommand == "setup-db":
            run_setup_db()
        elif args.subcommand == "recover":
            run_admin(["recover-password"])
        elif args.subcommand == "admin":
            run_admin(args.admin_args)
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)


if __name__ == "__main__":
    main()
