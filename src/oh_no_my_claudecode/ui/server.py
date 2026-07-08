from __future__ import annotations

import dataclasses
import errno
import json
import mimetypes
import subprocess
import webbrowser
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from ipaddress import ip_address
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlsplit

from oh_no_my_claudecode.core.repo import path_bucket
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.missioncontrol import build_dashboard, list_swarm_ids
from oh_no_my_claudecode.models import FileStat, RepoFileRecord, TaskStatus

# Callable that runs a shell command and returns (returncode, combined output).
CommandRunner = Callable[[list[str]], tuple[int, str]]

# Unit lifecycle states that mean "an agent is working right now".
_LIVE_UNIT_STATES = frozenset({"pending", "queued", "running"})

STATIC_ROOT = files("oh_no_my_claudecode.ui").joinpath("static")


def _default_command_runner(cmd: list[str]) -> tuple[int, str]:
    """Shell out and return ``(returncode, combined stdout+stderr)``.

    Capped at 60 s; any exception returns returncode=1 + error text.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)  # noqa: S603
        return result.returncode, (result.stdout + result.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def build_agents_payload(repo_root: Path) -> dict[str, Any]:
    """Agents view payload: local swarms + global summary.

    Delegates to the same ``_swarms_payload`` / ``_global_swarms_payload``
    helpers used by the main dashboard so there is no duplication.
    This function is *pure* given a fixed filesystem state — call it in tests
    by seeding swarm manifests under ``repo_root/.onmc/swarm/``.
    """
    return {
        "local": _swarms_payload(repo_root),
        "global": _global_swarms_payload(),
    }


def build_live_payload(live_dir: Path, *, since: float | None = None) -> dict[str, Any]:
    """Active-agent + event-feed payload from the telemetry bus.

    Pure given a fixed filesystem state — call it in tests by seeding
    ``<live_dir>/events.jsonl`` with fixture event lines.  Graceful when
    ``live_dir`` is absent or empty (returns zeroed response, no error).

    Parameters
    ----------
    live_dir:
        Directory containing ``events.jsonl`` (e.g. ``<repo>/.onmc/live/``).
    since:
        Unix timestamp (float).  Only events with ``ts > since`` appear in the
        returned ``events`` list.  ``active`` is always derived from the full
        history so start/stop pairing is correct across restarts.

    Returns
    -------
    dict with keys ``active`` (list of active-agent dicts), ``events``
    (serialised Event dicts filtered by ``since``), and ``max_ts`` (float).
    """
    from oh_no_my_claudecode import telemetry  # local import avoids circular deps

    all_events = telemetry.read_events(live_dir)
    filtered = (
        telemetry.read_events(live_dir, since_ts=since) if since is not None else all_events
    )
    active = telemetry.active_agents(all_events)
    max_ts = max((ev.ts for ev in all_events), default=0.0)
    return {
        "active": active,
        "events": [dataclasses.asdict(ev) for ev in filtered],
        "max_ts": max_ts,
    }


def _handle_agents_action(
    data: dict[str, Any],
    runner: CommandRunner,
) -> dict[str, Any]:
    """Dispatch an agents-action request to the injectable ``runner``.

    Returns ``{"ok": bool, "returncode": int, "output": str}``.
    Supported actions:

    - ``abort`` — ``onmc swarm abort <swarm_id>``
    - ``land``  — ``gh pr merge <pr_url> --squash``
    - ``mission`` — ``onmc mission <goal>``
    """
    action = str(data.get("action", ""))
    if action == "abort":
        swarm_id = str(data.get("swarm_id", "")).strip()
        if not swarm_id:
            return {"ok": False, "returncode": 1, "output": "swarm_id required"}
        cmd: list[str] = ["onmc", "swarm", "abort", swarm_id]
    elif action == "land":
        pr_url = str(data.get("pr_url", "")).strip()
        if not pr_url:
            return {"ok": False, "returncode": 1, "output": "pr_url required"}
        cmd = ["gh", "pr", "merge", pr_url, "--squash"]
    elif action == "mission":
        goal = str(data.get("goal", "")).strip()
        if not goal:
            return {"ok": False, "returncode": 1, "output": "goal required"}
        cmd = ["onmc", "mission", goal]
    else:
        return {"ok": False, "returncode": 1, "output": f"unknown action: {action!r}"}

    returncode, output = runner(cmd)
    return {"ok": returncode == 0, "returncode": returncode, "output": output}


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
        "global": _global_swarms_payload(),
        "performance": _performance_payload(Path(status["repo_root"])),
        "scorecard": _scorecard_payload(Path(status["repo_root"])),
        "timeline": _timeline_payload(service),
        "integration": _integration_payload(Path(status["repo_root"])),
    }


def _is_authorized(auth_header: str | None, token: str | None) -> bool:
    """Return True if the request passes bearer-token auth.

    Auth is only enforced when *token* is non-empty.  When *token* is None or
    empty every request is allowed.  A missing or malformed Authorization header
    fails when *token* is set.
    """
    if not token:
        return True
    if auth_header is None:
        return False
    scheme, _, value = auth_header.partition(" ")
    return scheme.lower() == "bearer" and value == token


def _ingest_events(raw: bytes, live_dir: Path) -> tuple[dict[str, Any], int]:
    """Parse raw request body and append event(s) to live_dir/events.jsonl.

    Accepts a single Event JSON object or a JSON array of objects.
    Returns ``(response_dict, http_status_code)`` — 200 on success, 400 on
    parse failure.  Individual items that cannot be coerced to Event are silently
    skipped so one malformed entry in a batch does not abort the rest.
    """
    from oh_no_my_claudecode import telemetry  # local import avoids circular deps

    try:
        data: object = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid JSON"}, 400

    if isinstance(data, dict):
        items: list[object] = [data]
    elif isinstance(data, list):
        items = list(data)
    else:
        return {"ok": False, "error": "expected object or array"}, 400

    accepted = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            ev = telemetry.Event(
                ts=float(item.get("ts", 0.0)),
                kind=str(item.get("kind", "")),
                swarm_id=item.get("swarm_id") or None,
                unit=item.get("unit") or None,
                agent=item.get("agent") or None,
                tool=item.get("tool") or None,
                detail=item.get("detail") or None,
                session_id=item.get("session_id") or None,
            )
            telemetry.emit(ev, live_dir=live_dir)
            accepted += 1
        except (TypeError, ValueError):
            continue

    return {"ok": True, "accepted": accepted}, 200


_PORT_SCAN_LIMIT = 20
"""How many consecutive ports to try when the requested one is already bound."""


def create_ui_server(
    service: OnmcService,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    command_runner: CommandRunner | None = None,
    token: str | None = None,
    live_dir: Path | None = None,
) -> ThreadingHTTPServer:
    runner: CommandRunner = (
        command_runner if command_runner is not None else _default_command_runner
    )
    handler = _handler_factory(service, command_runner=runner, token=token, live_dir=live_dir)
    return ThreadingHTTPServer((host, port), handler)


def create_ui_server_scanning(
    service: OnmcService,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    scan_limit: int = _PORT_SCAN_LIMIT,
) -> ThreadingHTTPServer:
    """Bind a UI server, falling back to the next free port when *port* is busy.

    A common footgun: a stale ``onmc ui`` from an earlier session still holds
    the default port, so a fresh launch would crash with ``[Errno 48] Address
    already in use`` — and worse, the user ends up looking at the *old*
    dashboard (rooted in a different repo) thinking it is the new one.  Instead
    we scan forward from *port* and bind the first free port.  ``port=0`` (let
    the OS choose) is honoured as-is with no scan.

    Raises the last :class:`OSError` when no port in the scan window is free.
    """
    if port == 0:
        return create_ui_server(service, host=host, port=port, token=token)

    last_exc: OSError | None = None
    for candidate in range(port, port + max(1, scan_limit)):
        try:
            return create_ui_server(service, host=host, port=candidate, token=token)
        except OSError as exc:
            if exc.errno in {errno.EADDRINUSE, errno.EACCES}:
                last_exc = exc
                continue
            raise
    msg = (
        f"could not bind any port in {port}–{port + scan_limit - 1} "
        f"(all in use); free one or pass --port"
    )
    raise OSError(errno.EADDRINUSE, msg) from last_exc


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
    token: str | None = None,
) -> None:
    server = create_ui_server_scanning(service, host=host, port=port, token=token)
    raw_host, bound_port = server.server_address[:2]
    bound_host = bytes(raw_host).decode() if isinstance(raw_host, (bytes, bytearray)) else raw_host
    browser_host = "127.0.0.1" if ip_address(bound_host).is_unspecified else bound_host
    url = f"http://{browser_host}:{bound_port}"
    if port not in (0, bound_port):
        print(
            f"Port {port} was busy (another onmc ui?) — using {bound_port} instead."
        )
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


def _handler_factory(
    service: OnmcService,
    *,
    command_runner: CommandRunner,
    token: str | None = None,
    live_dir: Path | None = None,
) -> type[BaseHTTPRequestHandler]:
    def _resolve_live_dir() -> Path:
        """Return the live-events directory, injected or derived from service."""
        if live_dir is not None:
            return live_dir
        return Path(service.status()["repo_root"]) / ".onmc" / "live"

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if not _is_authorized(self.headers.get("Authorization"), token):
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            path = urlsplit(self.path).path
            if path == "/api/dashboard":
                self._send_json(build_dashboard_payload(service))
                return
            if path == "/api/live":
                params = parse_qs(urlsplit(self.path).query)
                raw_since = params.get("since", ["0"])[0]
                try:
                    since_f = float(raw_since)
                    since_arg: float | None = since_f if since_f > 0.0 else None
                except ValueError:
                    since_arg = None
                self._send_json(build_live_payload(_resolve_live_dir(), since=since_arg))
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

        def do_POST(self) -> None:  # noqa: N802
            if not _is_authorized(self.headers.get("Authorization"), token):
                self.send_error(HTTPStatus.UNAUTHORIZED)
                return
            path = urlsplit(self.path).path
            if path == "/api/agents/action":
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                try:
                    data: dict[str, Any] = json.loads(raw)
                except json.JSONDecodeError:
                    self.send_error(HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(_handle_agents_action(data, command_runner))
                return
            if path == "/api/live/ingest":
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                result, status_code = _ingest_events(raw, _resolve_live_dir())
                if status_code != 200:  # noqa: PLR2004
                    self.send_error(HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(result)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

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


def _integration_payload(repo_root: Path) -> dict[str, Any]:
    """Is onmc the default layer on Claude Code? (MCP + hooks + wrap.) Never 500s."""
    try:
        from oh_no_my_claudecode.integration import integration_status

        return integration_status(repo_root).to_dict()
    except Exception:  # noqa: BLE001
        return {
            "mcp_registered": False,
            "hooks_installed": False,
            "wrap_installed": False,
            "claude_md_stanza": False,
            "level": "none",
            "next_steps": [],
        }


def _timeline_payload(service: OnmcService) -> dict[str, Any]:
    """Repo-evolution narrative: memories grouped into periods (via onmc timeline).

    JSON-safe (datetimes → ISO strings). Any failure returns a safe empty
    default so the dashboard never 500s.
    """
    empty: dict[str, Any] = {"periods": [], "total": 0, "notes": []}
    try:
        from datetime import datetime

        from oh_no_my_claudecode.timeline import build_timeline

        timeline = build_timeline(
            service.list_memories(), group="week", now=datetime.now(UTC)
        )
        return {
            "total": timeline.total,
            "notes": list(timeline.notes),
            "periods": [
                {
                    "label": period.label,
                    "entries": [
                        {
                            "kind": entry.kind,
                            "title": entry.title,
                            "summary": entry.summary,
                            "ts": entry.ts.isoformat() if entry.ts else None,
                        }
                        for entry in period.entries
                    ],
                }
                for period in timeline.periods
            ],
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
        flywheel["trend"] = _perf_trend(receipts)
        ledger = dataclasses.asdict(summarize_receipts(receipts, scope="project"))
        return {"flywheel": flywheel, "ledger": ledger}
    except Exception:  # noqa: BLE001
        return empty


def _perf_trend(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chronological verified/cost points for the sparklines; ``[]`` on failure.

    Sorts receipts by ``ended_at`` and keeps the last 30 so the UI can draw a
    verified-rate and cost trend without shipping every historical run.
    """
    try:
        dated = [r for r in receipts if isinstance(r, dict) and r.get("ended_at")]
        dated.sort(key=lambda r: str(r.get("ended_at")))
        return [
            {
                "verified": bool(r.get("verified")),
                "ended_at": r.get("ended_at"),
                "cost": float(r.get("cost_usd") or 0),
            }
            for r in dated[-30:]
        ]
    except Exception:  # noqa: BLE001
        return []


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


def _global_swarms_payload(home: Path | None = None) -> dict[str, Any]:
    """Aggregate swarms across EVERY onmc repo on this machine (the global view).

    Reads the known-repos registry and folds each repo's swarms into one list,
    tagging each with its repo. This is the local, zero-infra "all projects"
    dashboard. Any failure returns a safe empty default (never 500s).
    """
    empty: dict[str, Any] = {
        "repos": [],
        "summary": {"repos": 0, "swarms": 0, "live": 0, "running_units": 0},
        "swarms": [],
    }
    try:
        from oh_no_my_claudecode.home import list_known_repos

        repos: list[dict[str, Any]] = []
        all_swarms: list[dict[str, Any]] = []
        live = running = 0
        for root in list_known_repos(home):
            repo_root = Path(root)
            repo_name = repo_root.name
            per_repo = _swarms_payload(repo_root)
            repo_swarms = per_repo.get("swarms", [])
            summary = per_repo.get("summary", {})
            repos.append(
                {
                    "name": repo_name,
                    "root": root,
                    "swarms": len(repo_swarms),
                    "live": summary.get("live", 0),
                    "running_units": summary.get("running_units", 0),
                }
            )
            for swarm in repo_swarms:
                swarm["repo"] = repo_name
                all_swarms.append(swarm)
            live += summary.get("live", 0)
            running += summary.get("running_units", 0)

        # Live repos + most-recent swarms first.
        all_swarms.sort(
            key=lambda s: (s.get("live", False), s.get("started_at") or ""), reverse=True
        )
        repos.sort(key=lambda r: (r["live"], r["swarms"]), reverse=True)
        return {
            "repos": repos,
            "summary": {
                "repos": len(repos),
                "swarms": len(all_swarms),
                "live": live,
                "running_units": running,
            },
            "swarms": all_swarms,
        }
    except Exception:  # noqa: BLE001
        return empty


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
