import json
import struct
import threading

from shared.constants import MAX_FRAME

JSON_FRAME = 1
BIN_FRAME = 2
_HEADER = struct.Struct("!BI")


class ProtocolError(Exception):
    pass


class Connection:
    """Length-prefixed frames: type (1 byte) + length (4 bytes) + payload."""

    def __init__(self, sock):
        self.sock = sock
        self._send_lock = threading.Lock()

    def send_json(self, obj):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send_frame(JSON_FRAME, payload)

    def send_bin(self, data):
        self._send_frame(BIN_FRAME, data)

    def _send_frame(self, frame_type, payload):
        if len(payload) > MAX_FRAME:
            raise ProtocolError("payload exceeds maximum frame size")
        header = _HEADER.pack(frame_type, len(payload))
        with self._send_lock:
            self.sock.sendall(header + payload)

    def recv_frame(self):
        header = self._recv_exact(_HEADER.size)
        if header is None:
            return None
        frame_type, length = _HEADER.unpack(header)
        if length > MAX_FRAME:
            raise ProtocolError("incoming frame is too large")
        payload = self._recv_exact(length)
        if payload is None:
            return None
        if frame_type == JSON_FRAME:
            return ("json", json.loads(payload.decode("utf-8")))
        if frame_type == BIN_FRAME:
            return ("bin", payload)
        raise ProtocolError("unknown frame type")

    def _recv_exact(self, size):
        buf = bytearray()
        while len(buf) < size:
            try:
                chunk = self.sock.recv(size - len(buf))
            except (OSError, ConnectionResetError):
                return None
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    def close(self):
        try:
            self.sock.shutdown(2)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
