from __future__ import annotations

import dataclasses
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
from oh_no_my_claudecode.missioncontrol import build_dashboard, list_swarm_ids
from oh_no_my_claudecode.models import FileStat, RepoFileRecord, TaskStatus

# Unit lifecycle states that mean "an agent is working right now".
_LIVE_UNIT_STATES = frozenset({"pending", "queued", "running"})

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
        "loops": _loops_payload(service),
        "swarms": _swarms_payload(Path(status["repo_root"])),
        "performance": _performance_payload(Path(status["repo_root"])),
        "scorecard": _scorecard_payload(Path(status["repo_root"])),
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


def _loops_payload(service: OnmcService) -> dict[str, Any]:
    """Build the loops section for the dashboard payload.

    Always returns a dict with ``evolution`` and ``recent_runs`` keys.
    Any failure (missing receipts dir, no runs, import error) returns the
    safe empty default so the dashboard never 500s.
    """
    _empty: dict[str, Any] = {"evolution": None, "recent_runs": []}
    try:
        _repo_root, report = service.evolution()
        evolution_dict = dataclasses.asdict(report)
        # Trim the large nested `runs` list — we expose only aggregates here.
        evolution_dict.pop("runs", None)
        evolution_dict.pop("run_summary", None)

        recent_runs: list[dict[str, Any]] = []
        receipts_dir = _repo_root / ".agent-memory" / "receipts"
        if receipts_dir.exists() and receipts_dir.is_dir():
            entries = sorted(receipts_dir.iterdir(), reverse=True)
            for entry in entries:
                if entry.suffix != ".json":
                    continue
                try:
                    data: dict[str, Any] = json.loads(
                        entry.read_text(encoding="utf-8")
                    )
                    if not isinstance(data, dict):
                        continue
                    goal_raw = str(data.get("goal") or "")
                    recent_runs.append(
                        {
                            "goal": goal_raw[:80],
                            "agent": str(data.get("agent") or "unknown"),
                            "verified": bool(data.get("verified", False)),
                            "iterations": int(data.get("iterations", 0)),
                            "tokens": int(data.get("tokens_used", 0)),
                            "cost_usd": data.get("cost_usd"),
                            "when": data.get("ended_at") or data.get("started_at"),
                            "receipt_hash_short": entry.stem[-8:],
                        }
                    )
                except (OSError, json.JSONDecodeError, ValueError, TypeError):
                    continue
                if len(recent_runs) >= 10:  # noqa: PLR2004
                    break

        return {"evolution": evolution_dict, "recent_runs": recent_runs}
    except Exception:  # noqa: BLE001
        return _empty


def _swarms_payload(repo_root: Path) -> dict[str, Any]:
    """Live view of every onmc swarm: units, states, verified flags, cost.

    Reads ``.onmc/swarm/<id>/manifest.json`` + receipts via the missioncontrol
    reader — the same source ``onmc missioncontrol`` uses. A swarm is *live*
    when its ABORT-less ACTIVE sentinel is present or any unit is still
    pending/queued/running (an agent working right now). Any failure returns a
    safe empty default so the dashboard never 500s.
    """
    empty: dict[str, Any] = {
        "summary": {
            "swarms": 0,
            "live": 0,
            "running_units": 0,
            "verified_units": 0,
            "total_units": 0,
            "total_cost_usd": 0.0,
        },
        "swarms": [],
    }
    try:
        state_dir = repo_root / ".onmc" / "swarm"
        if not state_dir.is_dir():
            return empty

        swarms: list[dict[str, Any]] = []
        live = running_units = verified_units = total_units = 0
        total_cost = 0.0
        for swarm_id in list_swarm_ids(state_dir):
            model = build_dashboard(state_dir, swarm_id)
            if not model.exists:
                continue
            row = model.to_dict()
            unit_running = sum(1 for u in model.units if u.state in _LIVE_UNIT_STATES)
            # Live = an agent still has work in flight. The ACTIVE sentinel alone
            # is unreliable (it persists after a swarm finishes), so liveness is
            # driven by unit state; we surface aborted separately.
            is_live = unit_running > 0 and not row.get("aborted", False)
            row["live"] = is_live
            row["running_units"] = unit_running
            row["cost_usd"] = round(sum(u.cost_usd for u in model.units), 4)
            # A one-line label: the shared parent goal of the swarm's units.
            row["label"] = _swarm_label([u.goal for u in model.units])
            # Enrich each unit with a compact receipt summary for the drilldown.
            for unit in row.get("units", []):
                unit.update(_unit_receipt_extra(state_dir, unit.get("receipt_path")))
            swarms.append(row)

            total_units += model.total
            verified_units += model.verified_count
            running_units += unit_running
            total_cost += row["cost_usd"]
            if is_live:
                live += 1

        # Most-recent (or live) first: live swarms on top, then by started_at desc.
        swarms.sort(key=lambda s: (s.get("live", False), s.get("started_at") or ""), reverse=True)
        return {
            "summary": {
                "swarms": len(swarms),
                "live": live,
                "running_units": running_units,
                "verified_units": verified_units,
                "total_units": total_units,
                "total_cost_usd": round(total_cost, 4),
            },
            "swarms": swarms,
        }
    except Exception:  # noqa: BLE001
        return empty


def _scorecard_payload(repo_root: Path) -> dict[str, Any]:
    """The shareable agent-readiness + trust scorecard (roast/registry/flywheel/orggraph).

    Reuses ``scorecard.build_scorecard`` (each signal degrades to ``None`` with a
    note). Returns the scorecard dict plus its shareable markdown. Never 500s.
    """
    try:
        from oh_no_my_claudecode.scorecard import build_scorecard, render_markdown

        card = build_scorecard(repo_root)
        payload = card.to_dict()
        payload["markdown"] = render_markdown(card)
        return payload
    except Exception:  # noqa: BLE001
        return {"readiness": None, "notes": [], "markdown": ""}


def _performance_payload(repo_root: Path) -> dict[str, Any]:
    """How the agents perform: model win-rates (flywheel) + fleet cost (ledger).

    Reuses the flywheel trajectory analysis and the ledger accounting over the
    same run receipts. Any failure returns a safe empty default (never 500s).
    """
    empty: dict[str, Any] = {"flywheel": None, "ledger": None}
    try:
        from oh_no_my_claudecode.flywheel import load_trajectories, recommend, summarize
        from oh_no_my_claudecode.ledger.accounting import load_receipts, summarize_receipts

        report = summarize(load_trajectories(repo_root))
        rate = round(report.verified_total / report.total, 4) if report.total else 0.0
        flywheel = {
            "total": report.total,
            "verified_total": report.verified_total,
            "verified_rate": rate,
            "by_model": [dataclasses.asdict(m) for m in report.by_model],
            "best": dataclasses.asdict(report.best) if report.best else None,
            "recommendations": list(recommend(report)),
        }
        receipts = load_receipts(repo_root, scope="project")
        ledger = dataclasses.asdict(summarize_receipts(receipts, scope="project"))
        return {"flywheel": flywheel, "ledger": ledger}
    except Exception:  # noqa: BLE001
        return empty


def _unit_receipt_extra(state_dir: Path, receipt_path: str | None) -> dict[str, Any]:
    """Compact receipt fields for the unit drilldown; ``{}`` when unreadable.

    Resolves the manifest's ``receipt_path`` (absolute, or relative to the swarm
    state dir) and pulls a few human-useful fields. Never raises.
    """
    if not receipt_path:
        return {}
    try:
        candidate = Path(receipt_path)
        if not candidate.is_absolute():
            candidate = state_dir / receipt_path
        if not candidate.is_file():
            return {}
        data = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {
            "tokens": int(data.get("tokens_used", 0) or 0),
            "wall_seconds": float(data.get("wall_seconds", 0) or 0),
            "iterations": int(data.get("iterations", 0) or 0),
            "verifier_exit": data.get("verifier_final_exit"),
            "receipt_hash": str(data.get("receipt_hash") or "")[:16] or None,
            "git_tree_sha": str(data.get("git_tree_sha") or "")[:12] or None,
            "started_at": data.get("started_at"),
            "ended_at": data.get("ended_at"),
        }
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return {}


def _swarm_label(goals: list[str]) -> str:
    """Best-effort one-line label for a swarm from its unit goals."""
    for goal in goals:
        text = str(goal or "").strip()
        if text:
            return text[:80]
    return "swarm"


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
