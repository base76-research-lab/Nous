"""Minimal MCP client helper — Nous calling OUT to another MCP server.

Nous has so far only ever been an MCP *server* (mcp_gateway, mcp/server.py
expose its own tools to other clients). This is the other direction: a
thin wrapper around the official `mcp` SDK's client session, used for
agent-driven tool calls that don't need a full interactive LLM loop (e.g.
a periodic poller, or a folder-driven agent's own tool dispatch).

HTTP transport only for now (matches AgentMail's `streamable_http` MCP
endpoint). Thunderbird's local stdio server is a separate transport,
wired in when the mail-triage/calendar-write agent cards need it.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


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
            if not result.content:
                return {}
            text = result.content[0].text
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return {"raw": text}
