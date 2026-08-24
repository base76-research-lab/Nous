"""Minimal MCP client helper — Nous calling OUT to another MCP server.

Nous has so far only ever been an MCP *server* (mcp_gateway, mcp/server.py
expose its own tools to other clients). This is the other direction: a
thin wrapper around the official `mcp` SDK's client session, used for
agent-driven tool calls that don't need a full interactive LLM loop (e.g.
a periodic poller, or a folder-driven agent's own tool dispatch).

Two transports, both using the same official SDK:
- HTTP (`streamable_http_client`) — AgentMail's endpoint.
- stdio (`stdio_client`) — Thunderbird's local `node` bridge process, and
  any other local-process MCP server.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client


def _parse_tool_result(result: Any) -> dict[str, Any]:
    if not result.content:
        return {}
    text = result.content[0].text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"raw": text}


async def call_http_mcp_tool(
    *, url: str, headers: dict[str, str], tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Call one tool on an HTTP-transport MCP server and return its parsed
    JSON result. Raises on transport/protocol failure — callers should
    treat that as an interface error (TOOL_UNAVAILABLE), not a structural
    one.
    """
    http_client = httpx.AsyncClient(headers=headers)
    async with streamable_http_client(url, http_client=http_client) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return _parse_tool_result(result)


async def call_stdio_mcp_tool(
    *,
    command: str,
    args: list[str],
    env: dict[str, str] | None,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Call one tool on a local-process (stdio) MCP server, e.g. the
    Thunderbird bridge. Spawns and tears down the process per call — this
    is a correctness-first MVP, not a long-lived connection pool.
    """
    params = StdioServerParameters(command=command, args=args, env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return _parse_tool_result(result)


def _agentmail_api_key() -> str:
    import os
    from pathlib import Path

    key = os.getenv("AGENTMAIL_API_KEY", "").strip()
    if key:
        return key
    env_file = Path.home() / ".config" / "agentmail.env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("AGENTMAIL_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


# Server registry — the "folders over agents" AGENT.md cards reference a
# server by this short name (e.g. executor: "mcp:thunderbird_mail.listEvents"),
# never the raw command/URL. Adding a new MCP server means adding one entry
# here, not touching any agent card's dispatch logic.
_STDIO_SERVERS: dict[str, dict[str, Any]] = {
    "thunderbird_mail": {
        "command": "node",
        "args": ["/home/bjornwikstrom/Ljus-i-Omarchy/03_Drift/thunderbird-mcp/mcp-bridge.cjs"],
        "env": None,
    },
}


def _http_servers() -> dict[str, dict[str, Any]]:
    # Built lazily so the API key is re-read fresh each call rather than
    # captured once at import time.
    return {
        "agentmail": {
            "url": "https://mcp.agentmail.to/mcp",
            "headers": {"x-api-key": _agentmail_api_key()},
        },
    }


async def call_named_mcp_tool(*, server: str, tool_name: str, arguments: dict[str, Any]) -> Any:
    """Dispatch to a registered MCP server by short name. Raises
    ValueError for an unknown server (a config error, not a runtime one)
    and lets transport exceptions propagate — callers map those to
    TOOL_UNAVAILABLE.
    """
    if server in _STDIO_SERVERS:
        cfg = _STDIO_SERVERS[server]
        return await call_stdio_mcp_tool(
            command=cfg["command"], args=cfg["args"], env=cfg["env"],
            tool_name=tool_name, arguments=arguments,
        )
    http_servers = _http_servers()
    if server in http_servers:
        cfg = http_servers[server]
        return await call_http_mcp_tool(
            url=cfg["url"], headers=cfg["headers"], tool_name=tool_name, arguments=arguments,
        )
    raise ValueError(f"unknown MCP server: {server!r}")
