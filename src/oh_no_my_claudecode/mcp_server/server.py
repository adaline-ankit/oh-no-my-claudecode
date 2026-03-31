from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import cast

from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.stdio import stdio_server
from mcp.types import Resource, ResourceTemplate
from pydantic import AnyUrl

from oh_no_my_claudecode.mcp_server.resources import (
    default_repo,
    list_onmc_resource_templates,
    list_onmc_resources,
    read_onmc_resource,
)

STARTUP_SNIPPET = (
    "ONMC MCP server running. Add to Claude Code settings:\n"
    '{\n  "mcpServers": {\n    "onmc": {\n      "command": "onmc",\n'
    '      "args": ["serve", "--mcp"]\n    }\n  }\n}\n'
)


def build_mcp_server(path: Path | str = ".") -> Server:
    """Build the ONMC MCP server for a repo path."""
    repo = default_repo(path)
    app = Server("onmc")

    @app.list_resources()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_resources() -> list[Resource]:
        return list_onmc_resources()

    @app.list_resource_templates()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_resource_templates() -> list[ResourceTemplate]:
        return list_onmc_resource_templates()

    @app.read_resource()  # type: ignore[no-untyped-call,untyped-decorator]
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        return read_onmc_resource(repo, str(cast(str, uri)))

    return app


async def _run(path: Path | str = ".") -> None:
    app = build_mcp_server(path)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def run_mcp_server(path: Path | str = ".") -> None:
    """Run the ONMC MCP server over stdio."""
    sys.stderr.write(STARTUP_SNIPPET)
    sys.stderr.flush()
    asyncio.run(_run(path))
