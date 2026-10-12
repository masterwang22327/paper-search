"""Regress unread POST bodies corrupting the next HTTP/1.1 request."""

import http.client
import json
from pathlib import Path
import socket
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as reader


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.server = reader.ThreadingHTTPServer(("127.0.0.1", 0), reader.ReaderHandler)
        self.port = self.server.server_port
        self.state = SimpleNamespace(
            origin=f"http://127.0.0.1:{self.port}", csrf_token="current-token",
            task_id="test", propose_revision=Mock(return_value={"id": "candidate"}),
        )
        self.server.state = self.state
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_early_rejection_closes_connection_without_parsing_pending_body(self):
        cases = [
            ("old-token", "2", "", 403),
            ("current-token", str(reader.MAX_BODY + 1), "", 413),
            ("current-token", "invalid", "", 400),
            ("current-token", "2", "Transfer-Encoding: chunked\r\n", 400),
        ]
        for token, length, extra, status in cases:
            with self.subTest(token=token, length=length, extra=extra):
                with socket.create_connection(("127.0.0.1", self.port), timeout=3) as sock:
                    sock.sendall((
                        "POST /api/revision/propose HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{self.port}\r\nOrigin: {self.state.origin}\r\n"
                        f"X-Reader-Token: {token}\r\nContent-Length: {length}\r\n{extra}\r\n"
                        "{}GET /api/bootstrap HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{self.port}\r\n\r\n"
                    ).encode())
                    response = http.client.HTTPResponse(sock)
                    response.begin()
                    self.assertEqual(response.status, status)
                    self.assertEqual(response.getheader("Connection"), "close")
                    value = json.loads(response.read())
                    if status == 403:
                        self.assertEqual(value["code"], "invalid_token")
                    self.assertEqual(sock.recv(1), b"")
        self.state.propose_revision.assert_not_called()

    def test_retry_uses_new_connection_and_valid_requests_keep_alive(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        self.addCleanup(connection.close)
        headers = {"Origin": self.state.origin, "X-Reader-Token": "old-token"}
        connection.request("POST", "/api/revision/propose", "{}", headers)
        rejected = connection.getresponse()
        self.assertEqual(rejected.status, 403)
        rejected.read()
        headers["X-Reader-Token"] = self.state.csrf_token
        for _ in range(2):
            connection.request("POST", "/api/revision/propose", "{}", headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertFalse(response.will_close)
            self.assertEqual(json.loads(response.read()), {"id": "candidate"})
        self.assertEqual(self.state.propose_revision.call_count, 2)


if __name__ == "__main__":
    unittest.main()
