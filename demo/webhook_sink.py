"""Demo webhook receiver. Status: prototype. Prints each alert it receives. Standard library only."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

received = 0


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        global received
        length = min(int(self.headers.get("Content-Length") or 0), 65536)
        try:
            alert = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self.send_response(400)
            self.end_headers()
            return
        received += 1
        print(f"alert {received}: {alert.get('text', alert)}", flush=True)
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        body = json.dumps({"received": received}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("webhook sink listening on :8080", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
