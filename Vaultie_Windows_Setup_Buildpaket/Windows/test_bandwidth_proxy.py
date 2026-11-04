"""Fast offline tests for the Vaultie local bandwidth limiter."""
import socket
import socketserver
import threading
import time
import unittest

from bandwidth_proxy import LocalBandwidthProxy, SharedLimiter


class _Echo(socketserver.BaseRequestHandler):
    def handle(self):
        data = self.request.recv(1024)
        self.request.sendall(b"echo:" + data)


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class BandwidthProxyTests(unittest.TestCase):
    def test_limit_can_be_changed_and_disabled(self):
        limiter = SharedLimiter(True, 3)
        limiter.pace(75000)
        started = time.monotonic()
        limiter.pace(1)
        self.assertGreater(time.monotonic() - started, 0.12)
        limiter.configure(False, 25)
        started = time.monotonic()
        limiter.pace(500000)
        self.assertLess(time.monotonic() - started, 0.05)

    def test_local_http_proxy_connect(self):
        echo = _Server(("127.0.0.1", 0), _Echo)
        thread = threading.Thread(target=echo.serve_forever, daemon=True)
        thread.start()
        proxy = LocalBandwidthProxy(True, 25)
        try:
            with socket.create_connection(("127.0.0.1", proxy.port), timeout=3) as sock:
                sock.settimeout(3)
                request = (f"CONNECT 127.0.0.1:{echo.server_address[1]} HTTP/1.1\r\n"
                           f"Host: 127.0.0.1:{echo.server_address[1]}\r\n\r\n").encode()
                sock.sendall(request)
                response = sock.recv(4096)
                self.assertIn(b"200 Connection Established", response)
                sock.sendall(b"hello")
                self.assertIn(b"echo:hello", sock.recv(4096))
        finally:
            proxy.stop()
            echo.shutdown()
            echo.server_close()

    def test_local_plain_http_proxy(self):
        class _HTTP(socketserver.BaseRequestHandler):
            def handle(self):
                request = self.request.recv(4096)
                if b"GET /sample HTTP/1.1" not in request:
                    return
                self.request.sendall(b"HTTP/1.1 200 OK\r\n"
                                     b"Content-Length: 2\r\nConnection: close\r\n\r\nOK")
        endpoint = _Server(("127.0.0.1", 0), _HTTP)
        thread = threading.Thread(target=endpoint.serve_forever, daemon=True)
        thread.start()
        proxy = LocalBandwidthProxy(False, 10)
        try:
            with socket.create_connection(("127.0.0.1", proxy.port), timeout=3) as sock:
                sock.settimeout(3)
                target = f"127.0.0.1:{endpoint.server_address[1]}"
                sock.sendall((f"GET http://{target}/sample HTTP/1.1\r\n"
                              f"Host: {target}\r\nConnection: close\r\n\r\n").encode())
                result = bytearray()
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    result.extend(chunk)
                self.assertIn(b"200 OK", result)
                self.assertTrue(result.endswith(b"OK"))
        finally:
            proxy.stop()
            endpoint.shutdown()
            endpoint.server_close()


if __name__ == "__main__":
    unittest.main()
