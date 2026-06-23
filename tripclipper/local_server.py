from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
import urllib.parse

from .analyzer import analyze_project
from .config import create_project_config
from .eagle import eagle_apply, eagle_dry_run
from .exporter import export_project
from .model_config import model_config_status
from .web import TASK_LOG, _home_html, _project_results_html, _project_statuses, _thumbnail_path_for_asset


def serve_simple(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), TripClipperHandler)
    print(f"TripClipper local launcher running at http://{host}:{port}")
    server.serve_forever()


class TripClipperHandler(BaseHTTPRequestHandler):
    server_version = "TripClipperHTTP/0.1"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send_html(_home_html())
            return
        if path == "/api/status":
            self._send_json({"model_config": model_config_status(), "projects": _project_statuses(), "task_log": TASK_LOG[-50:]})
            return
        project_slug = _project_results_slug(path)
        if project_slug is not None:
            try:
                self._send_html(_project_results_html(project_slug))
            except Exception as exc:
                self._send_html(f"<h1>项目结果不可用</h1><pre>{exc}</pre>", status=HTTPStatus.NOT_FOUND)
            return
        thumbnail = _thumbnail_request(path)
        if thumbnail is not None:
            slug, asset_id = thumbnail
            thumb_path = _thumbnail_path_for_asset(slug, asset_id)
            if thumb_path is None:
                self.send_error(HTTPStatus.NOT_FOUND, "Thumbnail not found")
                return
            self._send_file(thumb_path)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        payload = self._read_json()
        routes = {
            "/create-config": lambda: _create_config(payload),
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
        stage = self.path.strip("/") or "request"
        _log(stage, "开始执行。")
        try:
            result = routes[self.path]()
            _log(stage, "完成。")
            self._send_json({"ok": True, "result": result})
        except Exception as exc:
            _log(stage, str(exc), "error")
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

    def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path) -> None:
        data = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _log(stage: str, message: str, level: str = "info") -> None:
    TASK_LOG.append({"stage": stage, "level": level, "message": message})
    del TASK_LOG[:-100]


def _create_config(payload: dict[str, Any]) -> dict[str, str]:
    return {"config_path": str(create_project_config(payload))}


def _project_results_slug(path: str) -> str | None:
    prefix = "/projects/"
    if not path.startswith(prefix):
        return None
    slug = path[len(prefix) :].strip("/")
    if not slug or "/" in slug:
        return None
    return urllib.parse.unquote(slug)


def _thumbnail_request(path: str) -> tuple[str, str] | None:
    prefix = "/media/"
    suffix = "/thumbnail/"
    if not path.startswith(prefix) or suffix not in path:
        return None
    rest = path[len(prefix) :]
    slug, asset_id = rest.split(suffix, 1)
    if not slug or not asset_id or "/" in asset_id:
        return None
    return urllib.parse.unquote(slug), urllib.parse.unquote(asset_id)
