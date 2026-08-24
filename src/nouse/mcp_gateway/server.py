from __future__ import annotations

import asyncio
from typing import Any

from nouse.mcp_gateway.gateway import (
    fetch_url,
    find_local_files,
    kernel_execute_self_update,
    kernel_get_identity,
    kernel_get_working_context,
    kernel_link_concepts,
    kernel_log_outcome,
    kernel_promote_memory,
    kernel_propose_fact,
    kernel_reflect,
    kernel_retrieve_memory,
    kernel_update_policy,
    kernel_write_episode,
    list_local_mounts,
    read_local_file,
    run_local_command,
    search_local_text,
    web_search,
    write_local_file,
)

try:
    from mcp.server.mcpserver import MCPServer
except Exception as exc:  # pragma: no cover - runtime dependency hint
    raise RuntimeError(
        "mcp package is required for b76 MCP server. Install with: pip install mcp"
    ) from exc

mcp = MCPServer("b76-kernel")


@mcp.tool()
def web_search_tool(
    query: str,
    max_results: int = 5,
    provider: str = "auto",
) -> dict[str, Any]:
    return web_search(query, max_results=max_results, provider=provider)


@mcp.tool()
def fetch_url_tool(url: str) -> dict[str, Any]:
    return fetch_url(url)


@mcp.tool()
def list_local_mounts_tool() -> dict[str, Any]:
    return list_local_mounts()


@mcp.tool()
def find_local_files_tool(
    query: str,
    roots: list[str] | None = None,
    extensions: list[str] | None = None,
    max_results: int = 80,
    include_hidden: bool = False,
) -> dict[str, Any]:
    return find_local_files(
        query,
        roots,
        extensions=extensions,
        max_results=max_results,
        include_hidden=include_hidden,
    )


@mcp.tool()
def search_local_text_tool(
    query: str,
    roots: list[str] | None = None,
    max_results: int = 120,
) -> dict[str, Any]:
    return search_local_text(query, roots, max_results=max_results)


@mcp.tool()
def read_local_file_tool(
    path: str,
    max_chars: int = 12000,
    start_line: int = 1,
    end_line: int = 0,
) -> dict[str, Any]:
    return read_local_file(
        path,
        max_chars=max_chars,
        start_line=start_line,
        end_line=end_line,
    )


@mcp.tool()
def write_local_file_tool(
    path: str,
    content: str,
    mode: str = "overwrite",
    create_dirs: bool = False,
) -> dict[str, Any]:
    return write_local_file(
        path,
        content,
        mode=mode,
        create_dirs=create_dirs,
    )


@mcp.tool()
def run_local_command_tool(
    command: str,
    workdir: str = "",
    timeout_sec: int = 45,
) -> dict[str, Any]:
    return run_local_command(
        command,
        workdir=workdir or None,
        timeout_sec=timeout_sec,
    )


@mcp.tool()
def kernel_get_identity_tool() -> dict[str, Any]:
    return kernel_get_identity()


@mcp.tool()
def kernel_get_working_context_tool(limit: int = 12) -> dict[str, Any]:
    return kernel_get_working_context(limit=limit)


@mcp.tool()
def kernel_retrieve_memory_tool(query: str, limit: int = 8) -> dict[str, Any]:
    return kernel_retrieve_memory(query, limit=limit)


@mcp.tool()
def kernel_write_episode_tool(
    text: str,
    source: str = "kernel",
    domain_hint: str = "kernel",
    path: str = "",
) -> dict[str, Any]:
    return kernel_write_episode(text, source=source, domain_hint=domain_hint, path=path)


@mcp.tool()
def kernel_propose_fact_tool(
    claim: str,
    evidence_ref: str = "",
    confidence: float = 0.5,
    source: str = "kernel_fact_proposal",
) -> dict[str, Any]:
    return kernel_propose_fact(
        claim,
        evidence_ref=evidence_ref,
        confidence=confidence,
        source=source,
    )


@mcp.tool()
def kernel_link_concepts_tool(
    src: str,
    rel_type: str,
    tgt: str,
    why: str = "",
    evidence_score: float = 0.5,
    assumption_flag: bool = False,
) -> dict[str, Any]:
    return kernel_link_concepts(
        src,
        rel_type,
        tgt,
        why=why,
        evidence_score=evidence_score,
        assumption_flag=assumption_flag,
    )


@mcp.tool()
def kernel_log_outcome_tool(
    action: str,
    outcome: str,
    trace_id: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    return kernel_log_outcome(action, outcome, trace_id=trace_id, run_id=run_id)


@mcp.tool()
def kernel_reflect_tool(
    note: str,
    trace_id: str = "",
    source: str = "kernel_reflection",
) -> dict[str, Any]:
    return kernel_reflect(note, trace_id=trace_id, source=source)


@mcp.tool()
def kernel_promote_memory_tool(
    max_episodes: int = 40,
    strict_min_evidence: float = 0.65,
    approval_token: str = "",
) -> dict[str, Any]:
    return kernel_promote_memory(
        max_episodes=max_episodes,
        strict_min_evidence=strict_min_evidence,
        approval_token=approval_token or None,
    )


@mcp.tool()
def kernel_update_policy_tool(change_request: str, approval_token: str = "") -> dict[str, Any]:
    return kernel_update_policy(change_request, approval_token=approval_token or None)


@mcp.tool()
def kernel_execute_self_update_tool(plan: str, approval_token: str = "") -> dict[str, Any]:
    return kernel_execute_self_update(plan, approval_token=approval_token or None)


def run_stdio() -> None:
    asyncio.run(mcp.run_stdio_async())


def run_http(host: str = "127.0.0.1", port: int = 8766) -> None:
    """Run b76-kernel as streamable-HTTP MCP server (for claude.ai web integration).

    Expose with Cloudflare Tunnel:
        cloudflared tunnel --url http://localhost:8766
    Then register https://<tunnel>.trycloudflare.com/mcp in claude.ai Settings → Integrations.
    """
    import argparse

    from mcp.server.transport_security import TransportSecuritySettings

    parser = argparse.ArgumentParser(description="Run b76-kernel as HTTP MCP server.")
    parser.add_argument("--host", default=host)
    parser.add_argument("--port", type=int, default=port)
    args = parser.parse_args()

    # Disable DNS-rebinding protection so Cloudflare Tunnel host headers pass through
    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )


if __name__ == "__main__":
    run_stdio()
