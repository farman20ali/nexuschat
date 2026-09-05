import json
import socket
import time

from shared.constants import (
    DISCOVER_MAGIC,
    DISCOVERY_PORT,
    LEGACY_DISCOVER_MAGIC,
    LEGACY_REPLY_PREFIX,
    REPLY_PREFIX,
    TCP_PORT,
)


def local_ip():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        probe.close()


def _enable_reuse(sock):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass


def _broadcast_targets(discovery_port):
    targets = {("255.255.255.255", discovery_port), ("<broadcast>", discovery_port)}
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM):
            ip = item[4][0]
            if ip.startswith("127."):
                continue
            parts = ip.split(".")
            if len(parts) == 4:
                targets.add((".".join(parts[:3] + ["255"]), discovery_port))
    except OSError:
        pass
    return list(targets)


def run_advertiser(stop_event, tcp_port=TCP_PORT, discovery_port=DISCOVERY_PORT):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _enable_reuse(sock)
    try:
        sock.bind(("0.0.0.0", discovery_port))
    except OSError as exc:
        raise RuntimeError(f"discovery port {discovery_port} is already in use") from exc
    sock.settimeout(0.5)
    hostname = socket.gethostname()
    ip = local_ip()
    try:
        while not stop_event.is_set():
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            clean_data = data.strip()
            if clean_data != DISCOVER_MAGIC and clean_data != LEGACY_DISCOVER_MAGIC:
                continue
            payload = json.dumps({
                "service": "nexuschat",
                "host": hostname,
                "ip": ip,
                "port": tcp_port,
            }).encode("utf-8")
            try:
                # Reply with matching prefix
                prefix = LEGACY_REPLY_PREFIX if clean_data == LEGACY_DISCOVER_MAGIC else REPLY_PREFIX
                sock.sendto(prefix + payload, addr)
            except OSError:
                continue
    finally:
        sock.close()


def find_servers(discovery_port=DISCOVERY_PORT, timeout=1.8):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _enable_reuse(sock)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.4)
    try:
        sock.bind(("", 0))
    except OSError:
        pass
    for target in _broadcast_targets(discovery_port):
        try:
            sock.sendto(DISCOVER_MAGIC, target)
            sock.sendto(LEGACY_DISCOVER_MAGIC, target)
        except OSError:
            continue
    found = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        except OSError:
            break
        prefix = None
        if data.startswith(REPLY_PREFIX):
            prefix = REPLY_PREFIX
        elif data.startswith(LEGACY_REPLY_PREFIX):
            prefix = LEGACY_REPLY_PREFIX
        if not prefix:
            continue
        try:
            info = json.loads(data[len(prefix):].decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        info["ip"] = info.get("ip") or addr[0]
        found[info["ip"]] = info
    sock.close()
    return list(found.values())
