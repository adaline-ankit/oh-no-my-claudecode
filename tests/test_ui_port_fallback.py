"""Tests for onmc ui automatic port fallback.

A stale ``onmc ui`` holding the default port used to crash a fresh launch with
``[Errno 48] Address already in use`` — and left the user staring at the old
dashboard.  ``create_ui_server_scanning`` binds the next free port instead.

NEVER binds 0.0.0.0 in any test — loopback only.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.ui.server import (
    create_ui_server,
    create_ui_server_scanning,
)


def _ready_service(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> OnmcService:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    return service


def test_scanning_port_zero_binds_os_assigned(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """port=0 → OS assigns a real port, no scan."""
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server_scanning(service, host="127.0.0.1", port=0)
    try:
        assert server.server_address[1] > 0
    finally:
        server.server_close()


def test_scanning_falls_back_when_busy(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the requested port is held, scanning binds a different free port."""
    service = _ready_service(sample_repo, monkeypatch)
    # Occupy a port via an OS-assigned bind, then ask scanning to start there.
    occupied = create_ui_server(service, host="127.0.0.1", port=0)
    busy_port = occupied.server_address[1]
    try:
        server = create_ui_server_scanning(
            service, host="127.0.0.1", port=busy_port, scan_limit=20
        )
        try:
            bound = server.server_address[1]
            assert bound != busy_port
            assert busy_port < bound <= busy_port + 20
        finally:
            server.server_close()
    finally:
        occupied.server_close()


def test_scanning_raises_when_window_exhausted(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A one-port scan window over a busy port surfaces a clear OSError."""
    service = _ready_service(sample_repo, monkeypatch)
    occupied = create_ui_server(service, host="127.0.0.1", port=0)
    busy_port = occupied.server_address[1]
    try:
        with pytest.raises(OSError, match="could not bind any port"):
            create_ui_server_scanning(
                service, host="127.0.0.1", port=busy_port, scan_limit=1
            )
    finally:
        occupied.server_close()


def test_scanning_binds_requested_port_when_free(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the requested port is free, scanning binds exactly that port."""
    service = _ready_service(sample_repo, monkeypatch)
    # Find a free port by opening then closing an OS-assigned bind.
    probe = create_ui_server(service, host="127.0.0.1", port=0)
    free_port = probe.server_address[1]
    probe.server_close()

    server = create_ui_server_scanning(service, host="127.0.0.1", port=free_port)
    try:
        assert server.server_address[1] == free_port
    finally:
        with contextlib.suppress(Exception):
            server.server_close()
