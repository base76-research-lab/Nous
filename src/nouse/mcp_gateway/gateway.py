"""
b76.mcp_gateway.gateway — MCP Gateway (Minimal)
===============================================
Erbjuder web search, URL-hämtning och lokal filsystemsåtkomst (read-only)
för chat-motorn.
Verktygen är utformade för att integreras direkt i den existerande
Ollama-agent-loopen, så modellen (b76 chat) kan hämta information autonomt.
"""
from __future__ import annotations

import httpx
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
import warnings
from urllib.parse import parse_qs, quote, unquote, urlparse
from bs4 import BeautifulSoup
from nouse.config.env import load_env_files
from nouse.daemon.file_text import extract_text
from nouse.memory.store import MemoryStore

try:
    from ddgs import DDGS  # type: ignore
except Exception:  # pragma: no cover - fallback om ddgs ej installerad
    from duckduckgo_search import DDGS  # type: ignore

log = logging.getLogger("nouse.mcp_gateway")
load_env_files()
warnings.filterwarnings(
    "ignore",
    message="This package (`duckduckgo_search`) has been renamed to `ddgs`! Use `pip install ddgs` instead.",
    category=RuntimeWarning,
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_ACCEPT_LANGUAGE = "en-US,en;q=0.9,sv-SE;q=0.8,sv;q=0.7"
_RG_BIN = "rg"
_MAX_READ_CHARS = max(2000, int((os.getenv("NOUSE_LOCAL_FILE_MAX_CHARS") or "12000").strip()))
_MAX_FIND_RESULTS = max(5, int((os.getenv("NOUSE_LOCAL_FIND_MAX_RESULTS") or "80").strip()))
_MAX_SEARCH_RESULTS = max(5, int((os.getenv("NOUSE_LOCAL_SEARCH_MAX_RESULTS") or "120").strip()))
_MAX_TEXT_FILE_BYTES = max(1024, int((os.getenv("NOUSE_LOCAL_TEXT_FILE_MAX_BYTES") or "4000000").strip()))
_MAX_FILE_SCAN_BYTES = max(1024, int((os.getenv("NOUSE_LOCAL_SCAN_FILE_MAX_BYTES") or "2000000").strip()))

_SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "node_modules",
    ".cache",
    ".trash",
    ".local",
}
_PSEUDO_FS_TYPES = {
    "proc",
    "sysfs",
    "tmpfs",
    "devtmpfs",
    "devpts",
    "cgroup",
    "cgroup2",
    "pstore",
    "securityfs",
    "debugfs",
    "tracefs",
    "configfs",
    "overlay",
    "squashfs",
    "rpc_pipefs",
    "autofs",
    "fusectl",
    "mqueue",
}

try:
    FETCH_TIMEOUT_SEC = max(5.0, float((os.getenv("NOUSE_FETCH_TIMEOUT_SEC") or "20").strip()))
except ValueError:
    FETCH_TIMEOUT_SEC = 20.0

# ── Ollama Tool Definitions ──────────────────────────────────────────────────

MCP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Sök på internet. "
                "Använd för att hitta uppdaterad eller saknad information. "
                "Valfritt: ange provider (t.ex. brave) för att prioritera den i denna körning."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Sökfråga",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max antal träffar (default 5)",
                    },
                    "provider": {
                        "type": "string",
                        "description": (
                            "Valfri sökprovider: auto | brave | serper | tavily | "
                            "duckduckgo | ddg | duckduckgo_html"
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Hämta textinnehållet från en specifik URL. "
                "Används för att läsa artiklar eller uppslagsverk som hittats via web_search."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Exakt URL att läsa",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_local_mounts",
            "description": (
                "Lista lokala mountpoints/diskar som kan genomsökas. "
                "Använd först för att förstå var data och papers finns."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_local_files",
            "description": (
                "Sök filer lokalt på datorn (read-only). Bra för papers, datasets, kod och anteckningar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Del av filnamn eller söksträng i sökväg.",
                    },
                    "roots": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Valfria rotkataloger. Om tomt används standard roots/mounts.",
                    },
                    "extensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filändelser, t.ex. ['pdf','md','txt'].",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max antal träffar (default 80).",
                    },
                    "include_hidden": {
                        "type": "boolean",
                        "description": "Inkludera dolda filer/mappar.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_local_text",
            "description": (
                "Sök textinnehåll i lokala filer (read-only). "
                "Returnerar fil, radnummer och utdrag."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text/regex att hitta i lokala filer.",
                    },
                    "roots": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Valfria rotkataloger. Om tomt används standard roots/mounts.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max antal matchrader (default 120).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_local_file",
            "description": (
                "Läs innehåll från lokal fil (read-only). Stöd för text och PDF (via pdftotext om tillgängligt)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolut eller relativ filväg att läsa.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Max antal tecken i svaret (default 12000).",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Startlinje (1-baserad, valfri).",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Slutlinje (1-baserad, valfri).",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kernel_get_identity",
            "description": "Returnerar kernel-identitet: mission, roll, constraints och status.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kernel_get_working_context",
            "description": "Hämtar kort working-memory-kontext för snabb chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max antal items (default 12).",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kernel_retrieve_memory",
            "description": "Söker minnesrelevans i working, episodic preview och semantic facts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Sökfråga mot minnen.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max antal träffar (default 8).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kernel_write_episode",
            "description": "Skriver en episod till working/episodic memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "source": {"type": "string"},
                    "domain_hint": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kernel_propose_fact",
            "description": "Föreslår fact med evidence_ref/confidence för senare konsolidering.",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "evidence_ref": {"type": "string"},
                    "confidence": {"type": "number"},
                    "source": {"type": "string"},
                },
                "required": ["claim"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kernel_link_concepts",
            "description": "Föreslår konceptlankning (src/type/tgt) med evidensscore.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string"},
                    "rel_type": {"type": "string"},
                    "tgt": {"type": "string"},
                    "why": {"type": "string"},
                    "evidence_score": {"type": "number"},
                    "assumption_flag": {"type": "boolean"},
                },
                "required": ["src", "rel_type", "tgt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kernel_log_outcome",
            "description": "Loggar resultat för handling med trace_id/run_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "outcome": {"type": "string"},
                    "trace_id": {"type": "string"},
                    "run_id": {"type": "string"},
                },
                "required": ["action", "outcome"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kernel_reflect",
            "description": "Skriver metakognitiv reflektion till memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string"},
                    "trace_id": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kernel_promote_memory",
            "description": "Guarded: initierar memory-promotion; kräver policy-allow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_episodes": {"type": "integer"},
                    "strict_min_evidence": {"type": "number"},
                    "approval_token": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kernel_update_policy",
            "description": "Guarded: policyförslag; blockeras utan explicit allow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "change_request": {"type": "string"},
                    "approval_token": {"type": "string"},
                },
                "required": ["change_request"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kernel_execute_self_update",
            "description": "Guarded: self-update request; blockeras utan explicit allow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan": {"type": "string"},
                    "approval_token": {"type": "string"},
                },
                "required": ["plan"],
            },
        },
    },
]

# ── Tool Implementations ─────────────────────────────────────────────────────

def _normalize_search_provider(provider: str | None) -> str:
    p = str(provider or "").strip().lower()
    aliases = {
        "": "auto",
        "default": "auto",
        "ddg": "duckduckgo",
        "duck": "duckduckgo",
        "brave_search": "brave",
        "google_serper": "serper",
    }
    return aliases.get(p, p or "auto")


def _provider_order(preferred: str) -> list[str]:
    base = ["serper", "tavily", "brave", "duckduckgo", "duckduckgo_html"]
    if preferred in {"auto", ""}:
        return base
    if preferred not in set(base):
        return base
    return [preferred] + [name for name in base if name != preferred]


def web_search(query: str, max_results: int = 5, provider: str | None = None) -> dict[str, Any]:
    """Utför en webbsökning med valbar provider-prioritering."""
    preferred = _normalize_search_provider(provider)
    order = _provider_order(preferred)

    for name in order:
        if name == "serper":
            if not os.getenv("SERPER_API_KEY"):
                continue
            out = _search_serper(query, max_results=max_results)
            if "error" not in out:
                if preferred != "auto":
                    out["provider_requested"] = preferred
                return out
            continue

        if name == "tavily":
            if not os.getenv("TAVILY_API_KEY"):
                continue
            out = _search_tavily(query, max_results=max_results)
            if "error" not in out:
                if preferred != "auto":
                    out["provider_requested"] = preferred
                return out
            continue

        if name == "brave":
            brave_key = os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY")
            if not brave_key:
                continue
            out = _search_brave(query, max_results=max_results, api_key=brave_key)
            if "error" not in out:
                if preferred != "auto":
                    out["provider_requested"] = preferred
                return out
            continue

        if name == "duckduckgo":
            try:
                results = []
                with DDGS() as ddgs:
                    for r in ddgs.text(query, max_results=max_results):
                        results.append(r)
                if results:
                    payload: dict[str, Any] = {
                        "provider": "duckduckgo",
                        "query": query,
                        "results": results,
                    }
                    if preferred != "auto":
                        payload["provider_requested"] = preferred
                    return payload
            except Exception as e:
                log.warning(f"web_search misslyckades för '{query}': {e}")
            continue

        if name == "duckduckgo_html":
            try:
                html_rows = _search_duckduckgo_html(query, max_results=max_results)
                if html_rows:
                    payload = {
                        "provider": "duckduckgo_html",
                        "query": query,
                        "results": html_rows,
                    }
                    if preferred != "auto":
                        payload["provider_requested"] = preferred
                    return payload
            except Exception as e:
                log.warning(f"web_search html-fallback misslyckades för '{query}': {e}")

    out: dict[str, Any] = {"provider": "none", "query": query, "results": []}
    if preferred != "auto":
        out["provider_requested"] = preferred
    return out


def _search_duckduckgo_html(query: str, max_results: int) -> list[dict[str, Any]]:
    safe_max = max(1, min(int(max_results or 5), 20))
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        resp = client.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
            },
        )
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text or "", "lxml")
    rows: list[dict[str, Any]] = []
    for node in soup.select(".result"):
        if len(rows) >= safe_max:
            break
        link = node.select_one("a.result__a")
        snippet = node.select_one(".result__snippet")
        if not link:
            continue
        href = (link.get("href") or "").strip()
        href = _normalize_duckduckgo_href(href)
        title = link.get_text(" ", strip=True)
        body = snippet.get_text(" ", strip=True) if snippet else ""
        if not href:
            continue
        rows.append({"title": title, "href": href, "body": body})
    return rows


def _normalize_duckduckgo_href(href: str) -> str:
    h = str(href or "").strip()
    if not h:
        return ""
    if h.startswith("//"):
        h = "https:" + h
    if "duckduckgo.com/l/?" not in h:
        return h
    try:
        parsed = urlparse(h)
        uddg = (parse_qs(parsed.query).get("uddg") or [""])[0]
        if uddg:
            return unquote(uddg)
    except Exception:
        return h
    return h


def _search_serper(query: str, max_results: int) -> dict[str, Any]:
    try:
        api_key = os.environ["SERPER_API_KEY"]
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
        organic = data.get("organic") or []
        results = [
            {
                "title": r.get("title", ""),
                "href": r.get("link", ""),
                "body": r.get("snippet", ""),
            }
            for r in organic[:max_results]
        ]
        return {"provider": "serper", "query": query, "results": results}
    except Exception as e:
        log.warning(f"serper search misslyckades: {e}")
        return {"error": str(e)}


def _search_tavily(query: str, max_results: int) -> dict[str, Any]:
    try:
        api_key = os.environ["TAVILY_API_KEY"]
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": max_results,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        rows = data.get("results") or []
        results = [
            {
                "title": r.get("title", ""),
                "href": r.get("url", ""),
                "body": r.get("content", ""),
            }
            for r in rows[:max_results]
        ]
        return {"provider": "tavily", "query": query, "results": results}
    except Exception as e:
        log.warning(f"tavily search misslyckades: {e}")
        return {"error": str(e)}


def _search_brave(query: str, max_results: int, api_key: str) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": api_key,
                },
                params={"q": query, "count": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
        rows = (data.get("web") or {}).get("results") or []
        results = [
            {
                "title": r.get("title", ""),
                "href": r.get("url", ""),
                "body": r.get("description", ""),
            }
            for r in rows[:max_results]
        ]
        return {"provider": "brave", "query": query, "results": results}
    except Exception as e:
        log.warning(f"brave search misslyckades: {e}")
        return {"error": str(e)}

def _extract_main_text(raw_html: str, max_chars: int = 4000) -> str:
    soup = BeautifulSoup(raw_html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n").strip()
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    cleaned_text = "\n".join(lines)
    if len(cleaned_text) > max_chars:
        return cleaned_text[:max_chars] + "\n... [TRUNKED]"
    return cleaned_text


def _fetch_via_jina(url: str) -> dict[str, Any]:
    """Fallback för sidor som blockerar direkt GET (ex. 403)."""
    proxy_url = f"https://r.jina.ai/http://{quote(url, safe=':/?&=#%')}"
    with httpx.Client(timeout=FETCH_TIMEOUT_SEC, follow_redirects=True) as client:
        resp = client.get(
            proxy_url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
                "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.1",
            },
        )
        resp.raise_for_status()
    content = (resp.text or "").strip()
    if len(content) > 4000:
        content = content[:4000] + "\n... [TRUNKED]"
    return {"url": url, "content": content, "source": "jina_fallback"}


def fetch_url(url: str) -> dict[str, Any]:
    """Hämta webbsidans huvudtext med fallback vid blockering."""
    try:
        with httpx.Client(timeout=FETCH_TIMEOUT_SEC, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
                    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
                },
            )
            if resp.status_code >= 400:
                if resp.status_code in {401, 403, 429, 503}:
                    try:
                        return _fetch_via_jina(url)
                    except Exception:
                        pass
                resp.raise_for_status()

            content_type = (resp.headers.get("content-type") or "").lower()
            is_pdf = ("pdf" in content_type) or str(url).lower().endswith(".pdf")
            if is_pdf:
                pdf = _extract_pdf_from_bytes(resp.content, max_chars=4000)
                if "error" in pdf:
                    return pdf
                return {
                    "url": url,
                    "content": str(pdf.get("content") or ""),
                    "source": "direct_fetch_pdf",
                    "truncated": bool(pdf.get("truncated")),
                }
            if "text/html" in content_type:
                cleaned_text = _extract_main_text(resp.text, max_chars=4000)
            else:
                cleaned_text = (resp.text or "").strip()
                if len(cleaned_text) > 4000:
                    cleaned_text = cleaned_text[:4000] + "\n... [TRUNKED]"
            return {"url": url, "content": cleaned_text, "source": "direct_fetch"}
    except Exception as e:
        log.warning(f"fetch_url misslyckades för '{url}': {e}")
        return {"error": str(e)}


def _extract_pdf_from_bytes(content: bytes, *, max_chars: int) -> dict[str, Any]:
    if not content:
        return {"error": "empty pdf content"}
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        text = extract_text(tmp_path) or ""
    finally:
        tmp_path.unlink(missing_ok=True)
    if not text.strip():
        return {"error": "pdf extract failed (empty text)"}
    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    return {"content": text, "truncated": truncated}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_KERNEL_MISSION = (
    os.getenv("NOUSE_KERNEL_MISSION")
    or "Att utvecklas till den forsta verifierbara brain-first AI:n"
).strip()
_KERNEL_ROLE = (os.getenv("NOUSE_KERNEL_ROLE") or "brain-kernel").strip()


def _kernel_memory() -> MemoryStore:
    return MemoryStore()


def _kernel_policy_allows_guarded_write(approval_token: str | None = None) -> bool:
    env_allow = (os.getenv("NOUSE_KERNEL_ALLOW_GUARDED_WRITES") or "").strip().lower()
    if env_allow in {"1", "true", "yes", "on"}:
        return True
    expected = (os.getenv("NOUSE_KERNEL_APPROVAL_TOKEN") or "").strip()
    token = (approval_token or "").strip()
    return bool(expected and token and token == expected)


def _kernel_guard_or_block(operation: str, approval_token: str | None = None) -> dict[str, Any] | None:
    if _kernel_policy_allows_guarded_write(approval_token):
        return None
    return {
        "error": "guarded_write_blocked",
        "operation": operation,
        "policy": {
            "requires": ["NOUSE_KERNEL_ALLOW_GUARDED_WRITES=1 or valid approval_token"],
            "hint": "Set env var for controlled runtime or pass approval_token configured in NOUSE_KERNEL_APPROVAL_TOKEN.",
        },
        "ts": _now_iso(),
    }


def kernel_get_identity() -> dict[str, Any]:
    mem = _kernel_memory()
    audit = mem.audit(limit=5)
    return {
        "ts": _now_iso(),
        "role": _KERNEL_ROLE,
        "mission": _KERNEL_MISSION,
        "constraints": [
            "speed_first_chat",
            "evidence_gated_memory",
            "guarded_high_risk_writes",
        ],
        "memory": {
            "working_items": int(audit.get("working_items", 0) or 0),
            "episodes_total": int(audit.get("episodes_total", 0) or 0),
            "semantic_facts": int(audit.get("semantic_facts", 0) or 0),
            "unconsolidated_total": int(audit.get("unconsolidated_total", 0) or 0),
        },
    }


def kernel_get_working_context(limit: int = 12) -> dict[str, Any]:
    safe_limit = _safe_int(limit, 12, minimum=1, maximum=80)
    rows = _kernel_memory().working_snapshot(limit=safe_limit)
    return {"ts": _now_iso(), "limit": safe_limit, "results": rows}


def _kernel_load_semantic_dialogue_facts() -> dict[str, Any]:
    mem = _kernel_memory()
    try:
        raw = json.loads(mem.semantic_path.read_text(encoding="utf-8"))
        return dict(raw.get("dialogue_facts") or {})
    except Exception:
        return {}


def kernel_retrieve_memory(query: str, limit: int = 8) -> dict[str, Any]:
    q = str(query or "").strip().lower()
    if not q:
        return {"error": "query required"}
    safe_limit = _safe_int(limit, 8, minimum=1, maximum=50)

    mem = _kernel_memory()
    out: list[dict[str, Any]] = []

    for row in mem.working_snapshot(limit=min(120, safe_limit * 5)):
        hay = " ".join(
            [
                str(row.get("summary") or ""),
                " ".join(str(x) for x in (row.get("cues") or [])),
                str(row.get("domain_hint") or ""),
            ]
        ).lower()
        if q in hay:
            out.append({"source": "working", "item": row})
            if len(out) >= safe_limit:
                return {"query": query, "results": out, "truncated": True}

    audit = mem.audit(limit=max(5, safe_limit * 2))
    for row in (audit.get("unconsolidated_preview") or []):
        hay = " ".join(
            [
                str(row.get("domain_hint") or ""),
                str(row.get("source") or ""),
            ]
        ).lower()
        if q in hay:
            out.append({"source": "episodic_preview", "item": row})
            if len(out) >= safe_limit:
                return {"query": query, "results": out, "truncated": True}

    dialogue_facts = _kernel_load_semantic_dialogue_facts()
    for key, row in dialogue_facts.items():
        r = row if isinstance(row, dict) else {}
        hay = " ".join(
            [
                str(key),
                str(r.get("question") or ""),
                str(r.get("answer") or ""),
            ]
        ).lower()
        if q not in hay:
            continue
        out.append(
            {
                "source": "semantic_dialogue",
                "item": {
                    "question": str(r.get("question") or ""),
                    "answer": str(r.get("answer") or ""),
                    "support": int(r.get("support", 0) or 0),
                    "last_seen": str(r.get("last_seen") or ""),
                },
            }
        )
        if len(out) >= safe_limit:
            return {"query": query, "results": out, "truncated": True}

    return {"query": query, "results": out, "truncated": False}


def kernel_write_episode(
    text: str,
    *,
    source: str = "kernel",
    domain_hint: str = "kernel",
    path: str = "",
) -> dict[str, Any]:
    episode = _kernel_memory().ingest_episode(
        text,
        {"source": source, "domain_hint": domain_hint, "path": path},
        [],
    )
    return {"status": "ok", "episode_id": str(episode.get("id") or ""), "ts": _now_iso()}


def kernel_propose_fact(
    claim: str,
    *,
    evidence_ref: str = "",
    confidence: float = 0.5,
    source: str = "kernel_fact_proposal",
) -> dict[str, Any]:
    c = max(0.0, min(1.0, float(confidence)))
    payload = (
        f"Fact proposal: {claim}\n"
        f"EvidenceRef: {evidence_ref or 'none'}\n"
        f"Confidence: {c:.3f}"
    )
    episode = _kernel_memory().ingest_episode(
        payload,
        {"source": source, "domain_hint": "fact_proposal", "path": evidence_ref or ""},
        [],
    )
    return {
        "status": "accepted_as_proposal",
        "episode_id": str(episode.get("id") or ""),
        "confidence": c,
        "ts": _now_iso(),
    }


def kernel_link_concepts(
    src: str,
    rel_type: str,
    tgt: str,
    *,
    why: str = "",
    evidence_score: float = 0.5,
    assumption_flag: bool = False,
) -> dict[str, Any]:
    relation = {
        "src": str(src or "").strip(),
        "type": str(rel_type or "").strip(),
        "tgt": str(tgt or "").strip(),
        "why": str(why or "").strip(),
        "domain_src": "kernel",
        "domain_tgt": "kernel",
        "evidence_score": max(0.0, min(1.0, float(evidence_score))),
        "assumption_flag": bool(assumption_flag),
    }
    if not relation["src"] or not relation["type"] or not relation["tgt"]:
        return {"error": "src, rel_type and tgt are required"}
    text = f"Link proposal: {relation['src']} --{relation['type']}--> {relation['tgt']}"
    episode = _kernel_memory().ingest_episode(
        text,
        {"source": "kernel_link_concepts", "domain_hint": "relation_proposal", "path": ""},
        [relation],
    )
    return {"status": "ok", "episode_id": str(episode.get("id") or ""), "ts": _now_iso()}


def kernel_log_outcome(
    action: str,
    outcome: str,
    *,
    trace_id: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    text = (
        f"Outcome\n"
        f"Action: {action}\n"
        f"Result: {outcome}\n"
        f"TraceID: {trace_id or '-'}\n"
        f"RunID: {run_id or '-'}"
    )
    episode = _kernel_memory().ingest_episode(
        text,
        {"source": "kernel_outcome", "domain_hint": "outcome_log", "path": run_id or ""},
        [],
    )
    return {"status": "ok", "episode_id": str(episode.get("id") or ""), "ts": _now_iso()}


def kernel_reflect(note: str, *, trace_id: str = "", source: str = "kernel_reflection") -> dict[str, Any]:
    text = f"Reflection: {note}\nTraceID: {trace_id or '-'}"
    episode = _kernel_memory().ingest_episode(
        text,
        {"source": source, "domain_hint": "metacognition", "path": ""},
        [],
    )
    return {"status": "ok", "episode_id": str(episode.get("id") or ""), "ts": _now_iso()}


def kernel_promote_memory(
    *,
    max_episodes: int = 40,
    strict_min_evidence: float = 0.65,
    approval_token: str | None = None,
) -> dict[str, Any]:
    blocked = _kernel_guard_or_block("kernel_promote_memory", approval_token)
    if blocked is not None:
        return blocked
    safe_max = _safe_int(max_episodes, 40, minimum=1, maximum=200)
    safe_min_evidence = max(0.0, min(1.0, float(strict_min_evidence)))
    # Phase-1 behavior: acknowledge guarded intent and return current audit snapshot.
    audit = _kernel_memory().audit(limit=5)
    return {
        "status": "accepted",
        "operation": "kernel_promote_memory",
        "phase": "v1",
        "requested": {
            "max_episodes": safe_max,
            "strict_min_evidence": safe_min_evidence,
        },
        "memory": {
            "unconsolidated_total": int(audit.get("unconsolidated_total", 0) or 0),
            "semantic_facts": int(audit.get("semantic_facts", 0) or 0),
        },
        "ts": _now_iso(),
    }


def kernel_update_policy(change_request: str, *, approval_token: str | None = None) -> dict[str, Any]:
    blocked = _kernel_guard_or_block("kernel_update_policy", approval_token)
    if blocked is not None:
        return blocked
    payload = f"Policy update request: {change_request}"
    episode = _kernel_memory().ingest_episode(
        payload,
        {"source": "kernel_policy_update", "domain_hint": "policy", "path": ""},
        [],
    )
    return {"status": "accepted", "episode_id": str(episode.get("id") or ""), "ts": _now_iso()}


def kernel_execute_self_update(plan: str, *, approval_token: str | None = None) -> dict[str, Any]:
    blocked = _kernel_guard_or_block("kernel_execute_self_update", approval_token)
    if blocked is not None:
        return blocked
    payload = f"Self-update request: {plan}"
    episode = _kernel_memory().ingest_episode(
        payload,
        {"source": "kernel_self_update", "domain_hint": "self_update", "path": ""},
        [],
    )
    return {"status": "accepted", "episode_id": str(episode.get("id") or ""), "ts": _now_iso()}


def _safe_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = default
    return max(minimum, min(maximum, v))


def _normalize_ext(ext: str) -> str:
    e = str(ext or "").strip().lower()
    if not e:
        return ""
    if not e.startswith("."):
        e = "." + e
    return e


def _is_data_mount(device: str, mountpoint: str, fs_type: str) -> bool:
    mp = str(mountpoint or "").strip()
    dev = str(device or "").strip()
    fst = str(fs_type or "").strip().lower()
    if not mp:
        return False
    if fst in _PSEUDO_FS_TYPES:
        return False
    if mp == "/":
        return True
    if mp.startswith(("/proc", "/sys", "/run", "/dev", "/snap")):
        return False
    if dev.startswith("/dev/"):
        return True
    if mp == str(Path.home()):
        return True
    if mp.startswith(("/media/", "/mnt/", "/Volumes/")):
        return True
    return False


def list_local_mounts() -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    mounts_file = Path("/proc/mounts")
    if mounts_file.exists():
        seen = set()
        for line in mounts_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            device, mountpoint, fs_type = parts[0], parts[1], parts[2]
            if not _is_data_mount(device, mountpoint, fs_type):
                continue
            if mountpoint in seen:
                continue
            seen.add(mountpoint)
            rows.append({"device": device, "mountpoint": mountpoint, "fs_type": fs_type})
    else:
        # Fallback for non-Linux environments.
        home = str(Path.home())
        rows.append({"device": "local", "mountpoint": home, "fs_type": "unknown"})
    rows.sort(key=lambda r: r.get("mountpoint", ""))
    return {"ts": _now_iso(), "mounts": rows}


def _default_roots() -> list[Path]:
    env_roots_raw = (os.getenv("NOUSE_LOCAL_FS_ROOTS") or "").strip()
    if env_roots_raw:
        out = [Path(p).expanduser() for p in env_roots_raw.split(",") if p.strip()]
    else:
        # Start in home for låg latens och lägg sedan till faktiska mountpoints
        # för att ge bred lokal täckning (system + externa diskar).
        out = [Path.home()]
        mount_info = list_local_mounts().get("mounts")
        if isinstance(mount_info, list):
            for row in mount_info:
                if not isinstance(row, dict):
                    continue
                mountpoint = str(row.get("mountpoint") or "").strip()
                if mountpoint:
                    out.append(Path(mountpoint))

    dedup: list[Path] = []
    seen = set()
    for p in out:
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        key = str(rp)
        if key in seen:
            continue
        seen.add(key)
        if rp.exists():
            dedup.append(rp)
    return dedup


def _resolve_roots(raw_roots: Any) -> list[Path]:
    if isinstance(raw_roots, list) and raw_roots:
        roots: list[Path] = []
        for item in raw_roots:
            try:
                p = Path(str(item)).expanduser().resolve()
            except Exception:
                continue
            if p.exists():
                roots.append(p)
        if roots:
            return roots
    return _default_roots()


def _walk_candidate_files(
    roots: list[Path],
    *,
    include_hidden: bool,
) -> Iterator[Path]:
    for root in roots:
        if root.is_file():
            yield root
            continue
        if not root.is_dir():
            continue
        try:
            root_dev = root.stat().st_dev
        except Exception:
            root_dev = None
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            if not include_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
            # Undvik att korsa till andra filsystem (t.ex. /proc, nätmounts)
            # när vi redan skannar ett specifikt root.
            if root_dev is not None:
                kept: list[str] = []
                for d in dirnames:
                    child = Path(dirpath) / d
                    try:
                        if child.is_symlink():
                            continue
                        if child.stat().st_dev != root_dev:
                            continue
                        kept.append(d)
                    except Exception:
                        continue
                dirnames[:] = kept
            for fname in filenames:
                if not include_hidden and fname.startswith("."):
                    continue
                yield Path(dirpath) / fname


def find_local_files(
    query: str,
    roots: list[str] | None = None,
    *,
    extensions: list[str] | None = None,
    max_results: int = _MAX_FIND_RESULTS,
    include_hidden: bool = False,
) -> dict[str, Any]:
    q = str(query or "").strip().lower()
    if not q:
        return {"error": "query required"}
    safe_max = _safe_int(max_results, _MAX_FIND_RESULTS, minimum=1, maximum=500)
    root_paths = _resolve_roots(roots)
    ext_filter = set(
        e for e in (_normalize_ext(x) for x in (extensions or [])) if e
    )

    results: list[dict[str, Any]] = []
    scanned = 0
    for path in _walk_candidate_files(root_paths, include_hidden=bool(include_hidden)):
        scanned += 1
        try:
            spath = str(path)
            name = path.name
            if q not in name.lower() and q not in spath.lower():
                continue
            if ext_filter and path.suffix.lower() not in ext_filter:
                continue
            st = path.stat()
            results.append(
                {
                    "path": spath,
                    "name": name,
                    "size_bytes": int(st.st_size),
                    "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                }
            )
            if len(results) >= safe_max:
                break
        except Exception:
            continue

    return {
        "query": query,
        "roots": [str(p) for p in root_paths],
        "scanned_candidates": scanned,
        "results": results,
        "truncated": len(results) >= safe_max,
    }


def _read_pdf_text(path: Path, max_chars: int) -> dict[str, Any]:
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        try:
            proc = subprocess.run(
                [pdftotext, "-layout", "-nopgbrk", str(path), "-"],
                capture_output=True,
                text=True,
                check=False,
                timeout=60.0,
            )
        except Exception as e:
            return {"error": f"pdf read failed: {e}"}
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            return {"error": f"pdf read failed: {stderr or 'unknown error'}"}
        text = proc.stdout or ""
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
    else:
        text = extract_text(path)
        if not text.strip():
            return {
                "error": (
                    "pdf read failed: pdftotext saknas och pypdf-extraktion gav tom text. "
                    "Installera poppler-utils eller pypdf."
                )
            }
    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    return {"content": text, "truncated": truncated}


def read_local_file(
    path: str,
    *,
    max_chars: int = _MAX_READ_CHARS,
    start_line: int = 1,
    end_line: int = 0,
) -> dict[str, Any]:
    try:
        p = Path(str(path or "")).expanduser().resolve()
    except Exception:
        return {"error": "invalid path"}
    if not p.exists() or not p.is_file():
        return {"error": f"file not found: {p}"}

    safe_max_chars = _safe_int(max_chars, _MAX_READ_CHARS, minimum=500, maximum=100_000)
    safe_start = max(1, int(start_line or 1))
    safe_end = max(0, int(end_line or 0))

    if p.suffix.lower() == ".pdf":
        pdf = _read_pdf_text(p, safe_max_chars)
        if "error" in pdf:
            return pdf
        text = str(pdf.get("content") or "")
        truncated = bool(pdf.get("truncated"))
    else:
        try:
            raw = p.read_bytes()
        except Exception as e:
            return {"error": f"read failed: {e}"}
        if len(raw) > _MAX_TEXT_FILE_BYTES:
            raw = raw[:_MAX_TEXT_FILE_BYTES]
            truncated = True
        else:
            truncated = False
        if b"\x00" in raw:
            return {"error": "binary file; use a text/pdf file instead"}
        text = raw.decode("utf-8", errors="ignore")
        if len(text) > safe_max_chars:
            text = text[:safe_max_chars]
            truncated = True

    lines = text.splitlines()
    if safe_end > 0:
        lines = lines[safe_start - 1 : safe_end]
    else:
        lines = lines[safe_start - 1 :]
    text_out = "\n".join(lines)
    return {
        "path": str(p),
        "size_bytes": int(p.stat().st_size),
        "content": text_out,
        "line_start": safe_start,
        "line_end": safe_end if safe_end > 0 else None,
        "truncated": truncated,
    }


def _search_local_text_rg(query: str, roots: list[Path], *, max_results: int) -> list[dict[str, Any]]:
    rg_bin = shutil.which(_RG_BIN)
    if not rg_bin:
        return []
    cmd = [
        rg_bin,
        "--line-number",
        "--with-filename",
        "--color",
        "never",
        "--smart-case",
        "--max-count",
        "3",
        query,
    ] + [str(r) for r in roots]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30.0,
            check=False,
        )
    except Exception:
        return []
    if proc.returncode not in {0, 1}:
        return []
    rows: list[dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        if len(rows) >= max_results:
            break
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        fpath, lno, snippet = parts[0], parts[1], parts[2]
        try:
            line_no = int(lno)
        except ValueError:
            line_no = 0
        rows.append({"path": fpath, "line": line_no, "snippet": snippet.strip()[:500]})
    return rows


def _search_local_text_fallback(query: str, roots: list[Path], *, max_results: int) -> list[dict[str, Any]]:
    q = query.lower()
    rows: list[dict[str, Any]] = []
    for path in _walk_candidate_files(roots, include_hidden=False):
        if len(rows) >= max_results:
            break
        try:
            if path.stat().st_size > _MAX_FILE_SCAN_BYTES:
                continue
            raw = path.read_bytes()
            if b"\x00" in raw:
                continue
            text = raw.decode("utf-8", errors="ignore")
            for idx, line in enumerate(text.splitlines(), start=1):
                if q in line.lower():
                    rows.append({"path": str(path), "line": idx, "snippet": line.strip()[:500]})
                    if len(rows) >= max_results:
                        break
        except Exception:
            continue
    return rows


def search_local_text(
    query: str,
    roots: list[str] | None = None,
    *,
    max_results: int = _MAX_SEARCH_RESULTS,
) -> dict[str, Any]:
    q = str(query or "").strip()
    if not q:
        return {"error": "query required"}
    safe_max = _safe_int(max_results, _MAX_SEARCH_RESULTS, minimum=1, maximum=500)
    root_paths = _resolve_roots(roots)
    rows = _search_local_text_rg(q, root_paths, max_results=safe_max)
    provider = "rg"
    if not rows:
        rows = _search_local_text_fallback(q, root_paths, max_results=safe_max)
        provider = "python_fallback"
    return {
        "query": q,
        "roots": [str(p) for p in root_paths],
        "provider": provider,
        "results": rows[:safe_max],
        "truncated": len(rows) >= safe_max,
    }


def is_mcp_tool(name: str) -> bool:
    """Returnerar True om verktyget hanteras av denna gateway."""
    return name in (
        "web_search",
        "fetch_url",
        "list_local_mounts",
        "find_local_files",
        "search_local_text",
        "read_local_file",
        "kernel_get_identity",
        "kernel_get_working_context",
        "kernel_retrieve_memory",
        "kernel_write_episode",
        "kernel_propose_fact",
        "kernel_link_concepts",
        "kernel_log_outcome",
        "kernel_reflect",
        "kernel_promote_memory",
        "kernel_update_policy",
        "kernel_execute_self_update",
    )

def execute_mcp_tool(name: str, args: dict[str, Any]) -> Any:
    """Kör MCP-verktyg och returnerar resultatet."""
    if name == "web_search":
        provider = args.get("provider")
        if not str(provider or "").strip():
            env_default = str(os.getenv("NOUSE_WEB_SEARCH_DEFAULT_PROVIDER") or "").strip()
            if env_default:
                provider = env_default
            elif (os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY")):
                provider = "brave"
        return web_search(
            args["query"],
            args.get("max_results", 5),
            provider=provider,
        )
    if name == "fetch_url":
        return fetch_url(args["url"])
    if name == "list_local_mounts":
        return list_local_mounts()
    if name == "find_local_files":
        return find_local_files(
            args["query"],
            args.get("roots"),
            extensions=args.get("extensions"),
            max_results=args.get("max_results", _MAX_FIND_RESULTS),
            include_hidden=bool(args.get("include_hidden", False)),
        )
    if name == "search_local_text":
        return search_local_text(
            args["query"],
            args.get("roots"),
            max_results=args.get("max_results", _MAX_SEARCH_RESULTS),
        )
    if name == "read_local_file":
        return read_local_file(
            args["path"],
            max_chars=args.get("max_chars", _MAX_READ_CHARS),
            start_line=args.get("start_line", 1),
            end_line=args.get("end_line", 0),
        )
    if name == "kernel_get_identity":
        return kernel_get_identity()
    if name == "kernel_get_working_context":
        return kernel_get_working_context(limit=args.get("limit", 12))
    if name == "kernel_retrieve_memory":
        return kernel_retrieve_memory(args["query"], limit=args.get("limit", 8))
    if name == "kernel_write_episode":
        return kernel_write_episode(
            args["text"],
            source=args.get("source", "kernel"),
            domain_hint=args.get("domain_hint", "kernel"),
            path=args.get("path", ""),
        )
    if name == "kernel_propose_fact":
        return kernel_propose_fact(
            args["claim"],
            evidence_ref=args.get("evidence_ref", ""),
            confidence=args.get("confidence", 0.5),
            source=args.get("source", "kernel_fact_proposal"),
        )
    if name == "kernel_link_concepts":
        return kernel_link_concepts(
            args["src"],
            args["rel_type"],
            args["tgt"],
            why=args.get("why", ""),
            evidence_score=args.get("evidence_score", 0.5),
            assumption_flag=bool(args.get("assumption_flag", False)),
        )
    if name == "kernel_log_outcome":
        return kernel_log_outcome(
            args["action"],
            args["outcome"],
            trace_id=args.get("trace_id", ""),
            run_id=args.get("run_id", ""),
        )
    if name == "kernel_reflect":
        return kernel_reflect(
            args["note"],
            trace_id=args.get("trace_id", ""),
            source=args.get("source", "kernel_reflection"),
        )
    if name == "kernel_promote_memory":
        return kernel_promote_memory(
            max_episodes=args.get("max_episodes", 40),
            strict_min_evidence=args.get("strict_min_evidence", 0.65),
            approval_token=args.get("approval_token"),
        )
    if name == "kernel_update_policy":
        return kernel_update_policy(
            args["change_request"],
            approval_token=args.get("approval_token"),
        )
    if name == "kernel_execute_self_update":
        return kernel_execute_self_update(
            args["plan"],
            approval_token=args.get("approval_token"),
        )
    return {"error": f"Okänt MCP-verktyg: {name}"}
