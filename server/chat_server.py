import logging
import socket
import threading
from pathlib import Path

from server.database import Database
from server.file_store import FileStore
from server import settings
from shared.constants import BIN_CHUNK, EVERYONE, MAX_FILE_SIZE
from shared.discovery import run_advertiser
from shared.files import safe_filename
from shared.protocol import Connection, ProtocolError

logger = logging.getLogger(__name__)


class ChatServer:
    def __init__(self, host="0.0.0.0", port=None, discovery_port=None):
        self.host = host
        self.port = port or settings.TCP_PORT
        self.discovery_port = discovery_port or settings.DISCOVERY_PORT
        self.db = Database()
        self.files = FileStore()
        self._users = {}
        self._users_lock = threading.Lock()
        self._uploads = {}
        self._stop = threading.Event()
        self._listen_sock = None

    def start(self):
        settings.FILE_DIR.mkdir(parents=True, exist_ok=True)
        self.db.connect()
        def _advertiser_worker():
            try:
                run_advertiser(self._stop, self.port, self.discovery_port)
            except Exception as exc:
                logger.warning(
                    "LAN discovery disabled on UDP %s (%s). Specify --discovery-port <port> to advertise on an alternative port.",
                    self.discovery_port,
                    exc,
                )

        advertiser = threading.Thread(
            target=_advertiser_worker,
            daemon=True,
            name="discovery",
        )
        advertiser.start()
        logger.info("LAN discovery on UDP %s", self.discovery_port)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.host, self.port))
        except OSError as exc:
            sock.close()
            raise OSError(
                f"TCP port {self.port} is already in use! Another NexusChat server or service is running.\n"
                f"Please specify a different port: nexuschat server --port <new_port>"
            ) from exc
        sock.listen(32)
        sock.settimeout(1.0)
        self._listen_sock = sock
        logger.info("chat server listening on %s:%s", self.host, self.port)

        try:
            while not self._stop.is_set():
                try:
                    client_sock, address = sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                client_sock.settimeout(120)
                thread = threading.Thread(
                    target=self._serve_client,
                    args=(client_sock, address),
                    daemon=True,
                    name=f"client-{address[0]}:{address[1]}",
                )
                thread.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Chat server accept loop stopped by interrupt signal.")
        finally:
            self.stop()

    def stop(self):
        if self._stop.is_set() and self._listen_sock is None:
            return
        self._stop.set()
        sock = self._listen_sock
        self._listen_sock = None
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        with self._users_lock:
            sessions = list(self._users.values())
            self._users.clear()
        for session in sessions:
            try:
                session[0].close()
            except Exception:
                pass
        try:
            self.db.close()
        except Exception:
            pass

    def _serve_client(self, sock, address):
        conn = Connection(sock)
        username = None
        try:
            username = self._authenticate(conn)
            if not username:
                return
            logger.info("connected %s from %s", username, address)
            self._send_user_list()
            while not self._stop.is_set():
                frame = conn.recv_frame()
                if frame is None:
                    break
                kind, payload = frame
                if kind == "bin":
                    self._handle_binary(username, payload)
                    continue
                self._handle_json(username, conn, payload)
        except (ProtocolError, ConnectionResetError, OSError, ValueError) as exc:
            logger.info("session ended for %s (%s): %s", username or address, address, exc)
        except Exception:
            logger.exception("unexpected error for %s", address)
        finally:
            self._abort_upload(username)
            if username:
                self._drop_user(username)
            conn.close()

    def _authenticate(self, conn):
        frame = conn.recv_frame()
        if frame is None or frame[0] != "json":
            return None
        msg = frame[1]
        action_type = msg.get("type")
        if action_type not in ("auth", "register"):
            conn.send_json({"type": "auth_fail", "error": "expected auth or register"})
            return None
        username = str(msg.get("username", "")).strip()
        password = str(msg.get("password", ""))

        if action_type == "register":
            ok, error, role = self.db.register(username, password)
            must_change = False
        else:
            ok, error, role, must_change = self.db.authenticate(username, password)

        if not ok:
            conn.send_json({"type": "auth_fail", "error": error or "authentication failed"})
            return None
        with self._users_lock:
            if username in self._users:
                conn.send_json({"type": "auth_fail", "error": f"User '{username}' is already logged in"})
                return None
            self._users[username] = (conn, username, role)
        from shared.auth import create_jwt_token
        token = create_jwt_token({"sub": username, "role": role})
        conn.send_json({
            "type": "auth_ok",
            "username": username,
            "role": role,
            "token": token,
            "must_change_password": must_change,
        })
        self._send_json(conn, {"type": "file_list", "files": self._file_list_payload(username)})
        return username

    def _handle_json(self, username, conn, msg):
        kind = msg.get("type")
        if kind == "chat":
            self._handle_chat(username, msg)
        elif kind == "history_req":
            rows = self.db.history_for(username)
            conn.send_json({"type": "history", "messages": rows})
        elif kind == "history_delete":
            room = msg.get("room")
            is_admin = self._is_admin(username)
            room_norm = (str(room) if room is not None else "").strip()
            if room_norm in ("all", EVERYONE, "#general"):
                if not is_admin:
                    conn.send_json({"type": "error", "error": "Only administrators can purge the global #general chat."})
                    return
                count = self.db.delete_history(username, room=room_norm, is_admin=True)
                self._broadcast({
                    "type": "chat",
                    "sender": "system",
                    "recipient": EVERYONE,
                    "body": f"📢 Global chat history in #general was purged by Admin @{username}.",
                    "msg_type": "text",
                    "id": 0,
                    "created_at": "",
                })
                conn.send_json({"type": "history_deleted", "room": EVERYONE, "count": count})
            else:
                count = self.db.delete_history(username, room=room_norm, is_admin=is_admin)
                conn.send_json({"type": "history_deleted", "room": room_norm, "count": count})
        elif kind == "file_upload_start":
            self._start_upload(username, msg)
        elif kind == "file_upload_end":
            self._finish_upload(username)
        elif kind == "file_download":
            self._send_file(username, conn, msg.get("file_id"))
        elif kind == "file_list_req":
            conn.send_json({"type": "file_list", "files": self._file_list_payload(username)})
        elif kind == "file_delete":
            self._delete_file(username, msg.get("file_id"), mode=msg.get("mode", "me"))
        elif kind == "typing":
            recipient = str(msg.get("recipient") or EVERYONE).strip() or EVERYONE
            self._route(username, recipient, {"type": "typing", "sender": username, "recipient": recipient})
        elif kind == "admin_users_req":
            if not self._is_admin(username):
                conn.send_json({"type": "error", "error": "admin access required"})
                return
            all_users = self.db.list_all_users()
            with self._users_lock:
                online_names = set(self._users.keys())
            for u in all_users:
                u["online"] = u["username"] in online_names
            conn.send_json({"type": "admin_users", "users": all_users})
        elif kind == "admin_set_role":
            if not self._is_admin(username):
                conn.send_json({"type": "error", "error": "admin access required"})
                return
            target = str(msg.get("target") or "").strip()
            new_role = str(msg.get("role") or "").strip()
            ok, err = self.db.set_user_role(target, new_role)
            conn.send_json({"type": "admin_result", "action": "set_role", "ok": ok, "error": err, "target": target})
            if ok:
                self._send_to(target, {"type": "role_update", "role": new_role})
        elif kind == "admin_reset_password":
            if not self._is_admin(username):
                conn.send_json({"type": "error", "error": "admin access required"})
                return
            target = str(msg.get("target") or "").strip()
            new_password = str(msg.get("new_password") or "")
            ok, err = self.db.reset_password(target, new_password)
            conn.send_json({"type": "admin_result", "action": "reset_password", "ok": ok, "error": err, "target": target})
        elif kind == "admin_delete_user":
            if not self._is_admin(username):
                conn.send_json({"type": "error", "error": "admin access required"})
                return
            target = str(msg.get("target") or "").strip()
            if target == username:
                conn.send_json({"type": "admin_result", "action": "delete_user", "ok": False, "error": "cannot delete your own account", "target": target})
                return
            ok = self.db.delete_user(target)
            if ok:
                self._disconnect_user(target, "your account has been deleted by an administrator")
            conn.send_json({"type": "admin_result", "action": "delete_user", "ok": ok, "error": None if ok else "user not found", "target": target})
        elif kind == "admin_kick_user":
            if not self._is_admin(username):
                conn.send_json({"type": "error", "error": "admin access required"})
                return
            target = str(msg.get("target") or "").strip()
            if target == username:
                conn.send_json({"type": "admin_result", "action": "kick_user", "ok": False, "error": "cannot kick yourself", "target": target})
                return
            kicked = self._disconnect_user(target, "you have been kicked by an administrator")
            conn.send_json({"type": "admin_result", "action": "kick_user", "ok": kicked, "error": None if kicked else "user not online", "target": target})
        elif kind == "admin_stats_req":
            if not self._is_admin(username):
                conn.send_json({"type": "error", "error": "admin access required"})
                return
            stats = self.db.get_stats()
            with self._users_lock:
                stats["online_users"] = len(self._users)
            conn.send_json({"type": "admin_stats", "stats": stats})
        elif kind == "ping":
            conn.send_json({"type": "pong"})
        elif kind == "disconnect":
            raise ConnectionResetError("client disconnect")
        else:
            conn.send_json({"type": "error", "error": f"unknown message type: {kind}"})

    def _handle_chat(self, username, msg):
        recipient = str(msg.get("recipient") or EVERYONE).strip() or EVERYONE
        body = str(msg.get("body") or "").strip()
        if not body:
            return
        saved = self.db.save_message(username, recipient, body, "text")
        payload = {
            "type": "chat",
            "sender": username,
            "recipient": recipient,
            "body": body,
            "msg_type": "text",
            "id": saved["id"],
            "created_at": saved["created_at"].isoformat(sep=" ", timespec="seconds"),
        }
        self._route(username, recipient, payload)

    def _start_upload(self, username, msg):
        filename = safe_filename(msg.get("filename") or "file")
        size = int(msg.get("size") or 0)
        recipient = str(msg.get("recipient") or EVERYONE).strip() or EVERYONE
        if size <= 0 or size > MAX_FILE_SIZE:
            self._send_to(username, {"type": "error", "error": "file is empty or larger than 50 MB"})
            return
        temp = self.files.new_temp()
        self._uploads[username] = {
            "path": temp,
            "handle": open(temp, "wb"),
            "size": size,
            "received": 0,
            "filename": filename,
            "recipient": recipient,
        }

    def _handle_binary(self, username, payload):
        upload = self._uploads.get(username)
        if not upload:
            return
        remaining = upload["size"] - upload["received"]
        if len(payload) > remaining:
            self._abort_upload(username)
            self._send_to(username, {"type": "error", "error": "file exceeded declared size"})
            return
        upload["handle"].write(payload)
        upload["received"] += len(payload)

    def _finish_upload(self, username):
        upload = self._uploads.get(username)
        if not upload:
            self._send_to(username, {"type": "error", "error": "no upload in progress"})
            return
        try:
            upload["handle"].close()
            if upload["received"] != upload["size"]:
                Path(upload["path"]).unlink(missing_ok=True)
                self._send_to(username, {"type": "error", "error": "incomplete file upload"})
                return
            stored_name, _dest = self.files.finalize(upload["path"], upload["filename"])
            row = self.db.save_file(upload["filename"], stored_name, upload["size"], username)
            body = f"FILE: {upload['filename']}"
            saved = self.db.save_message(
                username, upload["recipient"], body, "file", file_id=row["id"]
            )
            payload = {
                "type": "chat",
                "sender": username,
                "recipient": upload["recipient"],
                "body": body,
                "msg_type": "file",
                "file_id": row["id"],
                "filename": upload["filename"],
                "size": upload["size"],
                "id": saved["id"],
                "created_at": saved["created_at"].isoformat(sep=" ", timespec="seconds"),
            }
            self._route(username, upload["recipient"], payload)
            self._refresh_file_lists(username, upload["recipient"])
        finally:
            self._uploads.pop(username, None)

    def _abort_upload(self, username):
        upload = self._uploads.pop(username, None)
        if not upload:
            return
        try:
            upload["handle"].close()
        except OSError:
            pass
        Path(upload["path"]).unlink(missing_ok=True)

    def _send_file(self, username, conn, file_id):
        try:
            file_id = int(file_id)
        except (TypeError, ValueError):
            conn.send_json({"type": "error", "error": "invalid file id"})
            return
        meta = self.db.get_file(file_id)
        if not meta:
            conn.send_json({"type": "error", "error": "file not found"})
            return
        path = self.files.path_for(meta["stored_name"])
        if not path.is_file():
            conn.send_json({"type": "error", "error": "file missing on server"})
            return
        conn.send_json({
            "type": "file_download_start",
            "file_id": file_id,
            "filename": meta["original_name"],
            "size": meta["size_bytes"],
        })
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(BIN_CHUNK)
                if not chunk:
                    break
                conn.send_bin(chunk)
        conn.send_json({"type": "file_download_end", "file_id": file_id, "filename": meta["original_name"]})

    def _delete_file(self, username, file_id, mode="me"):
        try:
            file_id = int(file_id)
        except (TypeError, ValueError):
            self._send_to(username, {"type": "error", "error": "invalid file id"})
            return
        meta = self.db.get_file(file_id)
        if not meta:
            self._send_to(username, {"type": "error", "error": "file not found"})
            return
        is_owner = meta["uploader"] == username
        is_admin = self._is_admin(username)

        if mode == "everyone":
            if not (is_owner or is_admin):
                self._send_to(username, {"type": "error", "error": "permission denied (only uploader or admin can delete for everyone)"})
                return
            stored = self.db.delete_file(file_id)
            if not stored:
                self._send_to(username, {"type": "error", "error": "could not delete file from database"})
                return
            self.files.delete(stored)
            # Refresh file lists for ALL active users
            with self._users_lock:
                active_users = list(self._users.keys())
            for user in active_users:
                self._send_to(user, {"type": "file_list", "files": self._file_list_payload(user)})
            self._broadcast({
                "type": "chat",
                "sender": "system",
                "recipient": EVERYONE,
                "body": f"File '{meta['original_name']}' was deleted for everyone by @{username}.",
                "msg_type": "text",
                "id": 0,
                "created_at": "",
            })
        else:
            # Delete for me: hide only for username
            self.db.hide_file_for_user(file_id, username)
            self._send_to(username, {"type": "file_list", "files": self._file_list_payload(username)})
            self._send_to(username, {
                "type": "chat",
                "sender": "system",
                "recipient": username,
                "body": f"File '{meta['original_name']}' was removed from your view (Delete for Me).",
                "msg_type": "text",
                "id": 0,
                "created_at": "",
            })

    def _file_list_payload(self, username):
        rows = self.db.list_files(username)
        return [
            {
                "id": row["id"],
                "name": row["original_name"],
                "size": row["size_bytes"],
                "uploader": row["uploader"],
                "created_at": row["created_at"].isoformat(sep=" ", timespec="seconds") if row["created_at"] else "",
            }
            for row in rows
        ]

    def _refresh_file_lists(self, sender, recipient):
        targets = {sender}
        if recipient == EVERYONE:
            with self._users_lock:
                targets.update(self._users.keys())
        else:
            targets.add(recipient)
        for name in targets:
            self._send_to(name, {"type": "file_list", "files": self._file_list_payload(name)})

    def _route(self, sender, recipient, payload):
        if recipient == EVERYONE:
            self._broadcast(payload)
            return
        self._send_to(sender, payload)
        if recipient != sender:
            self._send_to(recipient, payload)

    def _broadcast(self, payload):
        with self._users_lock:
            names = list(self._users.keys())
        for name in names:
            self._send_to(name, payload)

    def _send_user_list(self):
        with self._users_lock:
            users = sorted(self._users.keys())
        self._broadcast({"type": "user_list", "users": users})

    def _drop_user(self, username):
        with self._users_lock:
            self._users.pop(username, None)
        self._send_user_list()

    def _is_admin(self, username):
        role = self.db.get_user_role(username)
        return role == "admin"

    def _disconnect_user(self, target, reason="disconnected"):
        with self._users_lock:
            session = self._users.pop(target, None)
        if not session:
            return False
        conn = session[0]
        try:
            conn.send_json({"type": "error", "error": reason})
        except OSError:
            pass
        conn.close()
        self._send_user_list()
        return True

    def _send_to(self, username, payload):
        with self._users_lock:
            session = self._users.get(username)
        if not session:
            return
        conn = session[0]
        try:
            conn.send_json(payload)
        except OSError:
            logger.info("failed to send to %s", username)

    def _send_json(self, conn, payload):
        try:
            conn.send_json(payload)
        except OSError:
            pass
