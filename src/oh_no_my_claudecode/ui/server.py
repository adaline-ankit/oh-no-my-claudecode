from __future__ import annotations

import json
import mimetypes
import webbrowser
from collections import defaultdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from ipaddress import ip_address
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from oh_no_my_claudecode.core.repo import path_bucket
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import FileStat, RepoFileRecord, TaskStatus

STATIC_ROOT = files("oh_no_my_claudecode.ui").joinpath("static")


def build_dashboard_payload(service: OnmcService) -> dict[str, Any]:
    status = service.status()
    memories = service.list_memories()
    tasks = service.list_tasks()
    repo_files = service.list_repo_files()
    file_stats = service.list_file_stats()
    attempt_counts = service.attempt_counts_by_task()
    artifact_counts = service.memory_artifact_counts_by_task()
    output_counts = service.task_output_counts_by_task()
    _, health = service.doctor()

    memory_rows = [memory.model_dump(mode="json") for memory in memories]
    task_rows = []
    for task in tasks:
        row = task.model_dump(mode="json")
        row.update(
            {
                "attempt_count": attempt_counts.get(task.task_id, 0),
                "artifact_count": artifact_counts.get(task.task_id, 0),
                "output_count": output_counts.get(task.task_id, 0),
            }
        )
        task_rows.append(row)

    errors = health.get("errors", [])
    warnings = health.get("warnings", [])
    return {
        "repo": {
            "name": Path(status["repo_root"]).name,
            "root": status["repo_root"],
            "last_ingest_at": status["last_ingest_at"],
        },
        "summary": {
            "memories": len(memory_rows),
            "tasks": len(task_rows),
            "active_tasks": sum(task.status == TaskStatus.ACTIVE for task in tasks),
            "attempts": int(status["attempts"]),
            "artifacts": int(status["memory_artifacts"]),
            "files": len(repo_files),
        },
        "memory_kinds": _memory_kind_counts(memory_rows),
        "memories": memory_rows,
        "tasks": task_rows,
        "codegraph": _codegraph_payload(repo_files, file_stats),
        "health": {
            "readiness": "ready" if not errors and not warnings else "needs_attention",
            "sections": health,
            "warnings": warnings,
            "errors": errors,
        },
        "report": service.agent_readiness_report(),
    }


def create_ui_server(
    service: OnmcService,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    handler = _handler_factory(service)
    return ThreadingHTTPServer((host, port), handler)


def export_dashboard_snapshot(service: OnmcService, output: Path) -> Path:
    """Write a self-contained dashboard HTML snapshot and return its absolute path."""
    index = STATIC_ROOT.joinpath("index.html").read_text(encoding="utf-8")
    styles = STATIC_ROOT.joinpath("styles.css").read_text(encoding="utf-8")
    javascript = STATIC_ROOT.joinpath("app.js").read_text(encoding="utf-8")
    payload = json.dumps(build_dashboard_payload(service), separators=(",", ":"))
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")

    index = index.replace(
        '<meta name="color-scheme" content="light">',
        '<meta name="color-scheme" content="light">\n'
        '    <meta http-equiv="Content-Security-Policy" '
        'content="default-src \'none\'; style-src \'unsafe-inline\'; '
        'script-src \'unsafe-inline\'">',
    )
    index = index.replace(
        '<link rel="stylesheet" href="/assets/styles.css">',
        f"<style>\n{styles}\n    </style>",
    )
    index = index.replace(
        '<script src="/assets/app.js" defer></script>',
        '<script id="onmc-dashboard-data" type="application/json">'
        f"{payload}</script>\n    <script>\n{javascript}\n    </script>",
    )

    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(index, encoding="utf-8")
    return destination


def serve_dashboard(
    service: OnmcService,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    server = create_ui_server(service, host=host, port=port)
    raw_host, bound_port = server.server_address[:2]
    bound_host = bytes(raw_host).decode() if isinstance(raw_host, (bytes, bytearray)) else raw_host
    browser_host = "127.0.0.1" if ip_address(bound_host).is_unspecified else bound_host
    url = f"http://{browser_host}:{bound_port}"
    print(f"ONMC dashboard: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _handler_factory(service: OnmcService) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/api/dashboard":
                self._send_json(build_dashboard_payload(service))
                return
            asset = _asset_for_path(path)
            if asset is None or not asset.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            body = asset.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return DashboardHandler


def _asset_for_path(path: str) -> Any | None:
    asset_map = {
        "/": "index.html",
        "/index.html": "index.html",
        "/assets/styles.css": "styles.css",
        "/assets/app.js": "app.js",
    }
    asset_name = asset_map.get(path)
    if asset_name is None or PurePosixPath(path).parts.count(".."):
        return None
    return STATIC_ROOT.joinpath(asset_name)


def _memory_kind_counts(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    for memory in memories:
        counts[str(memory["kind"])] += 1
    return [
        {"kind": kind, "count": count}
        for kind, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _codegraph_payload(
    repo_files: list[RepoFileRecord],
    file_stats: list[FileStat],
) -> dict[str, list[dict[str, Any]]]:
    stats_by_path = {stat.path: stat for stat in file_stats}
    directories: dict[str, dict[str, Any]] = {}
    file_rows: list[dict[str, Any]] = []
    for record in repo_files:
        stat = stats_by_path.get(record.path)
        churn = stat.change_count if stat else 0
        recent = stat.recent_change_count if stat else 0
        bucket = path_bucket(record.path)
        directory = directories.setdefault(
            bucket,
            {"path": bucket, "files": 0, "tests": 0, "churn": 0, "bytes": 0},
        )
        directory["files"] += 1
        directory["tests"] += int(record.is_test)
        directory["churn"] += churn + recent
        directory["bytes"] += record.size_bytes
        file_rows.append(
            {
                "path": record.path,
                "directory": bucket,
                "is_test": record.is_test,
                "bytes": record.size_bytes,
                "churn": churn,
                "recent_churn": recent,
                "score": recent * 5 + churn * 3 + min(record.size_bytes / 4096, 8),
            }
        )
    return {
        "directories": sorted(
            directories.values(),
            key=lambda item: (item["churn"], item["files"]),
            reverse=True,
        ),
        "files": sorted(file_rows, key=lambda item: item["score"], reverse=True),
    }
