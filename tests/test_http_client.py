import io
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError

import pytest

from marketing_agent.http_client import NoRedirectHandler, ResponseTooLarge, opener, read_limited


class _Server:
    def __init__(self):
        self.paths: list[str] = []
        paths = self.paths

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                paths.append(self.path)
                if self.path == "/start":
                    self.send_response(302)
                    self.send_header("Location", "/target")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"ok")

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_no_redirect_returns_none_by_default():
    with _Server() as server:
        with pytest.raises(HTTPError) as caught:
            opener().open(server.url + "/start", timeout=5)
    assert caught.value.code == 302
    assert server.paths == ["/start"]
    assert "/target" not in server.paths


def test_no_redirect_raises_custom_error():
    class Blocked(Exception):
        pass

    with _Server() as server:
        with pytest.raises(Blocked):
            opener(on_redirect=lambda: Blocked("blocked")).open(server.url + "/start", timeout=5)
    assert server.paths == ["/start"]
    assert isinstance(NoRedirectHandler(), NoRedirectHandler)


def test_read_limited_rejects_oversize():
    assert read_limited(io.BytesIO(b"a" * 10), 10) == b"a" * 10
    assert read_limited(io.BytesIO(b"a" * 3), 10) == b"aaa"
    with pytest.raises(ResponseTooLarge):
        read_limited(io.BytesIO(b"a" * 11), 10)
    assert issubclass(ResponseTooLarge, ValueError)


def test_single_redirect_handler_definition():
    root = Path(__file__).resolve().parents[1] / "src" / "marketing_agent"
    pattern = re.compile(r"^\s*class\s+\w*Redirect\w*\(.*HTTPRedirectHandler.*\)", re.M)
    found = [p.name for p in root.glob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert found == ["http_client.py"]
