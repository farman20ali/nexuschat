import queue
import socket
import threading
from pathlib import Path

from shared.constants import BIN_CHUNK, EVERYONE, MAX_FILE_SIZE
from shared.files import safe_filename, zip_paths
from shared.protocol import Connection, ProtocolError


class ChatClient:
    def __init__(self):
        self.events = queue.Queue()
        self.username = None
        self.role = "user"
        self._conn = None
        self._thread = None
        self._alive = threading.Event()
        self._download = None
        self._download_lock = threading.Lock()

    @property
    def connected(self):
        return self._alive.is_set() and self._conn is not None

    def emit(self, kind, payload=None):
        self.events.put((kind, payload))

    def connect(self, host, port, username, password, register=False):
        self.disconnect()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.settimeout(12)
        try:
            sock.connect((host, int(port)))
        except OSError as exc:
            sock.close()
            self.emit("error", f"could not reach {host}:{port} ({exc})")
            return False
        sock.settimeout(120)
        conn = Connection(sock)
        try:
            req_type = "register" if register else "auth"
            conn.send_json({"type": req_type, "username": username.strip(), "password": password})
            frame = conn.recv_frame()
        except (OSError, ProtocolError, ValueError) as exc:
            conn.close()
            self.emit("error", f"authentication failed: {exc}")
            return False
        if frame is None or frame[0] != "json":
            conn.close()
            self.emit("error", "server closed the connection")
            return False
        reply = frame[1]
        if reply.get("type") != "auth_ok":
            conn.close()
            self.emit("auth_fail", reply.get("error") or "authentication failed")
            return False
        self._conn = conn
        self.username = username.strip()
        self.role = reply.get("role") or "user"
        self._alive.set()
        self._thread = threading.Thread(target=self._listen, daemon=True, name="chat-recv")
        self._thread.start()
        self.emit("connected", {"username": self.username, "role": self.role, "host": host, "port": int(port)})
        return True

    def disconnect(self):
        self._alive.clear()
        conn = self._conn
        self._conn = None
        if conn:
            try:
                conn.send_json({"type": "disconnect"})
            except OSError:
                pass
            conn.close()
        self._abort_download()

    def send_chat(self, recipient, body):
        text = (body or "").strip()
        if not text:
            return
        self._send({"type": "chat", "recipient": recipient or EVERYONE, "body": text})

    def send_typing(self, recipient):
        self._send({"type": "typing", "recipient": recipient or EVERYONE})

    def request_history(self):
        self._send({"type": "history_req"})

    def delete_history(self, room=None):
        self._send({"type": "history_delete", "room": room})

    def request_files(self):
        self._send({"type": "file_list_req"})

    def delete_file(self, file_id, mode="me"):
        self._send({"type": "file_delete", "file_id": file_id, "mode": mode})

    def admin_request_users(self):
        self._send({"type": "admin_users_req"})

    def admin_set_role(self, target, role):
        self._send({"type": "admin_set_role", "target": target, "role": role})

    def admin_reset_password(self, target, new_password):
        self._send({"type": "admin_reset_password", "target": target, "new_password": new_password})

    def admin_delete_user(self, target):
        self._send({"type": "admin_delete_user", "target": target})

    def admin_kick_user(self, target):
        self._send({"type": "admin_kick_user", "target": target})

    def admin_request_stats(self):
        self._send({"type": "admin_stats_req"})

    def upload_path(self, path, recipient, zip_name=None):
        path = Path(path)
        if path.is_dir():
            raise ValueError("cannot upload a directory")
        data = path.read_bytes()
        name = zip_name or path.name
        self.upload_bytes(name, data, recipient)

    def upload_many(self, paths, zip_name, recipient):
        data = zip_paths(paths)
        self.upload_bytes(safe_filename(zip_name), data, recipient)

    def upload_bytes(self, filename, data, recipient):
        if not data:
            raise ValueError("file is empty")
        if len(data) > MAX_FILE_SIZE:
            raise ValueError("file is larger than 50 MB")
        filename = safe_filename(filename)
        self._send({
            "type": "file_upload_start",
            "filename": filename,
            "size": len(data),
            "recipient": recipient or EVERYONE,
        })
        conn = self._conn
        if not conn:
            raise ConnectionError("not connected")
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + BIN_CHUNK]
            conn.send_bin(chunk)
            offset += len(chunk)
        self._send({"type": "file_upload_end"})
        self.emit("status", f"uploaded {filename}")

    def start_download(self, file_id, dest_dir):
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        with self._download_lock:
            self._download = {"dest": dest, "handle": None, "name": None, "received": 0, "size": 0}
        self._send({"type": "file_download", "file_id": file_id})

    def _listen(self):
        conn = self._conn
        try:
            while self._alive.is_set() and conn:
                frame = conn.recv_frame()
                if frame is None:
                    break
                kind, payload = frame
                if kind == "bin":
                    self._write_download(payload)
                    continue
                self._dispatch(payload)
        except (OSError, ProtocolError, ValueError) as exc:
            if self._alive.is_set():
                self.emit("error", f"connection lost: {exc}")
        finally:
            if self._alive.is_set():
                self.emit("disconnected", None)
            self._alive.clear()

    def _dispatch(self, msg):
        kind = msg.get("type")
        if kind == "file_download_start":
            self._open_download(msg)
        elif kind == "file_download_end":
            self._close_download(success=True)
        elif kind == "error":
            self._abort_download()
            self.emit("error", msg.get("error") or "server error")
        else:
            self.emit(kind, msg)

    def _open_download(self, msg):
        with self._download_lock:
            state = self._download
            if not state:
                return
            name = safe_filename(msg.get("filename") or "download")
            path = state["dest"] / name
            counter = 1
            while path.exists():
                path = state["dest"] / f"{path.stem}_{counter}{path.suffix}"
                counter += 1
            state["handle"] = path.open("wb")
            state["name"] = str(path)
            state["size"] = int(msg.get("size") or 0)
            state["received"] = 0
        self.emit("status", f"downloading {name}")

    def _write_download(self, payload):
        with self._download_lock:
            state = self._download
            if not state or not state.get("handle"):
                return
            state["handle"].write(payload)
            state["received"] += len(payload)

    def _close_download(self, success):
        path = None
        with self._download_lock:
            state = self._download
            self._download = None
            if state and state.get("handle"):
                path = state.get("name")
                try:
                    state["handle"].close()
                except OSError:
                    pass
        if success and path:
            self.emit("file_saved", path)
        elif path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass

    def _abort_download(self):
        self._close_download(success=False)

    def _send(self, payload):
        if not self._conn:
            self.emit("error", "not connected")
            return
        try:
            self._conn.send_json(payload)
        except OSError as exc:
            self.emit("error", f"send failed: {exc}")
            self.disconnect()
