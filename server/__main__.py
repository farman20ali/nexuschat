import logging
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.chat_server import ChatServer
from server import settings


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    server = ChatServer()
    logging.info(
        "database %s:%s/%s  files %s",
        settings.DB_HOST,
        settings.DB_PORT,
        settings.DB_NAME,
        settings.FILE_DIR,
    )

    def _stop(signum, _frame):
        logging.info("signal %s, shutting down", signum)
        server.stop()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)
    try:
        server.start()
    except (KeyboardInterrupt, SystemExit):
        logging.info("NexusChat Server stopped by interrupt signal.")
        server.stop()
        sys.exit(0)
    except Exception as exc:
        err_msg = str(exc).lower()
        if "connection refused" in err_msg or "password authentication" in err_msg or "operationalerror" in str(type(exc)).lower() or "does not exist" in err_msg:
            from nexuschat.cli import print_db_error_help
            print_db_error_help(exc)
            sys.exit(1)
        logging.exception("server failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
