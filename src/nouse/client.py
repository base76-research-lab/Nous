"""
b76.client — tunn HTTP-klient mot daemon-API
============================================
Används av CLI-kommandon när daemon kör och har exklusivt
grepp om KuzuDB. Alla b76-kommandon bör anropa `daemon_url()`
för att avgöra om de ska prata med API:et eller öppna DB direkt.
"""
from __future__ import annotations

import json
import os
import time

import httpx

DAEMON_BASE = "http://127.0.0.1:8765"
_TIMEOUT    = 5.0
BRAIN_DB_BASE = (os.getenv("NOUSE_BRAIN_DB_BASE") or "http://127.0.0.1:7676").rstrip("/")
_BRAIN_TIMEOUT = max(
    1.0,
    float(os.getenv("NOUSE_BRAIN_DB_TIMEOUT_SEC", "5")),
)
_CHAT_STREAM_CONNECT_TIMEOUT_SEC = max(
    1.0,
    float(os.getenv("NOUSE_CHAT_STREAM_CONNECT_TIMEOUT_SEC", "10")),
)
_CHAT_STREAM_READ_TIMEOUT_SEC = max(
    30.0,
    float(os.getenv("NOUSE_CHAT_STREAM_READ_TIMEOUT_SEC", "300")),
)
_CHAT_STREAM_CONNECT_RETRIES = max(
    1,
    int(os.getenv("NOUSE_CHAT_STREAM_CONNECT_RETRIES", "3")),
)
_CHAT_STREAM_RETRY_BACKOFF_SEC = max(
    0.2,
    float(os.getenv("NOUSE_CHAT_STREAM_RETRY_BACKOFF_SEC", "0.8")),
)


def daemon_running() -> bool:
    """Returnerar True om daemon svarar på /api/status."""
    try:
        r = httpx.get(f"{DAEMON_BASE}/api/status", timeout=_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


def _brain_get(path: str, *, params: dict | None = None, timeout: float = _BRAIN_TIMEOUT) -> dict:
    r = httpx.get(f"{BRAIN_DB_BASE}{path}", params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _brain_post(path: str, *, payload: dict | None = None, timeout: float = _BRAIN_TIMEOUT) -> dict:
    r = httpx.post(f"{BRAIN_DB_BASE}{path}", json=(payload or {}), timeout=timeout)
    r.raise_for_status()
    return r.json()


def brain_db_running() -> bool:
    """Returnerar True om brain-db-core svarar på /health."""
    try:
        row = _brain_get("/health", timeout=_BRAIN_TIMEOUT)
        return bool(row.get("ok"))
    except Exception:
        return False


def brain_get_health(timeout: float = _BRAIN_TIMEOUT) -> dict:
    return _brain_get("/health", timeout=timeout)


def brain_get_state(timeout: float = _BRAIN_TIMEOUT) -> dict:
    return _brain_get("/state", timeout=timeout)


def brain_get_gap_map(timeout: float = _BRAIN_TIMEOUT) -> dict:
    return _brain_get("/gap_map", timeout=timeout)


def brain_get_metrics(last_n: int = 100, timeout: float = _BRAIN_TIMEOUT) -> dict:
    return _brain_get("/metrics", params={"last_n": int(last_n)}, timeout=timeout)


def brain_get_live(
    *,
    limit_nodes: int = 12,
    limit_edges: int = 16,
    timeout: float = _BRAIN_TIMEOUT,
) -> dict:
    return _brain_get(
        "/live",
        params={"limit_nodes": int(limit_nodes), "limit_edges": int(limit_edges)},
        timeout=timeout,
    )


def brain_step(
    *,
    events: list[dict] | None = None,
    timeout: float = _BRAIN_TIMEOUT,
) -> dict:
    return _brain_post("/step", payload={"events": events or []}, timeout=timeout)


def brain_save(timeout: float = _BRAIN_TIMEOUT) -> dict:
    return _brain_post("/save", payload={}, timeout=timeout)


def brain_clawbot_ingest(
    *,
    text: str,
    channel: str = "default",
    actor_id: str = "",
    source: str = "clawbot",
    mode: str = "now",
    strict_pairing: bool = True,
    context_key: str = "",
    timeout: float = _BRAIN_TIMEOUT,
) -> dict:
    r = httpx.post(
        f"{DAEMON_BASE}/api/ingress/clawbot",
        json={
            "text": text,
            "channel": channel,
            "actor_id": actor_id,
            "source": source,
            "mode": mode,
            "strict_pairing": bool(strict_pairing),
            "context_key": context_key,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def brain_clawbot_allowlist(channel: str = "default", timeout: float = _BRAIN_TIMEOUT) -> dict:
    r = httpx.get(
        f"{DAEMON_BASE}/api/ingress/clawbot/allowlist",
        params={"channel": channel},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def brain_clawbot_approve(
    *,
    channel: str = "default",
    code: str,
    timeout: float = _BRAIN_TIMEOUT,
) -> dict:
    r = httpx.post(
        f"{DAEMON_BASE}/api/ingress/clawbot/approve",
        json={"channel": channel, "code": code},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def get_status() -> dict:
    r = httpx.get(f"{DAEMON_BASE}/api/status", timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_sessions(limit: int = 30, status: str = "all", timeout: float = 10.0) -> dict:
    r = httpx.get(
        f"{DAEMON_BASE}/api/sessions",
        params={"limit": limit, "status": status},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def post_session_open(
    *,
    session_id: str = "main",
    lane: str = "main",
    source: str = "cli",
    timeout: float = 10.0,
) -> dict:
    r = httpx.post(
        f"{DAEMON_BASE}/api/sessions/open",
        json={"session_id": session_id, "lane": lane, "source": source, "meta": {}},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def post_system_wake(
    *,
    text: str = "",
    session_id: str = "main",
    source: str = "cli",
    mode: str = "now",
    reason: str = "operator_wake",
    context_key: str = "",
    timeout: float = 10.0,
) -> dict:
    r = httpx.post(
        f"{DAEMON_BASE}/api/system/wake",
        json={
            "text": text,
            "session_id": session_id,
            "source": source,
            "mode": mode,
            "reason": reason,
            "context_key": context_key,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def get_system_events(
    *,
    limit: int = 20,
    session_id: str = "",
    timeout: float = 10.0,
) -> dict:
    r = httpx.get(
        f"{DAEMON_BASE}/api/system/events",
        params={"limit": limit, "session_id": session_id},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def get_usage_summary(limit: int = 1000, timeout: float = 15.0) -> dict:
    r = httpx.get(
        f"{DAEMON_BASE}/api/usage/summary",
        params={"limit": limit},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def get_queue_status(limit: int = 20, status: str = "all", timeout: float = 15.0) -> dict:
    r = httpx.get(
        f"{DAEMON_BASE}/api/queue/status",
        params={"limit": limit, "status": status},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def post_queue_scan(max_new: int = 4, timeout: float = 20.0) -> dict:
    r = httpx.post(
        f"{DAEMON_BASE}/api/queue/scan",
        json={"max_new": max_new},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def post_queue_retry_failed(
    limit: int = 5,
    reason: str = "manuell retry via cli",
    timeout: float = 20.0,
) -> dict:
    r = httpx.post(
        f"{DAEMON_BASE}/api/queue/retry_failed",
        json={"limit": limit, "reason": reason},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def post_queue_run(
    *,
    count: int = 1,
    task_timeout_sec: float = 180.0,
    extract_timeout_sec: float = 30.0,
    extract_models: str = "",
    source: str = "cli_queue",
    wait: bool = False,
    timeout: float = 30.0,
) -> dict:
    r = httpx.post(
        f"{DAEMON_BASE}/api/queue/run",
        json={
            "count": count,
            "task_timeout_sec": task_timeout_sec,
            "extract_timeout_sec": extract_timeout_sec,
            "extract_models": extract_models,
            "source": source,
            "wait": wait,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def post_kickstart(
    *,
    session_id: str = "main",
    mission: str = "",
    focus_domains: str = "",
    repo_root: str = "",
    iic1_root: str = "",
    max_tasks: int = 8,
    max_docs: int = 8,
    source: str = "cli_kickstart",
    timeout: float = 90.0,
) -> dict:
    r = httpx.post(
        f"{DAEMON_BASE}/api/kickstart",
        json={
            "session_id": session_id,
            "mission": mission,
            "focus_domains": focus_domains,
            "repo_root": repo_root,
            "iic1_root": iic1_root,
            "max_tasks": int(max_tasks),
            "max_docs": int(max_docs),
            "source": source,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def get_queue_run_status(
    job_id: str,
    include_results: bool = True,
    timeout: float = 15.0,
) -> dict:
    r = httpx.get(
        f"{DAEMON_BASE}/api/queue/run_status",
        params={"job_id": job_id, "include_results": str(bool(include_results)).lower()},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def get_graph(limit: int = 500) -> dict:
    r = httpx.get(f"{DAEMON_BASE}/api/graph", params={"limit": limit}, timeout=30.0)
    r.raise_for_status()
    return r.json()


def get_nerv(domain_a: str, domain_b: str, max_hops: int = 8) -> dict:
    r = httpx.get(f"{DAEMON_BASE}/api/nerv",
                  params={"domain_a": domain_a, "domain_b": domain_b,
                          "max_hops": max_hops},
                  timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_trace(start: str, end: str, max_hops: int = 10, max_paths: int = 3) -> dict:
    r = httpx.get(f"{DAEMON_BASE}/api/trace",
                  params={"start": start, "end": end,
                          "max_hops": max_hops, "max_paths": max_paths},
                  timeout=30.0)
    r.raise_for_status()
    return r.json()


def get_bisoc(tau: float = 0.55, epsilon: float = 2.0, max_domains: int = 50) -> dict:
    r = httpx.get(f"{DAEMON_BASE}/api/bisoc",
                  params={"tau": tau, "epsilon": epsilon, "max_domains": max_domains},
                  timeout=120.0)
    r.raise_for_status()
    return r.json()


def get_output_trace(trace_id: str | None = None, limit: int = 200) -> dict:
    params: dict[str, str | int] = {"limit": limit}
    if trace_id:
        params["trace_id"] = trace_id
    r = httpx.get(f"{DAEMON_BASE}/api/trace/output", params=params, timeout=30.0)
    r.raise_for_status()
    return r.json()


def get_knowledge_audit(
    limit: int = 50,
    *,
    strict: bool = True,
    min_evidence_score: float = 0.65,
) -> dict:
    r = httpx.get(
        f"{DAEMON_BASE}/api/knowledge/audit",
        params={
            "limit": limit,
            "strict": str(bool(strict)).lower(),
            "min_evidence_score": min_evidence_score,
        },
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()


def post_knowledge_backfill(
    limit: int | None = None,
    *,
    strict: bool = True,
    min_evidence_score: float = 0.65,
) -> dict:
    params: dict[str, int | str | float] = {}
    if limit is not None:
        params["limit"] = limit
    params["strict"] = str(bool(strict)).lower()
    params["min_evidence_score"] = min_evidence_score
    r = httpx.post(
        f"{DAEMON_BASE}/api/knowledge/backfill",
        params=params,
        timeout=120.0,
    )
    r.raise_for_status()
    return r.json()


def get_memory_audit(limit: int = 20) -> dict:
    r = httpx.get(
        f"{DAEMON_BASE}/api/memory/audit",
        params={"limit": limit},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()


def post_memory_consolidate(
    *,
    max_episodes: int = 40,
    strict_min_evidence: float = 0.65,
) -> dict:
    r = httpx.post(
        f"{DAEMON_BASE}/api/memory/consolidate",
        params={
            "max_episodes": max_episodes,
            "strict_min_evidence": strict_min_evidence,
        },
        timeout=120.0,
    )
    r.raise_for_status()
    return r.json()


def post_knowledge_enrich(
    *,
    max_nodes: int = 50,
    max_minutes: float = 15.0,
    dry_run: bool = False,
) -> dict:
    r = httpx.post(
        f"{DAEMON_BASE}/api/knowledge/enrich",
        params={
            "max_nodes": max_nodes,
            "max_minutes": max_minutes,
            "dry_run": str(dry_run).lower(),
        },
        timeout=max_minutes * 60 + 30,
    )
    r.raise_for_status()
    return r.json()


def post_nightrun_now(
    *,
    max_minutes: float = 60.0,
    dry_run: bool = False,
) -> dict:
    r = httpx.post(
        f"{DAEMON_BASE}/api/nightrun/now",
        params={
            "max_minutes": max_minutes,
            "dry_run": str(dry_run).lower(),
        },
        timeout=max_minutes * 60 + 30,
    )
    r.raise_for_status()
    return r.json()


def stream_chat(query: str, *, session_id: str = "main"):
    """
    Generator: streama NDJSON-svar från /api/agent_chat.
    Varje item är ett dict med 'type' och 'msg'/'name'/'result'.
    """
    for attempt in range(1, _CHAT_STREAM_CONNECT_RETRIES + 1):
        emitted_rows = 0
        emitted_tool_or_result = False
        try:
            with httpx.stream(
                "POST",
                f"{DAEMON_BASE}/api/agent_chat",
                json={"query": query, "session_id": session_id},
                timeout=httpx.Timeout(
                    connect=_CHAT_STREAM_CONNECT_TIMEOUT_SEC,
                    read=_CHAT_STREAM_READ_TIMEOUT_SEC,
                    write=30.0,
                    pool=10.0,
                ),
            ) as resp:
                resp.raise_for_status()
                saw_terminal_event = False
                try:
                    for line in resp.iter_lines():
                        raw = str(line or "").strip()
                        if not raw:
                            continue
                        try:
                            row = json.loads(raw)
                        except json.JSONDecodeError:
                            yield {
                                "type": "error",
                                "msg": f"Ogiltigt stream-paket från daemon: {raw[:200]}",
                            }
                            return
                        row_type = str(row.get("type", ""))
                        emitted_rows += 1
                        if row_type in {"tool", "tool_result"}:
                            emitted_tool_or_result = True
                        if row_type in {"done", "error"}:
                            saw_terminal_event = True
                        yield row
                    if not saw_terminal_event:
                        yield {
                            "type": "error",
                            "msg": "Daemon avslutade streamen utan done/error.",
                        }
                except httpx.RemoteProtocolError as e:
                    # Säker retry enbart om streamen dog innan användbar output
                    # och innan tool/result syntes (för att undvika dubbelkörning).
                    can_retry = (
                        attempt < _CHAT_STREAM_CONNECT_RETRIES
                        and emitted_rows == 0
                        and not emitted_tool_or_result
                    )
                    if can_retry:
                        wait_s = _CHAT_STREAM_RETRY_BACKOFF_SEC * attempt
                        yield {
                            "type": "status",
                            "msg": (
                                "Streamen bröts tidigt av daemon. Försöker igen "
                                f"({attempt}/{_CHAT_STREAM_CONNECT_RETRIES}) om {wait_s:.1f}s..."
                            ),
                        }
                        time.sleep(wait_s)
                        continue
                    yield {
                        "type": "error",
                        "msg": (
                            "Streamen avbröts oväntat från daemon "
                            f"(RemoteProtocolError: {e}). Försök igen."
                        ),
                    }
                    return
                except httpx.ReadTimeout as e:
                    yield {
                        "type": "error",
                        "msg": (
                            "Chat-streamen tog för lång tid att svara "
                            f"(timeout efter {_CHAT_STREAM_READ_TIMEOUT_SEC:.0f}s: {e}). "
                            "Försök igen eller ställ en smalare fråga."
                        ),
                    }
                    return
            return
        except httpx.RemoteProtocolError as e:
            can_retry = (
                attempt < _CHAT_STREAM_CONNECT_RETRIES
                and emitted_rows == 0
                and not emitted_tool_or_result
            )
            if can_retry:
                wait_s = _CHAT_STREAM_RETRY_BACKOFF_SEC * attempt
                yield {
                    "type": "status",
                    "msg": (
                        "Daemon stream-protokollfel vid anslutning. Försöker igen "
                        f"({attempt}/{_CHAT_STREAM_CONNECT_RETRIES}) om {wait_s:.1f}s..."
                    ),
                }
                time.sleep(wait_s)
                continue
            yield {
                "type": "error",
                "msg": (
                    "Kunde inte läsa chat-stream från daemon "
                    f"(RemoteProtocolError: {e})"
                ),
            }
            return
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            if attempt < _CHAT_STREAM_CONNECT_RETRIES:
                wait_s = _CHAT_STREAM_RETRY_BACKOFF_SEC * attempt
                yield {
                    "type": "status",
                    "msg": (
                        "Daemon ej nåbar ännu. Försöker återansluta "
                        f"({attempt}/{_CHAT_STREAM_CONNECT_RETRIES}) om {wait_s:.1f}s..."
                    ),
                }
                time.sleep(wait_s)
                continue
            yield {
                "type": "error",
                "msg": f"Kunde inte läsa chat-stream från daemon: {e}",
            }
            return
        except httpx.HTTPError as e:
            text = str(e)
            if "Connection refused" in text and attempt < _CHAT_STREAM_CONNECT_RETRIES:
                wait_s = _CHAT_STREAM_RETRY_BACKOFF_SEC * attempt
                yield {
                    "type": "status",
                    "msg": (
                        "Connection refused från daemon. Försöker igen "
                        f"({attempt}/{_CHAT_STREAM_CONNECT_RETRIES}) om {wait_s:.1f}s..."
                    ),
                }
                time.sleep(wait_s)
                continue
            yield {
                "type": "error",
                "msg": f"Kunde inte läsa chat-stream från daemon: {e}",
            }
            return
