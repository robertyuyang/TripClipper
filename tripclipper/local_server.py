from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .analyzer import analyze_project
from .config import create_project_config
from .eagle import eagle_apply, eagle_dry_run
from .exporter import export_project
from .web import TASK_LOG, _home_html, _project_statuses


def serve_simple(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), TripClipperHandler)
    print(f"TripClipper local launcher running at http://{host}:{port}")
    server.serve_forever()


class TripClipperHandler(BaseHTTPRequestHandler):
    server_version = "TripClipperHTTP/0.1"

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            self._send_html(_home_html())
            return
        if self.path == "/api/status":
            self._send_json({"projects": _project_statuses(), "task_log": TASK_LOG[-50:]})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        payload = self._read_json()
        routes = {
            "/create-config": lambda: {"config_path": str(create_project_config(payload))},
            "/scan": lambda: analyze_project(payload["config_path"], "scan"),
            "/analyze": lambda: analyze_project(
                payload["config_path"],
                payload.get("stage") or "sample",
                force=bool(payload.get("force")),
            ),
            "/export": lambda: export_project(payload["project"]),
            "/sync-eagle": lambda: eagle_apply(payload["project"])
            if payload.get("mode") == "apply"
            else eagle_dry_run(payload["project"]),
        }
        if self.path not in routes:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        try:
            result = routes[self.path]()
            _log(self.path.strip("/") or "request", "完成。")
            self._send_json({"ok": True, "result": result})
        except Exception as exc:
            _log(self.path.strip("/") or "request", str(exc), "error")
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _log(stage: str, message: str, level: str = "info") -> None:
    TASK_LOG.append({"stage": stage, "level": level, "message": message})
    del TASK_LOG[:-100]
