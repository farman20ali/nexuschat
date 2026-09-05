import logging
import os
import re

import bcrypt
import psycopg2
import psycopg2.extras
from psycopg2 import sql
from psycopg2.pool import ThreadedConnectionPool

from server import settings
from shared.constants import EVERYONE

logger = logging.getLogger(__name__)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS files (
    id SERIAL PRIMARY KEY,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE,
    size_bytes BIGINT NOT NULL,
    uploader TEXT NOT NULL,
    hidden_for TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,
    body TEXT NOT NULL,
    msg_type TEXT NOT NULL DEFAULT 'text',
    file_id INTEGER REFERENCES files(id) ON DELETE SET NULL,
    deleted_by TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages (sender);
CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages (recipient);
CREATE INDEX IF NOT EXISTS idx_files_uploader ON files (uploader);
"""


class Database:
    def __init__(self):
        self._pool = None

    def connect(self):
        self._ensure_database()
        self._pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=16,
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            dbname=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
        )
        self.create_tables()
        logger.info("PostgreSQL ready on %s:%s/%s", settings.DB_HOST, settings.DB_PORT, settings.DB_NAME)

    def close(self):
        if self._pool:
            self._pool.closeall()
            self._pool = None

    def _dsn(self, dbname):
        return dict(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            dbname=dbname,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
        )

    def _ensure_database(self):
        if not _IDENT.match(settings.DB_NAME):
            raise ValueError("invalid database name")
        try:
            conn = psycopg2.connect(**self._dsn(settings.DB_NAME))
            conn.close()
            return
        except psycopg2.OperationalError as exc:
            text = str(exc).lower()
            if "does not exist" not in text:
                raise
        admin = psycopg2.connect(**self._dsn("postgres"))
        admin.autocommit = True
        try:
            with admin.cursor() as cur:
                cur.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(settings.DB_NAME))
                )
            logger.info("created database %s", settings.DB_NAME)
        except psycopg2.errors.DuplicateDatabase:
            pass
        finally:
            admin.close()

    def create_tables(self):
        with self._cursor() as cur:
            cur.execute(SCHEMA)
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user'")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS sec_question_1 TEXT")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS sec_answer_hash_1 TEXT")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS sec_question_2 TEXT")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS sec_answer_hash_2 TEXT")
            cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS deleted_by TEXT[] NOT NULL DEFAULT '{}'")
            cur.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS hidden_for TEXT[] NOT NULL DEFAULT '{}'")
            # Ensure default admin account exists
            cur.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
            admin_row = cur.fetchone()
            if not admin_row:
                cur.execute("SELECT id FROM users WHERE username = 'admin'")
                existing_admin = cur.fetchone()
                if existing_admin:
                    cur.execute("UPDATE users SET role = 'admin' WHERE username = 'admin'")
                else:
                    default_pw = os.environ.get("NEXUS_ADMIN_PASSWORD") or os.environ.get("DEFAULT_ADMIN_PASSWORD") or "admin123"
                    hashed = bcrypt.hashpw(default_pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                    cur.execute(
                        "INSERT INTO users (username, password_hash, role) VALUES ('admin', %s, 'admin')",
                        (hashed,),
                    )
                    logger.info("Created default admin account: username='admin', password='%s'", default_pw)

    def _cursor(self):
        return _PoolCursor(self._pool)

    def authenticate(self, username, password):
        username = (username or "").strip()
        if not username or not password:
            return False, "Username and password are required", None, False
        with self._cursor() as cur:
            cur.execute("SELECT id, password_hash, role, must_change_password FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
            if not row:
                return False, f"User '{username}' not found. Please register an account.", None, False
            stored = row["password_hash"]
            if isinstance(stored, memoryview):
                stored = stored.tobytes()
            if isinstance(stored, str):
                stored = stored.encode("utf-8")
            if bcrypt.checkpw(password.encode("utf-8"), stored):
                role = row.get("role") or "user"
                must_change = bool(row.get("must_change_password"))
                return True, None, role, must_change
            return False, "Incorrect password", None, False

    def register(self, username, password):
        username = (username or "").strip()
        if not username or not password:
            return False, "Username and password are required", None
        if len(username) < 3 or len(username) > 32:
            return False, "Username must be between 3 and 32 characters", None
        if len(password) < 4:
            return False, "Password must be at least 4 characters", None
        if "|" in username or " " in username:
            return False, "Username cannot contain spaces or '|'", None
        with self._cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                return False, f"Username '{username}' is already taken", None
            cur.execute("SELECT COUNT(*) AS total FROM users")
            total = cur.fetchone()["total"]
            role = "admin" if (total == 0 or username.lower() == "admin") else "user"
            hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (username, hashed, role),
            )
        return True, None, role

    def authenticate_or_register(self, username, password):
        ok, err, role = self.authenticate(username, password)
        if ok:
            return True, None, role
        if "not found" in (err or "").lower():
            return self.register(username, password)
        return False, err, None

    def save_message(self, sender, recipient, body, msg_type="text", file_id=None):
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages (sender, recipient, body, msg_type, file_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (sender, recipient, body, msg_type, file_id),
            )
            return cur.fetchone()

    def history_for(self, username, limit=200):
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT m.id, m.sender, m.recipient, m.body, m.msg_type, m.file_id,
                       m.created_at, f.original_name
                FROM messages m
                LEFT JOIN files f ON f.id = m.file_id
                WHERE (m.sender = %s OR m.recipient = %s OR m.recipient = 'all')
                  AND NOT (%s = ANY(m.deleted_by))
                ORDER BY m.id DESC
                LIMIT %s
                """,
                (username, username, username, limit),
            )
            rows = cur.fetchall()
        rows.reverse()
        return [self._row_to_message(row) for row in rows]

    def delete_history(self, username, room=None, is_admin=False):
        with self._cursor() as cur:
            room_norm = (room or "").strip()
            if room_norm in ("all", "everyone", EVERYONE, "#general"):
                if not is_admin:
                    return 0
                cur.execute("DELETE FROM messages WHERE recipient = 'all'")
                return cur.rowcount

            if room_norm:
                # Purge DM conversation with specific user - only hide for 'username'
                cur.execute(
                    """
                    UPDATE messages
                    SET deleted_by = array_append(deleted_by, %s)
                    WHERE ((sender = %s AND recipient = %s) OR (sender = %s AND recipient = %s))
                      AND NOT (%s = ANY(deleted_by))
                    """,
                    (username, username, room_norm, room_norm, username, username),
                )
                return cur.rowcount

            # Purge all conversations for username (delete for me only)
            cur.execute(
                """
                UPDATE messages
                SET deleted_by = array_append(deleted_by, %s)
                WHERE (sender = %s OR recipient = %s)
                  AND recipient != 'all'
                  AND NOT (%s = ANY(deleted_by))
                """,
                (username, username, username, username),
            )
            return cur.rowcount

    def save_file(self, original_name, stored_name, size_bytes, uploader):
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO files (original_name, stored_name, size_bytes, uploader)
                VALUES (%s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (original_name, stored_name, size_bytes, uploader),
            )
            return cur.fetchone()

    def get_file(self, file_id):
        with self._cursor() as cur:
            cur.execute("SELECT * FROM files WHERE id = %s", (file_id,))
            return cur.fetchone()

    def list_files(self, username):
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT f.id, f.original_name, f.size_bytes, f.uploader, f.created_at
                FROM files f
                LEFT JOIN messages m ON m.file_id = f.id
                WHERE (f.uploader = %s
                   OR m.recipient = %s
                   OR m.recipient = 'all'
                   OR m.sender = %s)
                   AND NOT (%s = ANY(f.hidden_for))
                ORDER BY f.id DESC
                LIMIT 100
                """,
                (username, username, username, username),
            )
            return cur.fetchall()

    def hide_file_for_user(self, file_id, username):
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE files
                SET hidden_for = array_append(hidden_for, %s)
                WHERE id = %s AND NOT (%s = ANY(hidden_for))
                """,
                (username, file_id, username),
            )
            return cur.rowcount > 0

    def delete_file(self, file_id, username=None):
        with self._cursor() as cur:
            if username:
                cur.execute(
                    "SELECT stored_name FROM files WHERE id = %s AND uploader = %s",
                    (file_id, username),
                )
            else:
                cur.execute("SELECT stored_name FROM files WHERE id = %s", (file_id,))
            row = cur.fetchone()
            if not row:
                return None
            cur.execute("DELETE FROM files WHERE id = %s", (file_id,))
            return row["stored_name"]

    def get_user_role(self, username):
        with self._cursor() as cur:
            cur.execute("SELECT role FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
            return (row.get("role") or "user") if row else None

    def list_all_users(self):
        with self._cursor() as cur:
            cur.execute("SELECT id, username, role, created_at FROM users ORDER BY id ASC")
            rows = cur.fetchall()
            return [
                {
                    "id": r["id"],
                    "username": r["username"],
                    "role": r.get("role") or "user",
                    "created_at": r["created_at"].isoformat(sep=" ", timespec="seconds") if r.get("created_at") else "",
                }
                for r in rows
            ]

    def set_user_role(self, username, role):
        if role not in ("admin", "user"):
            return False, "invalid role (must be admin or user)"
        with self._cursor() as cur:
            cur.execute("UPDATE users SET role = %s WHERE username = %s", (role, username))
            return cur.rowcount > 0, None

    def reset_password(self, username, new_password, must_change=False):
        if not new_password or len(new_password) < 4:
            return False, "password must be at least 4 characters"
        hashed = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s, must_change_password = %s WHERE username = %s",
                (hashed, must_change, username),
            )
            return cur.rowcount > 0, None

    def change_password(self, username, old_password, new_password):
        ok, err, role, _must_change = self.authenticate(username, old_password)
        if not ok:
            return False, f"Old password verification failed: {err}"
        return self.reset_password(username, new_password, must_change=False)

    def set_security_questions(self, username, q1, a1, q2, a2):
        from shared.auth import hash_security_answer
        hash_1 = hash_security_answer(a1)
        hash_2 = hash_security_answer(a2)
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET sec_question_1 = %s, sec_answer_hash_1 = %s,
                    sec_question_2 = %s, sec_answer_hash_2 = %s
                WHERE username = %s
                """,
                (q1, hash_1, q2, hash_2, username),
            )
            return cur.rowcount > 0, None

    def get_security_questions(self, username):
        with self._cursor() as cur:
            cur.execute(
                "SELECT sec_question_1, sec_question_2, sec_answer_hash_1, sec_answer_hash_2 FROM users WHERE username = %s",
                (username,),
            )
            row = cur.fetchone()
            if not row:
                return None, None, False
            q1 = row.get("sec_question_1") or "What is your recovery security answer #1?"
            q2 = row.get("sec_question_2") or "What is your recovery security answer #2?"
            configured = bool(row.get("sec_answer_hash_1") and row.get("sec_answer_hash_2"))
            return q1, q2, configured

    def verify_security_answers(self, username, a1, a2):
        from shared.auth import verify_security_answer
        with self._cursor() as cur:
            cur.execute(
                "SELECT sec_answer_hash_1, sec_answer_hash_2 FROM users WHERE username = %s",
                (username,),
            )
            row = cur.fetchone()
            if not row or not row.get("sec_answer_hash_1") or not row.get("sec_answer_hash_2"):
                return False, "Security questions are not configured for this user"
            ok1 = verify_security_answer(a1, row["sec_answer_hash_1"])
            ok2 = verify_security_answer(a2, row["sec_answer_hash_2"])
            if ok1 and ok2:
                return True, None
            return False, "Incorrect security question answers"

    def delete_user(self, username):
        with self._cursor() as cur:
            cur.execute("DELETE FROM messages WHERE sender = %s OR recipient = %s", (username, username))
            cur.execute("DELETE FROM files WHERE uploader = %s", (username,))
            cur.execute("DELETE FROM users WHERE username = %s", (username,))
            return cur.rowcount > 0

    def get_stats(self):
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total_users FROM users")
            users = cur.fetchone()["total_users"]
            cur.execute("SELECT COUNT(*) AS total_messages FROM messages")
            messages = cur.fetchone()["total_messages"]
            cur.execute("SELECT COUNT(*) AS total_files, COALESCE(SUM(size_bytes), 0) AS total_bytes FROM files")
            files_row = cur.fetchone()
            return {
                "users": users,
                "messages": messages,
                "files": files_row["total_files"],
                "bytes": int(files_row["total_bytes"]),
            }

    @staticmethod
    def _row_to_message(row):
        created = row["created_at"]
        return {
            "id": row["id"],
            "sender": row["sender"],
            "recipient": row["recipient"],
            "body": row["body"],
            "msg_type": row["msg_type"],
            "file_id": row["file_id"],
            "filename": row.get("original_name"),
            "created_at": created.isoformat(sep=" ", timespec="seconds") if created else "",
        }


class _PoolCursor:
    def __init__(self, pool):
        self.pool = pool
        self.conn = None
        self.cur = None

    def __enter__(self):
        self.conn = self.pool.getconn()
        self.cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return self.cur

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()
        finally:
            if self.cur:
                self.cur.close()
            self.pool.putconn(self.conn)
        return False
