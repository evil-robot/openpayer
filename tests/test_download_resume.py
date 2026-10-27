import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from openpayer.ingest.discover import download_to_temp

BODY = bytes(range(256)) * 800  # 204,800 bytes
_state = {"dropped": False}


class _DropOnce(BaseHTTPRequestHandler):
    def do_GET(self):
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            start = int(rng.removeprefix("bytes=").split("-")[0])
            chunk = BODY[start:]
            self.send_response(206)
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Content-Range", f"bytes {start}-{len(BODY) - 1}/{len(BODY)}")
            self.end_headers()
            self.wfile.write(chunk)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        if not _state["dropped"]:
            _state["dropped"] = True
            self.wfile.write(BODY[:50_000])
            self.connection.close()  # body truncated: client must resume
            return
        self.wfile.write(BODY)

    def log_message(self, *args):
        pass


def test_download_resumes_after_mid_body_drop():
    _state["dropped"] = False
    server = HTTPServer(("127.0.0.1", 0), _DropOnce)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        path = download_to_temp(f"http://127.0.0.1:{port}/file.json.gz")
        try:
            assert path.read_bytes() == BODY
        finally:
            path.unlink(missing_ok=True)
    finally:
        server.shutdown()
