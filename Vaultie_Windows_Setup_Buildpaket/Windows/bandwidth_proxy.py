"""Local, in-memory bandwidth limiter for Vaultie's HTTP/HTTPS browser traffic.

Only listens on 127.0.0.1. It does not inspect decrypted HTTPS traffic, log
browsing addresses, or use an external proxy service. The limiter is global
across simultaneous proxy connections, and limits total upload + download.
"""
import select
import socket
import socketserver
import threading
import time
from urllib.parse import urlsplit

CHUNK_SIZE = 8192
MAX_HEADER = 65536


class SharedLimiter:
    def __init__(self, enabled=False, megabits=10):
        self._lock = threading.Lock()
        self._enabled = bool(enabled)
        self._mbps = max(3, min(25, int(megabits)))
        self._next_slot = time.monotonic()

    def configure(self, enabled, megabits):
        with self._lock:
            self._enabled = bool(enabled)
            self._mbps = max(3, min(25, int(megabits)))
            self._next_slot = time.monotonic()

    def pace(self, size):
        with self._lock:
            if not self._enabled:
                return
            rate = self._mbps * 1_000_000 / 8.0
            now = time.monotonic()
            scheduled = max(now, self._next_slot)
            self._next_slot = scheduled + size / rate
        wait = scheduled - now
        if wait > 0:
            time.sleep(wait)


class _LocalHTTPProxy(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        client.settimeout(20)
        buffer = bytearray()
        while b"\r\n\r\n" not in buffer:
            data = client.recv(4096)
            if not data:
                return
            buffer.extend(data)
            if len(buffer) > MAX_HEADER:
                client.sendall(b"HTTP/1.1 431 Request Header Fields Too Large\r\nConnection: close\r\n\r\n")
                return

        head, body = bytes(buffer).split(b"\r\n\r\n", 1)
        lines = head.split(b"\r\n")
        try:
            method, target, version = lines[0].decode("ascii").split(" ", 2)
            if version not in ("HTTP/1.0", "HTTP/1.1"):
                raise ValueError("HTTP version")
            if method == "CONNECT":
                endpoint = urlsplit("//" + target)
                host, port = endpoint.hostname, endpoint.port
                if not host or not port:
                    raise ValueError("CONNECT target")
                outgoing = b""
            else:
                parsed = urlsplit(target)
                if parsed.scheme != "http" or not parsed.hostname:
                    raise ValueError("Proxy supports HTTP and HTTPS CONNECT only")
                host, port = parsed.hostname, parsed.port or 80
                relative = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
                first = (method + " " + relative + " " + version).encode("ascii")
                filtered = [line for line in lines[1:]
                            if not line.lower().startswith(b"proxy-connection:")]
                outgoing = b"\r\n".join([first, *filtered]) + b"\r\n\r\n" + body
            if not (1 <= port <= 65535):
                raise ValueError("Port")
        except (ValueError, UnicodeDecodeError):
            client.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
            return

        try:
            remote = socket.create_connection((host, port), timeout=15)
        except OSError:
            try:
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            return

        with remote:
            remote.settimeout(None)
            client.settimeout(None)
            try:
                if method == "CONNECT":
                    client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    if body:
                        self.server.limiter.pace(len(body))
                        remote.sendall(body)
                else:
                    self._forward(remote, outgoing)
                peers = (client, remote)
                while True:
                    readable, _, _ = select.select(peers, (), (), None)
                    for source in readable:
                        data = source.recv(CHUNK_SIZE)
                        if not data:
                            return
                        destination = remote if source is client else client
                        self._forward(destination, data)
            except (OSError, ValueError):
                return

    def _forward(self, destination, payload):
        if not payload:
            return
        for offset in range(0, len(payload), CHUNK_SIZE):
            part = payload[offset:offset + CHUNK_SIZE]
            self.server.limiter.pace(len(part))
            destination.sendall(part)


class LocalBandwidthProxy:
    def __init__(self, enabled=False, mbps=10):
        self.limiter = SharedLimiter(enabled, mbps)
        self.server = _LocalHTTPProxy(("127.0.0.1", 0), _Handler)
        self.server.limiter = self.limiter
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       name="VaultieLocalBandwidthProxy", daemon=True)
        self.thread.start()

    def configure(self, enabled, mbps):
        self.limiter.configure(enabled, mbps)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
