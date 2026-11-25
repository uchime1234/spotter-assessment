"""Loopback-only, deterministic OSRM response for the fictional assessment demo."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

DEMO_ROUTE = "/route/v1/driving/-95.992800,36.154000;-84.512000,39.103100"


class DemoProvider(BaseHTTPRequestHandler):
    def do_GET(self):
        if urlsplit(self.path).path == DEMO_ROUTE:
            status = 200
            body = {
                "code": "Ok",
                "routes": [{"distance": 620 * 1609.344, "geometry": {
                    "type": "LineString",
                    "coordinates": [[-95.9928, 36.154], [-91.5, 38.0], [-84.512, 39.1031]],
                }}],
            }
        else:
            status = 400
            body = {"code": "NoRoute"}
        content = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


if __name__ == "__main__":
    with HTTPServer(("127.0.0.1", 8767), DemoProvider) as server:
        server.serve_forever()
