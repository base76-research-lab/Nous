from __future__ import annotations

import importlib.metadata
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from rich.markdown import Markdown
from rich.panel import Panel

from nouse.cli.commands import relay as relay_mod
from nouse.cli.commands import status as status_mod
from nouse.cli.console import console

app = typer.Typer(
    name="nouse",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
    help=(
        "νοῦς  v0.4.0\n\n"
        "Local cognitive substrate CLI.\n\n"
        "Quick start:\n"
        "  nouse start me\n"
        "  nouse start autonomy\n"
        "  nouse status\n"
    ),
)

app.add_typer(relay_mod.app, name="relay")


def _version_callback(value: bool) -> None:
    if not value:
        return
    try:
        version = importlib.metadata.version("nouse")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    typer.echo(f"nouse version {version}")
    raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Visa version och avsluta.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    from nouse.config.env import load_env_files

    load_env_files(force=True)
    if ctx.invoked_subcommand is None and not version:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


def _render_trace_rows(events: list[dict[str, Any]], trace_id: str = "") -> None:
    console.print(
        f"[bold cyan]Output Trace[/bold cyan]  "
        f"events={len(events)}"
        + (f"  [dim]trace_id={trace_id}[/dim]" if trace_id else "")
    )
    for event in events:
        ts = str(event.get("ts", ""))[:19]
        tid = str(event.get("trace_id", ""))[:26]
        ev = str(event.get("event", ""))
        endpoint = str(event.get("endpoint", "-"))
        model = event.get("model")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}

        summary = ""
        if "query" in payload:
            summary = f" q={str(payload['query'])[:120]}"
        elif "response" in payload:
            summary = f" rsp={str(payload['response'])[:120]}"
        elif "name" in payload:
            summary = f" tool={payload['name']}"
        elif "error" in payload:
            summary = f" err={str(payload['error'])[:120]}"
        elif "added" in payload:
            summary = f" added={payload['added']}"

        attack_plan = payload.get("attack_plan")
        if isinstance(attack_plan, dict):
            qn = len(attack_plan.get("questions") or [])
            cn = len(attack_plan.get("claims") or [])
            an = len(attack_plan.get("assumptions") or [])
            summary += f" plan=Q{qn}/C{cn}/A{an}"

        model_str = f" model={model}" if model else ""
        console.print(
            f"[dim]{ts}[/dim]  [cyan]{tid}[/cyan]  [bold]{ev}[/bold]  "
            f"[dim]{endpoint}{model_str}{summary}[/dim]"
        )


def _format_journal_ts(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "--:--:--"
    iso = raw
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%H:%M:%S")
    except Exception:
        pass
    # Fallback för redan korta tidsstämplar.
    if "T" in raw:
        tail = raw.split("T", 1)[1]
        return tail[:8]
    return raw[:8]


def _as_float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _journal_tail_rows(
    events: list[dict[str, Any]],
    *,
    stage: str = "",
    limit: int = 12,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 200))
    wanted_stage = str(stage or "").strip().lower()

    rows: list[dict[str, Any]] = []
    for event in events:
        if str(event.get("event") or "") != "cycle_trace":
            continue
        row_stage = str(event.get("stage") or "").strip() or "unknown_stage"
        if wanted_stage and row_stage.lower() != wanted_stage:
            continue
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        rows.append(
            {
                "ts": _format_journal_ts(event.get("ts")),
                "stage": row_stage,
                "result": str(event.get("result") or "").strip(),
                "thought": str(event.get("thought") or "").strip(),
                "avg_evidence": _as_float_or_none(details.get("avg_evidence")),
                "max_evidence": _as_float_or_none(details.get("max_evidence")),
                "quality": _as_float_or_none(details.get("quality")),
                "quality_avg": _as_float_or_none(details.get("quality_avg")),
                "details": details,
            }
        )
    return rows[-safe_limit:]


def _render_journal_tail(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[yellow]Inga cycle_trace-poster matchade filtret.[/yellow]")
        return
    for row in rows:
        stage = str(row.get("stage") or "unknown_stage")
        ts = str(row.get("ts") or "--:--:--")
        result = str(row.get("result") or "").strip()
        if len(result) > 140:
            result = result[:137] + "..."
        extras: list[str] = []
        avg_evidence = row.get("avg_evidence")
        if isinstance(avg_evidence, float):
            extras.append(f"avg_ev={avg_evidence:.3f}")
        max_evidence = row.get("max_evidence")
        if isinstance(max_evidence, float):
            extras.append(f"max_ev={max_evidence:.3f}")
        quality = row.get("quality")
        if isinstance(quality, float):
            extras.append(f"quality={quality:.3f}")
        quality_avg = row.get("quality_avg")
        if isinstance(quality_avg, float):
            extras.append(f"quality_avg={quality_avg:.3f}")
        suffix = f" [dim]({' · '.join(extras)})[/dim]" if extras else ""
        if result:
            console.print(f"- [dim]{ts}[/dim] [cyan]{stage}[/cyan]: {result}{suffix}")
        else:
            console.print(f"- [dim]{ts}[/dim] [cyan]{stage}[/cyan]{suffix}")


def _parse_extension_csv(raw: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for part in str(raw or "").split(","):
        text = part.strip().lower()
        if not text:
            continue
        if not text.startswith("."):
            text = f".{text}"
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _discover_iic_roots(explicit_root: str = "") -> list[Path]:
    roots: list[Path] = []
    home = Path.home()
    user = home.name

    if str(explicit_root or "").strip():
        roots.append(Path(explicit_root).expanduser())

    roots.extend(
        [
            Path("/media") / user / "iic",
            Path("/media") / user / "IIC",
            Path("/mnt/iic"),
            Path("/iic"),
            home / "iic",
            home / "projects" / "iic",
        ]
    )

    out: list[Path] = []
    seen: set[str] = set()
    for row in roots:
        key = str(row.resolve()) if row.exists() else str(row)
        if key in seen:
            continue
        seen.add(key)
        if row.exists() and row.is_dir():
            out.append(row)
    return out


def _queue_learn_fallback(text: str, source: str, reason: str) -> Path:
    from datetime import datetime, timezone

    queue_dir = Path.home() / ".local" / "share" / "nouse" / "capture_queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = queue_dir / f"learn_from_{stamp}.txt"
    payload = (
        "QUEUED_INGEST\n"
        f"source={source}\n"
        f"reason={reason}\n\n"
        f"{text}\n"
    )
    path.write_text(payload, encoding="utf-8")
    return path


def _infer_provider_for_model_input(model_text: str, explicit_provider: str = "") -> str:
    provider = str(explicit_provider or "").strip()
    if provider:
        return provider

    text = str(model_text or "").strip()
    if "/" in text:
        prefix = text.split("/", 1)[0].strip()
        if prefix:
            return prefix

    low = text.lower()
    if ":" in text:
        return "ollama"
    if low.startswith("claude"):
        return "anthropic"
    if low.startswith(("gpt-", "o1", "o3", "o4", "gemini", "mistral")):
        return "openai_compatible"
    return "ollama"


_OPENAI_COMPAT_ALIASES = {
    "openai",
    "openai_compatible",
    "codex",
    "minimax",
    "openrouter",
    "fireworks",
    "together",
    "groq",
    "anthropic",
    "xai",
    "google",
    "mistral",
    "zai",
    "bedrock",
    "github-copilot",
    "copilot",
    "qwen",
    "huggingface",
    "deepseek",
    "venice",
}


def _canonical_runtime_provider(provider: str) -> str:
    p = str(provider or "").strip().lower()
    if p in _OPENAI_COMPAT_ALIASES:
        return "openai_compatible"
    if p == "ollama":
        return "ollama"
    return p or "ollama"


def _has_openai_compatible_api_key() -> bool:
    try:
        from nouse.config.env import load_env_files

        load_env_files(force=True)
    except Exception:
        pass
    return bool((os.getenv("NOUSE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip())


def _dotenv_quote(value: str) -> str:
    raw = str(value or "")
    escaped = raw.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _upsert_env_key(path: Path, key: str, value: str) -> None:
    safe_key = str(key or "").strip()
    if not safe_key:
        raise ValueError("env key required")
    line = f"{safe_key}={_dotenv_quote(value)}"

    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()

    out: list[str] = []
    replaced = False
    for raw in lines:
        stripped = raw.lstrip()
        if stripped.startswith("#") or "=" not in stripped:
            out.append(raw)
            continue
        lhs = stripped.split("=", 1)[0].strip()
        if lhs == safe_key:
            if not replaced:
                out.append(line)
                replaced = True
            continue
        out.append(raw)
    if not replaced:
        out.append(line)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except Exception:
        pass


def _project_runtime_env(scope_root: Path, *, watch_project_only: bool = True) -> dict[str, str]:
    root = scope_root.expanduser().resolve()
    home = root / ".nouse"
    env: dict[str, str] = {
        "NOUSE_MODE": "project",
        "NOUSE_PROJECT_ROOT": str(root),
        "NOUSE_HOME": str(home),
        "NOUSE_FIELD_DB": str(home / "field.sqlite"),
        "NOUSE_MEMORY_DIR": str(home / "memory"),
        "NOUSE_TRACE_DIR": str(home / "trace"),
        "NOUSE_JOURNAL_DIR": str(home / "journal"),
        "NOUSE_SESSION_STATE_PATH": str(home / "session_state.json"),
        "NOUSE_CAPTURE_QUEUE_DIR": str(home / "capture_queue"),
        "NOUSE_GRAPH_CENTER_PATH": str(home / "graph_center.json"),
        "NOUSE_STATUS_FILE": str(home / "status.json"),
        "NOUSE_SOURCE_THROTTLE_FILE": str(home / "source_throttle.json"),
        "NOUSE_DAEMON_BASE": "http://127.0.0.1:8765",
        "NOUSE_WRITE_SCOPE": str(root),
        "NOUSE_WRITE_SCOPE_ENFORCE": "1",
    }
    if watch_project_only:
        env["NOUSE_WATCH_PATHS"] = str(root)
    return env


def _personal_runtime_env() -> dict[str, str]:
    home = Path.home() / ".local" / "share" / "nouse" / "personal"
    return {
        "NOUSE_MODE": "personal",
        "NOUSE_HOME": str(home),
        "NOUSE_FIELD_DB": str(home / "field.sqlite"),
        "NOUSE_MEMORY_DIR": str(home / "memory"),
        "NOUSE_TRACE_DIR": str(home / "trace"),
        "NOUSE_JOURNAL_DIR": str(home / "journal"),
        "NOUSE_SESSION_STATE_PATH": str(home / "session_state.json"),
        "NOUSE_CAPTURE_QUEUE_DIR": str(home / "capture_queue"),
        "NOUSE_GRAPH_CENTER_PATH": str(home / "graph_center.json"),
        "NOUSE_STATUS_FILE": str(home / "status.json"),
        "NOUSE_SOURCE_THROTTLE_FILE": str(home / "source_throttle.json"),
        "NOUSE_LIVING_CORE_PATH": str(home / "self" / "living_core.json"),
        "NOUSE_DAEMON_BASE": "http://127.0.0.1:8765",
    }


def _ensure_runtime_dirs_from_env(env_map: dict[str, str]) -> None:
    file_keys = {
        "NOUSE_FIELD_DB",
        "NOUSE_SESSION_STATE_PATH",
        "NOUSE_GRAPH_CENTER_PATH",
        "NOUSE_STATUS_FILE",
        "NOUSE_SOURCE_THROTTLE_FILE",
    }
    dir_keys = {
        "NOUSE_HOME",
        "NOUSE_MEMORY_DIR",
        "NOUSE_TRACE_DIR",
        "NOUSE_JOURNAL_DIR",
        "NOUSE_CAPTURE_QUEUE_DIR",
    }
    for key in dir_keys:
        raw = str(env_map.get(key) or "").strip()
        if not raw:
            continue
        Path(raw).expanduser().mkdir(parents=True, exist_ok=True)
    for key in file_keys:
        raw = str(env_map.get(key) or "").strip()
        if not raw:
            continue
        Path(raw).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _slugify_project_name(name: str) -> str:
    raw = str(name or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", raw)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-._")
    return cleaned or "nouse-brain"


def _write_text_if_missing(path: Path, content: str, *, force: bool = False) -> None:
    if path.exists() and not force:
        return
    path.write_text(content, encoding="utf-8")


def _compose_template() -> str:
    return """services:
  nouse:
    build:
      context: .
      dockerfile: Dockerfile.nouse
      args:
        NOUSE_INSTALL_REF: ${NOUSE_INSTALL_REF:-main}
    container_name: nouse-${PROJECT_SLUG}
    restart: unless-stopped
    env_file:
      - .env
    environment:
      - NOUSE_OLLAMA_HOST=${NOUSE_OLLAMA_HOST:-http://host.docker.internal:11434}
    volumes:
      - ./:/workspace
    working_dir: /workspace
    ports:
      - "${NOUSE_WEB_PORT:-8765}:8765"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    command:
      [
        "python",
        "-c",
        "from nouse.web.server import start_server; start_server(host='0.0.0.0', port=8765)",
      ]
"""


def _dockerfile_template() -> str:
    return """FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \\
 && apt-get install -y --no-install-recommends git ca-certificates \\
 && rm -rf /var/lib/apt/lists/*

ARG NOUSE_INSTALL_REF=main
RUN pip install --no-cache-dir "git+https://github.com/base76-research-lab/Nous.git@${NOUSE_INSTALL_REF}"

WORKDIR /workspace
EXPOSE 8765
"""


def _project_readme_template(project_name: str, slug: str) -> str:
    return f"""# {project_name}

Nous project brain: `{slug}`

## Start (local profile)

```bash
nouse daemon web
```

## Start (docker profile)

```bash
docker compose up --build -d
```

## Open chat

```bash
nouse chat
```

## Notes

- This project is isolated via `NOUSE_HOME=.nouse` and `NOUSE_WRITE_SCOPE=.`
- Use `nouse research --query "..." --annotate` to feed findings.
"""


def _normalize_project_profile(profile: str) -> str:
    raw = str(profile or "standard").strip().lower()
    if raw in {"research", "r", "thesis", "study", "lab"}:
        return "research"
    return "standard"


def _scaffold_profile_layout(project_dir: Path, *, profile: str, force: bool = False) -> list[str]:
    normalized = _normalize_project_profile(profile)
    created: list[str] = []
    if normalized != "research":
        return created

    for rel in (
        "sources",
        "notes",
        "drafts",
        "findings",
        "claims",
        "exports",
        "data/raw",
        "data/processed",
    ):
        path = project_dir / rel
        path.mkdir(parents=True, exist_ok=True)
        created.append(str(path))

    _write_text_if_missing(
        project_dir / "sources" / "seed_urls.txt",
        "# Lägg en URL per rad\n"
        "# https://example.com/article\n",
        force=force,
    )
    _write_text_if_missing(
        project_dir / "notes" / "00_project_context.md",
        "# Projektkontext\n\n"
        "Skriv syfte, avgränsning, mål och antaganden här.\n",
        force=force,
    )
    _write_text_if_missing(
        project_dir / "claims" / "claims.md",
        "# Claims\n\n"
        "| claim_id | claim | status | evidence |\n"
        "|---|---|---|---|\n",
        force=force,
    )
    _write_text_if_missing(
        project_dir / "findings" / "findings.md",
        "# Findings\n\n"
        "| finding_id | finding | source | confidence |\n"
        "|---|---|---|---|\n",
        force=force,
    )
    _write_text_if_missing(
        project_dir / "drafts" / "thesis_outline.md",
        "# Thesis Outline\n\n"
        "1. Problem\n"
        "2. Method\n"
        "3. Findings\n"
        "4. Discussion\n"
        "5. Conclusion\n",
        force=force,
    )
    return created


def _project_process_env(env_map: dict[str, str], env_file: Path) -> dict[str, str]:
    merged = dict(os.environ)
    for key, value in env_map.items():
        merged[str(key)] = str(value)
    existing = str(merged.get("NOUSE_ENV_FILES") or "").strip()
    extra = str(env_file)
    if existing and extra not in {x.strip() for x in existing.split(",") if x.strip()}:
        merged["NOUSE_ENV_FILES"] = f"{existing},{extra}"
    elif not existing:
        merged["NOUSE_ENV_FILES"] = extra
    return merged


def _short_error_detail(text: str, limit: int = 260) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if len(raw) <= max(60, int(limit)):
        return raw
    return raw[: max(60, int(limit))].rstrip() + "..."


def _validate_web_port(value: int) -> int:
    try:
        port = int(value)
    except Exception as exc:  # pragma: no cover - typer sköter normalt typning
        raise typer.BadParameter("Port måste vara ett heltal.") from exc
    if port < 1024 or port > 65535:
        raise typer.BadParameter(
            "Ogiltig port. Använd 1024-65535. Rekommenderat: 8765 eller 8876."
        )
    return port


def _run_project_docker_up(project_dir: Path) -> tuple[bool, str]:
    try:
        run = subprocess.run(
            ["docker", "compose", "up", "--build", "-d"],
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False, "docker/compose hittades inte i PATH."
    except Exception as exc:
        return False, str(exc)

    if run.returncode == 0:
        return True, ""
    detail = _short_error_detail(run.stderr or run.stdout or "")
    if not detail:
        detail = f"docker compose exit={run.returncode}"
    return False, detail


def _start_project_daemon_web(
    project_dir: Path,
    *,
    web_port: int,
    env: dict[str, str],
) -> tuple[bool, str]:
    import shutil
    import sys

    commands: list[list[str]] = []
    nouse_bin = shutil.which("nouse")
    if nouse_bin:
        commands.append([nouse_bin, "daemon", "web", "--port", str(int(web_port))])
    commands.append([sys.executable, "-m", "nouse.cli.main", "daemon", "web", "--port", str(int(web_port))])

    last_err = ""
    for cmd in commands:
        try:
            subprocess.Popen(
                cmd,
                cwd=str(project_dir),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            return True, ""
        except Exception as exc:
            last_err = str(exc)
    return False, last_err or "kunde inte starta lokal daemon"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _ingestd_manifest_path() -> Path:
    return _repo_root() / "tools" / "nouse-ingestd" / "Cargo.toml"


def _ingestd_binary_path(*, release: bool) -> Path:
    profile = "release" if release else "debug"
    return _repo_root() / "tools" / "nouse-ingestd" / "target" / profile / "nouse-ingestd"


def _ingestd_commands(*, host: str, port: int, release: bool) -> list[list[str]]:
    import shutil

    commands: list[list[str]] = []
    manifest = _ingestd_manifest_path()
    if not manifest.exists():
        return commands

    binary_path = _ingestd_binary_path(release=release)
    if binary_path.exists():
        commands.append([str(binary_path), "--host", host, "--port", str(int(port))])

    cargo_bin = shutil.which("cargo")
    if cargo_bin:
        cargo_cmd = [cargo_bin, "run", "--manifest-path", str(manifest)]
        if release:
            cargo_cmd.append("--release")
        cargo_cmd.extend(["--", "--host", host, "--port", str(int(port))])
        commands.append(cargo_cmd)

    return commands


def _start_ingestd_background(*, host: str, port: int, release: bool, env: dict[str, str]) -> tuple[bool, str]:
    commands = _ingestd_commands(host=host, port=port, release=release)
    if not commands:
        return False, f"manifest saknas: {_ingestd_manifest_path()}"

    last_err = ""
    for cmd in commands:
        try:
            subprocess.Popen(
                cmd,
                cwd=str(_repo_root()),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            return True, ""
        except Exception as exc:
            last_err = str(exc)
    return False, last_err or "kunde inte starta ingestd"


def _run_ingestd_foreground(*, host: str, port: int, release: bool, env: dict[str, str]) -> int:
    commands = _ingestd_commands(host=host, port=port, release=release)
    if not commands:
        return 1

    for cmd in commands:
        try:
            return int(subprocess.call(cmd, cwd=str(_repo_root()), env=env))
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return 1


def _run_project_chat(project_dir: Path, *, env: dict[str, str]) -> int:
    import shutil
    import sys

    commands: list[list[str]] = []
    nouse_bin = shutil.which("nouse")
    if nouse_bin:
        commands.append([nouse_bin, "chat"])
    commands.append([sys.executable, "-m", "nouse.cli.main", "chat"])

    for cmd in commands:
        try:
            return int(subprocess.call(cmd, cwd=str(project_dir), env=env))
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return 1


def _maybe_open_in_editor(editor: str, project_dir: Path) -> bool:
    choice = str(editor or "").strip().lower()
    if not choice:
        return False

    import shutil

    candidates: list[list[str]] = []
    if choice in {"code", "vscode"}:
        if shutil.which("code"):
            candidates.append(["code", str(project_dir)])
    elif choice in {"cursor"}:
        if shutil.which("cursor"):
            candidates.append(["cursor", str(project_dir)])
    elif choice in {"idea", "jetbrains"}:
        if shutil.which("idea"):
            candidates.append(["idea", str(project_dir)])
        if choice == "jetbrains":
            for cmd in ("pycharm", "webstorm", "goland"):
                if shutil.which(cmd):
                    candidates.append([cmd, str(project_dir)])
                    break
    elif choice in {"pycharm"}:
        if shutil.which("pycharm"):
            candidates.append(["pycharm", str(project_dir)])
    elif choice in {"terminal"}:
        return False

    for cmd in candidates:
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            continue
    return False


@app.command(name="init")
@app.command(name="initiate")
def init_cmd(
    mode: str = typer.Option("project", "--mode", help="project | personal"),
    scope: str = typer.Option(
        ".",
        "--scope",
        help="Projektrot för mode=project (default: aktuell katalog).",
    ),
    env_file: str = typer.Option(
        ".env",
        "--env-file",
        help="Dotenv-fil att skriva runtime-profil till.",
    ),
    watch_project_only: bool = typer.Option(
        True,
        "--watch-project-only/--keep-watch-defaults",
        help="I project-läge: begränsa daemon-watch till projektkatalogen.",
    ),
) -> None:
    from nouse.config.env import load_env_files
    from nouse.self_layer import ensure_living_core

    selected_mode = str(mode or "project").strip().lower()
    target = Path(env_file).expanduser()
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()

    if selected_mode not in {"project", "personal"}:
        console.print("[red]Ogiltigt mode.[/red] Använd: project | personal")
        raise typer.Exit(1)

    if selected_mode == "project":
        scope_root = Path(scope).expanduser()
        if not scope_root.exists():
            console.print(f"[red]Scope-path finns inte:[/red] {scope_root}")
            raise typer.Exit(1)
        if not scope_root.is_dir():
            console.print(f"[red]Scope-path måste vara katalog:[/red] {scope_root}")
            raise typer.Exit(1)
        env_map = _project_runtime_env(scope_root, watch_project_only=watch_project_only)
    else:
        env_map = _personal_runtime_env()

    try:
        for key, value in env_map.items():
            _upsert_env_key(target, key, value)
            os.environ[key] = value
        _ensure_runtime_dirs_from_env(env_map)
        load_env_files(force=True)
        if selected_mode == "personal":
            ensure_living_core()
    except Exception as exc:
        console.print(f"[red]Init misslyckades:[/red] {exc}")
        raise typer.Exit(1)

    console.print(f"[green]Nous init klar.[/green] mode={selected_mode} env={target}")
    for key in (
        "NOUSE_HOME",
        "NOUSE_FIELD_DB",
        "NOUSE_LIVING_CORE_PATH",
        "NOUSE_MEMORY_DIR",
        "NOUSE_DAEMON_BASE",
        "NOUSE_WATCH_PATHS",
        "NOUSE_WRITE_SCOPE",
    ):
        value = str(env_map.get(key) or "").strip()
        if value:
            console.print(f"[dim]{key}={value}[/dim]")
    console.print(
        "[dim]Tips: starta om daemon med `nouse daemon web` i denna katalog för att använda profilen.[/dim]"
    )
    if selected_mode == "personal":
        console.print(
            "[dim]Personal-läge: lokal profil, eget living core och operatorstöd är nu bootstrapat.[/dim]"
        )


@app.command(name="new")
def new_cmd(
    name: str = typer.Argument(..., help="Projektnamn, t.ex. 'epistemologi'."),
    root: str = typer.Option(".", "--root", help="Bas-katalog där projektet skapas."),
    profile: str = typer.Option(
        "standard",
        "--profile",
        "-p",
        help="Scaffold-profil: standard | research",
    ),
    research: bool = typer.Option(
        False,
        "--research",
        "-r",
        help="Shortcut för --profile research",
    ),
    docker: bool = typer.Option(
        True,
        "--docker/--no-docker",
        help="Skapa docker compose + Dockerfile för isolerad brain-runner.",
    ),
    force: bool = typer.Option(False, "--force", help="Tillåt att skriva i befintlig katalog."),
    editor: str = typer.Option(
        "",
        "--editor",
        help="Öppna projektet direkt: code | cursor | idea | pycharm | terminal",
    ),
    watch_project_only: bool = typer.Option(
        True,
        "--watch-project-only/--keep-watch-defaults",
        help="Begränsa watch till denna projektmapp.",
    ),
    ollama_host: str = typer.Option(
        "http://host.docker.internal:11434",
        "--ollama-host",
        help="Ollama endpoint för docker-profilen.",
    ),
    web_port: int = typer.Option(
        8765,
        "--web-port",
        help="Exponerad web-port i docker compose.",
        callback=_validate_web_port,
    ),
    up: bool = typer.Option(
        False,
        "--up/--no-up",
        help="Starta projekt-brain direkt efter scaffold.",
    ),
    chat: bool = typer.Option(
        False,
        "--chat/--no-chat",
        help="Öppna nouse chat direkt i projektets profil.",
    ),
) -> None:
    from nouse.config.env import load_env_files

    project_name = str(name or "").strip()
    if not project_name:
        console.print("[red]Ange ett projektnamn.[/red]")
        raise typer.Exit(1)
    resolved_profile = _normalize_project_profile("research" if research else profile)

    slug = _slugify_project_name(project_name)
    base_dir = Path(root).expanduser().resolve()
    if not base_dir.exists():
        console.print(f"[red]Root-path finns inte:[/red] {base_dir}")
        raise typer.Exit(1)
    if not base_dir.is_dir():
        console.print(f"[red]Root-path måste vara katalog:[/red] {base_dir}")
        raise typer.Exit(1)

    project_dir = base_dir / slug
    if project_dir.exists() and not force:
        console.print(
            f"[red]Projektmappen finns redan:[/red] {project_dir}\n"
            "[dim]Kör med --force om du vill uppdatera scaffolden.[/dim]"
        )
        raise typer.Exit(1)

    project_dir.mkdir(parents=True, exist_ok=True)
    env_path = project_dir / ".env"
    env_map = _project_runtime_env(project_dir, watch_project_only=watch_project_only)
    env_map["NOUSE_DAEMON_BASE"] = f"http://127.0.0.1:{int(web_port)}"

    try:
        for key, value in env_map.items():
            _upsert_env_key(env_path, key, value)
        _upsert_env_key(env_path, "PROJECT_SLUG", slug)
        _upsert_env_key(env_path, "NOUSE_WEB_PORT", str(int(web_port)))
        _upsert_env_key(env_path, "NOUSE_OLLAMA_HOST", str(ollama_host).strip())
        _ensure_runtime_dirs_from_env(env_map)
        load_env_files(force=True)
    except Exception as exc:
        console.print(f"[red]Kunde inte initiera projektprofil:[/red] {exc}")
        raise typer.Exit(1)
    process_env = _project_process_env(env_map, env_path)

    _write_text_if_missing(
        project_dir / ".gitignore",
        ".nouse/\n__pycache__/\n.pytest_cache/\n",
        force=force,
    )
    _write_text_if_missing(
        project_dir / "README.md",
        _project_readme_template(project_name=project_name, slug=slug),
        force=force,
    )
    created: list[str] = [str(env_path), str(project_dir / "README.md")]
    created.extend(_scaffold_profile_layout(project_dir, profile=resolved_profile, force=force))
    if docker:
        compose_path = project_dir / "docker-compose.yml"
        dockerfile_path = project_dir / "Dockerfile.nouse"
        _write_text_if_missing(compose_path, _compose_template(), force=force)
        _write_text_if_missing(dockerfile_path, _dockerfile_template(), force=force)
        created.extend([str(compose_path), str(dockerfile_path)])

    opened = _maybe_open_in_editor(editor, project_dir)

    if chat and docker and not up:
        up = True
        console.print("[dim]--chat valdes, aktiverar --up automatiskt för docker-profil.[/dim]")

    if up:
        if docker:
            console.print("[dim]Startar docker compose (build + detached)...[/dim]")
            ok, detail = _run_project_docker_up(project_dir)
            if not ok:
                console.print("[red]Kunde inte starta docker-profilen.[/red]")
                if detail:
                    console.print(f"[dim]{detail}[/dim]")
                console.print(
                    f"[dim]Tips: prova annan port, t.ex. `nouse new \"{project_name}\" --web-port 8876 --up --force`.[/dim]"
                )
                raise typer.Exit(1)
            console.print("[green]Docker-profil startad.[/green]")
        else:
            console.print("[dim]Startar lokal daemon web i bakgrunden...[/dim]")
            ok, detail = _start_project_daemon_web(
                project_dir,
                web_port=int(web_port),
                env=process_env,
            )
            if not ok:
                console.print("[red]Kunde inte starta lokal daemon.[/red]")
                if detail:
                    console.print(f"[dim]{detail}[/dim]")
                raise typer.Exit(1)
            console.print("[green]Lokal daemon-start initierad.[/green]")

    console.print(
        Panel(
            "[bold cyan]Nous New Brain[/bold cyan]\n"
            f"[green]Project:[/green] {project_dir}\n"
            f"[green]Mode:[/green] project (isolated)\n"
            f"[green]Profile:[/green] {resolved_profile}\n"
            f"[green]Docker scaffold:[/green] {'yes' if docker else 'no'}\n"
            f"[green]Opened in editor:[/green] {'yes' if opened else 'no'}\n"
            "[dim]Start local: `cd {0} && nouse daemon web`[/dim]\n"
            "[dim]Start docker: `cd {0} && docker compose up --build -d`[/dim]".format(project_dir),
            border_style="cyan",
        )
    )
    for item in created:
        console.print(f"[dim]created: {item}[/dim]")

    if chat:
        console.print("[dim]Öppnar chat i projektprofil...[/dim]")
        rc = _run_project_chat(project_dir, env=process_env)
        if rc != 0:
            raise typer.Exit(rc)


@app.command(name="make")
def make_cmd(
    name: str = typer.Argument(..., help="Projektnamn, t.ex. 'epistemologi'."),
    root: str = typer.Option(".", "--root", help="Bas-katalog där projektet skapas."),
    research: bool = typer.Option(
        True,
        "--research/--standard",
        "-r/-s",
        help="Preset: research (default) eller standard.",
    ),
    docker: bool = typer.Option(
        True,
        "--docker/--no-docker",
        help="Skapa docker compose + Dockerfile.",
    ),
    force: bool = typer.Option(False, "--force", help="Tillåt att skriva i befintlig katalog."),
    editor: str = typer.Option(
        "",
        "--editor",
        help="Öppna projektet direkt: code | cursor | idea | pycharm | terminal",
    ),
    watch_project_only: bool = typer.Option(
        True,
        "--watch-project-only/--keep-watch-defaults",
        help="Begränsa watch till denna projektmapp.",
    ),
    ollama_host: str = typer.Option(
        "http://host.docker.internal:11434",
        "--ollama-host",
        help="Ollama endpoint för docker-profilen.",
    ),
    web_port: int = typer.Option(
        8765,
        "--web-port",
        help="Exponerad web-port i docker compose.",
        callback=_validate_web_port,
    ),
    up: bool = typer.Option(
        False,
        "--up/--no-up",
        help="Starta projekt-brain direkt efter scaffold.",
    ),
    chat: bool = typer.Option(
        False,
        "--chat/--no-chat",
        help="Öppna nouse chat direkt i projektets profil.",
    ),
) -> None:
    """
    Enkel wrapper runt `nouse new` med research-preset som default.

    Exempel:
      nouse make epistemologi --up
      nouse make "recklinghausen-research" --web-port 8876 --up --chat
      nouse make demo --standard
    """
    new_cmd(
        name=name,
        root=root,
        profile="research" if research else "standard",
        research=False,
        docker=docker,
        force=force,
        editor=editor,
        watch_project_only=watch_project_only,
        ollama_host=ollama_host,
        web_port=web_port,
        up=up,
        chat=chat,
    )


def _simple_key_plan_for_provider(provider: str) -> dict[str, Any]:
    p = str(provider or "").strip().lower()
    if p in {"anthropic", "claude"}:
        return {
            "keys": ["ANTHROPIC_API_KEY"],
            "openai_base_url": "",
            "note": (
                "Anthropic-nyckel sparad. Nous-chatten kör idag via openai_compatible-transport, "
                "så anthropic kräver separat bridge för direkt användning i chat."
            ),
        }
    if p in {"groq"}:
        return {
            "keys": ["GROQ_API_KEY", "NOUSE_OPENAI_API_KEY", "OPENAI_API_KEY"],
            "openai_base_url": "https://api.groq.com/openai/v1",
            "note": "Groq bridge aktiverad via openai_compatible.",
        }
    if p in {"openrouter"}:
        return {
            "keys": ["OPENROUTER_API_KEY", "NOUSE_OPENAI_API_KEY", "OPENAI_API_KEY"],
            "openai_base_url": "https://openrouter.ai/api/v1",
            "note": "OpenRouter bridge aktiverad via openai_compatible.",
        }
    if p in {"copilot", "github", "github-copilot"}:
        return {
            "keys": ["GITHUB_TOKEN", "NOUSE_OPENAI_API_KEY", "OPENAI_API_KEY"],
            "openai_base_url": "https://models.inference.ai.azure.com",
            "note": "GitHub Copilot/Models bridge aktiverad via openai_compatible.",
        }
    # Default och codex/openai-kompatibla providers.
    return {
        "keys": ["NOUSE_OPENAI_API_KEY", "OPENAI_API_KEY"],
        "openai_base_url": "https://api.openai.com/v1",
        "note": "",
    }


def _normalize_model_choice_for_runtime(provider: str, model: str) -> tuple[str, str, str]:
    """
    Returnerar (provider, model, note). Kan automatiskt falla tillbaka till ollama
    för lokala modeltags om OpenAI-kompatibel nyckel saknas.
    """
    requested_provider = str(provider or "").strip() or "ollama"
    requested_provider_low = requested_provider.lower()
    clean_model = str(model or "").strip()
    if not clean_model:
        raise ValueError("model required")

    canonical = _canonical_runtime_provider(requested_provider)
    if canonical == "ollama":
        return ("ollama", clean_model, "")

    if _has_openai_compatible_api_key():
        return (canonical, clean_model, "")

    # Ingen API-nyckel: lokal tag kan köras via ollama istället.
    if ":" in clean_model and "/" not in clean_model:
        return (
            "ollama",
            clean_model,
            "Ingen API-nyckel för openai_compatible hittades. "
            f"Byter till ollama för lokal modell '{clean_model}'.",
        )

    if requested_provider_low == "codex":
        raise RuntimeError(
            "Codex CLI är installerat, men denna Nous-build använder ännu "
            "openai_compatible-backend i chatten (inte native codex-cli bridge). "
            "Sätt NOUSE_OPENAI_API_KEY/OPENAI_API_KEY eller välj en ollama-modell "
            "(t.ex. 1, 2 eller 8)."
        )

    raise RuntimeError(
        "Saknar API-nyckel för openai_compatible. "
        "Sätt NOUSE_OPENAI_API_KEY/OPENAI_API_KEY eller välj en ollama-modell "
        "(t.ex. 1, 2 eller 8)."
    )


def _apply_main_chat_model_policy(*, provider: str, model: str) -> list[dict[str, Any]]:
    from nouse.llm.policy import set_workload_candidates

    clean_provider = str(provider or "").strip() or "ollama"
    clean_model = str(model or "").strip()
    if not clean_model:
        raise ValueError("model required")

    if "/" in clean_model:
        prefix, remainder = clean_model.split("/", 1)
        pref = prefix.strip()
        rem = remainder.strip()
        if pref and rem:
            if not clean_provider:
                clean_provider = pref
            clean_model = rem

    return [
        set_workload_candidates(workload="chat", candidates=[clean_model], provider=clean_provider),
        set_workload_candidates(workload="agent", candidates=[clean_model], provider=clean_provider),
    ]


def _is_likely_chat_model(model: str) -> bool:
    text = str(model or "").strip().lower()
    if not text:
        return False
    non_chat_markers = (
        "embed",
        "embedding",
        "whisper",
        "transcribe",
        "rerank",
    )
    return not any(marker in text for marker in non_chat_markers)


def _collect_main_chat_model_menu(*, max_total: int = 24, max_per_provider: int = 8) -> dict[str, Any]:
    import shutil
    import httpx
    import nouse.client as client
    from nouse.llm.policy import get_workload_policy

    row = get_workload_policy("agent")
    current_provider = str(row.get("provider") or "ollama")
    current_candidates = [str(x).strip() for x in (row.get("candidates") or []) if str(x).strip()]

    options: list[dict[str, str]] = []
    seen: set[str] = set()
    warning = ""

    def _add_option(provider: str, model: str, label: str, source: str) -> None:
        if len(options) >= max_total:
            return
        clean_provider = str(provider or "").strip() or "ollama"
        clean_model = str(model or "").strip()
        if not clean_model:
            return
        key = f"{clean_provider}::{clean_model}"
        if key in seen:
            return
        seen.add(key)
        options.append(
            {
                "provider": clean_provider,
                "model": clean_model,
                "label": str(label or clean_provider),
                "source": str(source or "unknown"),
            }
        )

    mismatch_count = 0
    for model in current_candidates[:3]:
        opt_provider = current_provider
        if (
            current_provider not in {"", "ollama"}
            and ":" in model
            and "/" not in model
        ):
            opt_provider = "ollama"
            mismatch_count += 1
        _add_option(opt_provider, model, "policy", "policy")

    # Always include a compact set of robust presets so users can switch quickly,
    # even when provider autodiscovery is partial.
    _add_option("ollama", "glm-5.1:cloud", "preset", "preset")
    _add_option("ollama", "gemma4:e2b", "preset", "preset")
    _add_option("ollama", "qwen3.5:latest", "preset", "preset")
    _add_option("openai_compatible", "gpt-5-codex", "preset", "preset")
    _add_option("openai_compatible", "gpt-4.1-mini", "preset", "preset")
    _add_option("anthropic", "claude-sonnet-4", "preset", "preset")

    # If CLI binaries are installed, expose matching quick presets.
    if shutil.which("codex"):
        _add_option("codex", "gpt-5-codex", "codex-cli", "cli_preset")
    if shutil.which("claude"):
        _add_option("anthropic", "claude-sonnet-4", "claude-cli", "cli_preset")
    if shutil.which("gh"):
        _add_option("copilot", "gpt-4o", "gh-copilot", "cli_preset")

    if client.daemon_running():
        try:
            resp = httpx.get(f"{client.DAEMON_BASE}/api/models/catalog", timeout=12.0)
            if resp.status_code == 200:
                payload = resp.json() if hasattr(resp, "json") else {}
                providers = payload.get("providers") if isinstance(payload, dict) else []
                if isinstance(providers, list):
                    for provider_row in providers:
                        if not isinstance(provider_row, dict):
                            continue
                        kind = str(provider_row.get("kind") or "ollama").strip() or "ollama"
                        label = str(provider_row.get("label") or kind).strip() or kind
                        defaults = provider_row.get("default_models")
                        available = provider_row.get("available_models")

                        merged: list[str] = []
                        local_seen: set[str] = set()
                        if isinstance(defaults, dict):
                            for raw in defaults.values():
                                text = str(raw or "").strip()
                                if text and text not in local_seen:
                                    local_seen.add(text)
                                    merged.append(text)
                        if isinstance(available, list):
                            for raw in available:
                                text = str(raw or "").strip()
                                if text and text not in local_seen:
                                    local_seen.add(text)
                                    merged.append(text)

                        filtered = [m for m in merged if _is_likely_chat_model(m)]
                        selected = filtered or merged
                        for model in selected[: max(1, int(max_per_provider))]:
                            _add_option(kind, model, label, "catalog")
            else:
                warning = f"catalog HTTP {resp.status_code}"
        except Exception as exc:
            warning = str(exc)

    if mismatch_count and not warning:
        warning = (
            "policy/provider mismatch: lokal modelltag med icke-ollama provider "
            "(fallback till ollama aktiv)."
        )

    return {
        "current_provider": current_provider,
        "current_candidates": current_candidates,
        "options": options,
        "warning": warning,
    }


def _has_local_tag_provider_mismatch(provider: str, candidates: list[str]) -> bool:
    p = str(provider or "").strip()
    if p in {"", "ollama"}:
        return False
    return any((":" in str(c or "") and "/" not in str(c or "")) for c in candidates)


def _render_main_chat_model_menu(menu: dict[str, Any]) -> None:
    provider = str(menu.get("current_provider") or "ollama")
    candidates = [str(x).strip() for x in (menu.get("current_candidates") or []) if str(x).strip()]
    preview = ", ".join(candidates[:3]) if candidates else "(ingen)"
    mismatch_note = ""
    if _has_local_tag_provider_mismatch(provider, candidates):
        mismatch_note = "\n[dim yellow]Mismatch upptäckt: lokal modelltag med icke-ollama provider.[/dim yellow]"

    console.print(
        Panel(
            "[bold cyan]Main Chat Model[/bold cyan]\n"
            f"[dim]Nu: {provider} · {preview}[/dim]\n"
            "[dim]/model <nr|model> byter main chat-modell (uppdaterar chat+agent).[/dim]\n"
            "[dim]/models visar listan igen. Enter i chatten börjar direkt.[/dim]\n"
            "[dim]Snabbval: skriv bara ett nummer direkt (innan första frågan).[/dim]"
            f"{mismatch_note}",
            border_style="blue",
        )
    )

    options = menu.get("options") if isinstance(menu.get("options"), list) else []
    if not options:
        warning = str(menu.get("warning") or "").strip()
        if warning:
            console.print(f"[yellow]Model-lista saknas just nu:[/yellow] {warning}")
        return

    current_set = set(candidates)
    missing_key = not _has_openai_compatible_api_key()
    for idx, row in enumerate(options, start=1):
        if not isinstance(row, dict):
            continue
        p = str(row.get("provider") or "").strip() or "ollama"
        m = str(row.get("model") or "").strip()
        if not m:
            continue
        marker = "*" if (p == provider and m in current_set) else " "
        label = str(row.get("label") or p).strip() or p
        note = ""
        if missing_key and _canonical_runtime_provider(p) != "ollama":
            if p.lower() == "codex":
                note = " [yellow](codex-cli login återanvänds inte här ännu)[/yellow]"
            else:
                note = " [yellow](kräver API-nyckel)[/yellow]"
        console.print(f"[dim]{idx:>2}.[/dim] {marker} {p} · {m} [dim]({label})[/dim]{note}")

    warning = str(menu.get("warning") or "").strip()
    if warning:
        console.print(f"[yellow]Model-catalog begränsad:[/yellow] {warning}")


def _resolve_main_model_choice(
    choice: str,
    *,
    menu: dict[str, Any],
    explicit_provider: str = "",
) -> tuple[str, str]:
    raw = str(choice or "").strip()
    if not raw:
        raise ValueError("Ange modellnummer eller modelref.")

    options = menu.get("options") if isinstance(menu.get("options"), list) else []
    if raw.isdigit():
        idx = int(raw)
        if idx < 1 or idx > len(options):
            raise ValueError(f"Ogiltigt model-index: {idx}")
        row = options[idx - 1] if isinstance(options[idx - 1], dict) else {}
        provider = str(row.get("provider") or "").strip() or "ollama"
        model = str(row.get("model") or "").strip()
        if not model:
            raise ValueError("Valt model-index saknar modelref.")
        return provider, model

    lowered = raw.lower()
    for row in options:
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "").strip() or "ollama"
        model = str(row.get("model") or "").strip()
        if not model:
            continue
        if lowered == model.lower() or lowered == f"{provider.lower()}/{model.lower()}":
            return provider, model

    if "/" in raw:
        prefix, remainder = raw.split("/", 1)
        provider = str(prefix or "").strip()
        model = str(remainder or "").strip()
        if provider and model:
            return provider, model

    provider = _infer_provider_for_model_input(raw, explicit_provider=explicit_provider)
    return provider, raw


def _pick_ollama_fallback_from_menu(menu: dict[str, Any]) -> str:
    options = menu.get("options") if isinstance(menu.get("options"), list) else []
    for row in options:
        if not isinstance(row, dict):
            continue
        provider = _canonical_runtime_provider(str(row.get("provider") or ""))
        model = str(row.get("model") or "").strip()
        if provider == "ollama" and model:
            return model
    return ""


def _auto_heal_main_chat_policy_if_needed(menu: dict[str, Any]) -> str:
    from nouse.llm.policy import get_workload_policy

    row = get_workload_policy("agent")
    provider = str(row.get("provider") or "ollama").strip() or "ollama"
    candidates = [str(x).strip() for x in (row.get("candidates") or []) if str(x).strip()]

    if _canonical_runtime_provider(provider) == "ollama":
        return ""
    if _has_openai_compatible_api_key():
        return ""

    fallback_model = ""
    for candidate in candidates:
        if ":" in candidate and "/" not in candidate:
            fallback_model = candidate
            break
    if not fallback_model:
        fallback_model = _pick_ollama_fallback_from_menu(menu)
    if not fallback_model:
        return (
            "Main chat-policy kräver API-nyckel men ingen ollama-fallback hittades. "
            "Välj lokal modell med /model 2 eller /model minimax-m2.7:cloud."
        )

    _apply_main_chat_model_policy(provider="ollama", model=fallback_model)
    return (
        "Main chat-policy krävde API-nyckel som saknas. "
        f"Bytte automatiskt till ollama · {fallback_model}."
    )


def _runtime_health_hint_line(*, workload: str = "agent") -> str:
    import nouse.client as client

    if not client.daemon_running():
        return "[dim]Runtime: offline (daemon ej igång).[/dim]"
    try:
        import httpx

        resp = httpx.get(
            f"{client.DAEMON_BASE}/api/models/health",
            params={"workload": workload},
            timeout=4.0,
        )
        if resp.status_code != 200:
            if resp.status_code == 404:
                try:
                    legacy = httpx.get(f"{client.DAEMON_BASE}/api/status", timeout=3.0)
                    if legacy.status_code == 200:
                        return "[yellow]Runtime: Working[/yellow] [dim](legacy daemon utan models/health).[/dim]"
                except Exception:
                    pass
            return f"[dim]Runtime: okänd (HTTP {resp.status_code}).[/dim]"
        payload = resp.json() if hasattr(resp, "json") else {}
        status = str(payload.get("status") or "").strip().lower()
        label = str(payload.get("label") or status or "unknown").strip()
        detail = str(payload.get("detail") or "").strip()
        color = {
            "working": "green",
            "degraded": "yellow",
            "not_working": "red",
        }.get(status, "dim")
        suffix = f" [dim]{detail}[/dim]" if detail else ""
        return f"[{color}]Runtime: {label}[/{color}]{suffix}"
    except Exception:
        return "[dim]Runtime: okänd.[/dim]"


def _start_daemon_background(*, wait_sec: float = 8.0) -> tuple[bool, str]:
    import shutil
    import sys
    import time

    import nouse.client as client

    if client.daemon_running():
        return True, "already_running"

    commands: list[list[str]] = []
    nouse_bin = shutil.which("nouse")
    if nouse_bin:
        commands.append([nouse_bin, "daemon"])
    commands.append([sys.executable, "-m", "nouse.cli.main", "daemon"])

    deadline_wait = max(1.0, float(wait_sec))
    for cmd in commands:
        try:
            subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except Exception:
            continue
        deadline = time.time() + deadline_wait
        while time.time() < deadline:
            if client.daemon_running():
                return True, "started"
            time.sleep(0.25)
    return False, "start_failed_or_timeout"


_CHAT_COMMANDS: list[dict[str, Any]] = [
    {
        "group": "Hjälp",
        "usage": "/, /help, /commands",
        "desc": "Visa kommandopalett.",
        "keys": ["/", "/help", "/commands", "/?", "/h"],
    },
    {
        "group": "Modeller",
        "usage": "/models",
        "desc": "Visa lista med tillgängliga main chat-modeller.",
        "keys": ["/models"],
    },
    {
        "group": "Modeller",
        "usage": "/model <nr|model>",
        "desc": "Byt main chat-modell.",
        "keys": ["/model"],
    },
    {
        "group": "Orkestrering",
        "usage": "/check",
        "desc": "Visa queue/HITL-status.",
        "keys": ["/check", "/review"],
    },
    {
        "group": "Orkestrering",
        "usage": "/orchestrate <jobb>",
        "desc": "Skicka jobb till bakgrundsagenter.",
        "keys": ["/orchestrate"],
    },
    {
        "group": "Superpowers",
        "usage": "/skills | /tools",
        "desc": "Visa tillgängliga MCP/skill-verktyg och superpower-lägen.",
        "keys": ["/skills", "/powers", "/tools"],
    },
    {
        "group": "Superpowers",
        "usage": "/skill [namn|off]",
        "desc": "Pinna eller rensa en Nous-skill för kommande chat-frågor.",
        "keys": ["/skill"],
    },
    {
        "group": "Superpowers",
        "usage": "/mcp <jobb|on|off>",
        "desc": "Kör en fråga i explicit MCP/tool-mode eller slå på/av tool-mode för sessionen.",
        "keys": ["/mcp"],
    },
    {
        "group": "Superpowers",
        "usage": "/tri <jobb>",
        "desc": "Kör explicit triangulering (LLM + graf + extern).",
        "keys": ["/tri", "/triangulate"],
    },
    {
        "group": "Superpowers",
        "usage": "/selfdevelop <plan>",
        "desc": "Begär self-develop/self-update workflow (guarded).",
        "keys": ["/selfdevelop"],
    },
    {
        "group": "HITL",
        "usage": "/approve <id> [note]",
        "desc": "Godkänn en HITL-interrupt.",
        "keys": ["/approve"],
    },
    {
        "group": "HITL",
        "usage": "/approve-all [note]",
        "desc": "Godkänn alla pending HITL och kör queue.",
        "keys": ["/approve-all"],
    },
    {
        "group": "HITL",
        "usage": "/reject <id> [note]",
        "desc": "Avvisa en HITL-interrupt.",
        "keys": ["/reject"],
    },
    {
        "group": "System",
        "usage": "/daemon",
        "desc": "Starta daemon vid behov / kontrollera online.",
        "keys": ["/daemon", "/start-daemon"],
    },
    {
        "group": "Session",
        "usage": "quit | exit | q",
        "desc": "Avsluta chatten.",
        "keys": ["quit", "exit", "q"],
    },
    {
        "group": "Session",
        "usage": '""" ... """',
        "desc": "Multiline-input. Starta/sluta med trippelcitat på egen rad.",
        "keys": ['"""'],
    },
]


def _filter_chat_commands(query: str = "") -> list[dict[str, Any]]:
    text = str(query or "").strip().lower().lstrip("/")
    if not text:
        return list(_CHAT_COMMANDS)
    out: list[dict[str, Any]] = []
    for row in _CHAT_COMMANDS:
        usage = str(row.get("usage") or "").lower()
        desc = str(row.get("desc") or "").lower()
        keys = [str(k).lower().lstrip("/") for k in (row.get("keys") or [])]
        if text in usage or text in desc or any(text in k for k in keys):
            out.append(row)
    return out


def _render_chat_command_palette(query: str = "") -> None:
    rows = _filter_chat_commands(query)
    if not rows:
        console.print(
            f"[yellow]Inga kommandon matchar:[/yellow] {query}\n"
            "[dim]Skriv / för hela listan.[/dim]"
        )
        return

    lines: list[str] = [
        "[bold cyan]Command Palette[/bold cyan]",
        "[dim]Tips: skriv // om du vill skicka text som börjar med '/'.[/dim]",
        "",
    ]
    shown_groups: set[str] = set()
    for row in rows:
        group = str(row.get("group") or "Övrigt")
        if group not in shown_groups:
            shown_groups.add(group)
            lines.append(f"[bold]{group}[/bold]")
        usage = str(row.get("usage") or "").strip()
        desc = str(row.get("desc") or "").strip()
        lines.append(f"[cyan]{usage}[/cyan]  [dim]{desc}[/dim]")
    if query:
        lines.append("")
        lines.append(f"[dim]Filter:[/dim] {query}")
    console.print(Panel("\n".join(lines), border_style="blue"))


def _render_superpower_skills_panel() -> None:
    from nouse.capability import build_capability_graph
    from nouse.cli.chat import get_live_tools
    from nouse.mcp_gateway.gateway import is_mcp_tool
    from nouse.plugins.loader import is_plugin_tool

    snapshot = build_capability_graph(probe_models=False)
    planes = snapshot.get("planes") if isinstance(snapshot, dict) else {}
    skill_plane = (planes.get("skill_plane") or {}) if isinstance(planes, dict) else {}
    skill_names = [
        str((row or {}).get("name") or "").strip()
        for row in (skill_plane.get("skills") or [])
        if str((row or {}).get("name") or "").strip()
    ]

    tools = get_live_tools()
    names = sorted(
        {
            str(((t or {}).get("function") or {}).get("name") or "").strip()
            for t in tools
        }
    )
    names = [n for n in names if n]
    mcp_names = [n for n in names if is_mcp_tool(n)]
    plugin_names = [n for n in names if is_plugin_tool(n)]
    core_names = [n for n in names if n not in set(mcp_names) | set(plugin_names)]
    kernel_names = [n for n in mcp_names if n.startswith("kernel_")]

    def _preview(rows: list[str], limit: int = 8) -> str:
        if not rows:
            return "-"
        head = rows[:limit]
        tail = " ..." if len(rows) > limit else ""
        return ", ".join(head) + tail

    lines = [
        "[bold cyan]Skill & MCP Superpowers[/bold cyan]",
        f"[dim]skills={len(skill_names)} · tools total={len(names)} · core={len(core_names)} · mcp={len(mcp_names)} · plugin={len(plugin_names)}[/dim]",
        "",
        f"[bold]Nous skills[/bold] [dim]({len(skill_names)})[/dim]",
        f"[dim]{_preview(skill_names, limit=10)}[/dim]",
        "",
        f"[bold]MCP[/bold] [dim]({len(mcp_names)})[/dim]",
        f"[dim]{_preview(mcp_names)}[/dim]",
        "",
        f"[bold]Kernel/Guarded[/bold] [dim]({len(kernel_names)})[/dim]",
        f"[dim]{_preview(kernel_names)}[/dim]",
        "",
        "[bold]Snabbkommandon[/bold]",
        "[cyan]/skill <namn>[/cyan]  [dim]pinna en skill för nästa frågor[/dim]",
        "[cyan]/skill <namn> <jobb>[/cyan]  [dim]engångskörning med explicit skill[/dim]",
        "[cyan]/skill off[/cyan]  [dim]rensa pinad skill[/dim]",
        "[cyan]/mcp on[/cyan]  [dim]håll tool-mode aktivt tills du stänger av[/dim]",
        "[cyan]/mcp <jobb>[/cyan]  [dim]explicit tool-mode on-demand[/dim]",
        "[cyan]/tri <jobb>[/cyan]  [dim]explicit triangulering[/dim]",
        "[cyan]/selfdevelop <plan>[/cyan]  [dim]self-update workflow (kan vara guarded)[/dim]",
    ]
    console.print(Panel("\n".join(lines), border_style="magenta"))


def _render_chat_control_modes(*, pinned_skill: str = "", force_mcp_mode: bool = False) -> None:
    status_skill = str(pinned_skill or "").strip() or "-"
    status_mcp = "on" if force_mcp_mode else "off"
    lines = [
        "[bold cyan]Chat Control[/bold cyan]",
        f"[dim]Pinned skill: {status_skill} · MCP mode: {status_mcp}[/dim]",
        "",
        "[bold]Usage[/bold]",
        "[cyan]/skill[/cyan]  [dim]visa skills och kontrolläge[/dim]",
        "[cyan]/skill <namn>[/cyan]  [dim]pinna en skill för kommande frågor[/dim]",
        "[cyan]/skill <namn> <jobb>[/cyan]  [dim]engångskörning med explicit skill[/dim]",
        "[cyan]/skill off[/cyan]  [dim]rensa pinad skill[/dim]",
        "[cyan]/mcp on[/cyan]  [dim]pinna tool-mode för kommande frågor[/dim]",
        "[cyan]/mcp off[/cyan]  [dim]stäng av pinnat tool-mode[/dim]",
    ]
    console.print(Panel("\n".join(lines), border_style="cyan"))


def _resolve_chat_skill_name(raw_value: str) -> str:
    from nouse.capability import resolve_skill_name

    return str(resolve_skill_name(raw_value)).strip()


def _read_chat_input_with_multiline() -> str:
    raw = input("\ndu> ")
    if raw.strip() != '"""':
        return raw.strip()

    lines: list[str] = []
    while True:
        line = input("... ")
        if line.strip() == '"""':
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _chat_via_api(
    *,
    session_id: str = "main",
    model: str = "",
    provider: str = "",
    list_models: bool = False,
    show_events: bool = False,
) -> None:
    import nouse.client as client

    daemon_boot_attempted = False

    def _ensure_daemon_online() -> bool:
        nonlocal daemon_boot_attempted
        if client.daemon_running():
            return True
        if not daemon_boot_attempted:
            daemon_boot_attempted = True
            ok, detail = _start_daemon_background(wait_sec=8.0)
            if ok:
                console.print("[green]Daemon startad i bakgrunden.[/green]")
                return True
            console.print(
                "[yellow]Daemon var inte igång och auto-start misslyckades.[/yellow] "
                "Kör `nouse daemon` eller `nouse daemon web`."
            )
            if detail:
                console.print(f"[dim]auto-start detail: {detail}[/dim]")
            return False
        console.print("[yellow]Daemon ej igång. Starta med `nouse daemon` eller `nouse daemon web`.[/yellow]")
        return False

    if str(model or "").strip():
        try:
            chosen_provider, chosen_model = _resolve_main_model_choice(
                str(model),
                menu={"options": [], "current_provider": "", "current_candidates": []},
                explicit_provider=str(provider or ""),
            )
            run_provider, run_model, note = _normalize_model_choice_for_runtime(
                chosen_provider,
                chosen_model,
            )
            _apply_main_chat_model_policy(provider=run_provider, model=run_model)
            console.print(f"[green]Main chat-modell satt:[/green] {run_provider} · {run_model}")
            if note:
                console.print(f"[yellow]{note}[/yellow]")
        except Exception as exc:
            console.print(f"[red]Kunde inte sätta main chat-modell:[/red] {exc}")

    menu = _collect_main_chat_model_menu()
    healed_msg = _auto_heal_main_chat_policy_if_needed(menu)
    if healed_msg:
        console.print(f"[yellow]{healed_msg}[/yellow]")
        menu = _collect_main_chat_model_menu()
    quick_model_pick_enabled = bool(list_models)
    if bool(list_models):
        _render_main_chat_model_menu(menu)

    policy_hint = ""
    try:
        from nouse.llm.policy import get_workload_policy

        row = get_workload_policy("agent")
        provider = str(row.get("provider") or "ollama")
        candidates = [str(x).strip() for x in (row.get("candidates") or []) if str(x).strip()]
        preview = ", ".join(candidates[:3]) if candidates else "(inga candidates)"
        has_local_tag_mismatch = (
            provider not in {"", "ollama"}
            and any((":" in c and "/" not in c) for c in candidates)
        )
        fallback_note = (
            "\n[yellow]Obs: lokal modelltag med icke-ollama provider. "
            "Nous använder automatisk ollama-fallback.[/yellow]"
            if has_local_tag_mismatch
            else ""
        )
        policy_hint = (
            f"\n[dim]Agent policy: {provider} · {preview}[/dim]"
            "\n[dim]Mode: terminal-chat med Nous RoW (read/write) via agent-loopen.[/dim]"
            f"\n{_runtime_health_hint_line(workload='agent')}"
            f"{fallback_note}"
        )
    except Exception:
        policy_hint = ""

    console.print(
        Panel(
            "[bold cyan]Nous Chat[/bold cyan]\n"
            "[dim]Skriv 'quit' eller 'exit' för att avsluta.[/dim]"
            "\n[dim]Skriv / för command palette (kommandon, listor och funktioner).[/dim]"
            '\n[dim]Multiline: skriv """ på egen rad för att starta/avsluta block.[/dim]'
            f"{policy_hint}",
            border_style="cyan",
        )
    )
    pinned_skill = ""
    force_mcp_mode = False

    while True:
        try:
            raw = _read_chat_input_with_multiline()
        except (EOFError, KeyboardInterrupt):
            console.print("Hejdå")
            return

        if not raw:
            continue
        raw_lower = raw.lower()
        if raw in {"/", "/?", "/h"} or raw_lower in {"/help", "/commands"}:
            _render_chat_command_palette()
            continue
        if raw_lower.startswith("/help ") or raw_lower.startswith("/commands "):
            _, _, query = raw.partition(" ")
            _render_chat_command_palette(query)
            continue
        if raw.startswith("//"):
            raw = raw[1:]
            raw_lower = raw.lower()
        if raw.isdigit():
            options = menu.get("options") if isinstance(menu.get("options"), list) else []
            idx = int(raw)
            if 1 <= idx <= len(options):
                try:
                    chosen_provider, chosen_model = _resolve_main_model_choice(
                        raw,
                        menu=menu,
                        explicit_provider=str(provider or ""),
                    )
                    run_provider, run_model, note = _normalize_model_choice_for_runtime(
                        chosen_provider,
                        chosen_model,
                    )
                    _apply_main_chat_model_policy(provider=run_provider, model=run_model)
                    console.print(
                        f"[green]Main chat-modell uppdaterad:[/green] "
                        f"{run_provider} · {run_model}"
                    )
                    if note:
                        console.print(f"[yellow]{note}[/yellow]")
                    menu = _collect_main_chat_model_menu()
                    _render_main_chat_model_menu(menu)
                    quick_model_pick_enabled = False
                except Exception as exc:
                    console.print(f"[red]Modelbyte misslyckades:[/red] {exc}")
                continue
            if quick_model_pick_enabled:
                console.print(
                    "[yellow]Ogiltigt modellnummer. "
                    "Använd /models för att visa aktuell lista.[/yellow]"
                )
                continue
        if raw_lower in {"/models", "/model"}:
            menu = _collect_main_chat_model_menu()
            _render_main_chat_model_menu(menu)
            quick_model_pick_enabled = True
            continue
        if raw_lower in {"/daemon", "/start-daemon"}:
            if _ensure_daemon_online():
                console.print("[green]Daemon online.[/green]")
            continue
        if raw_lower in {"/skills", "/powers", "/tools"}:
            _render_superpower_skills_panel()
            _render_chat_control_modes(
                pinned_skill=pinned_skill,
                force_mcp_mode=force_mcp_mode,
            )
            continue
        if raw_lower == "/skill":
            _render_superpower_skills_panel()
            _render_chat_control_modes(
                pinned_skill=pinned_skill,
                force_mcp_mode=force_mcp_mode,
            )
            continue
        if raw_lower.startswith("/skill "):
            argline = raw.split(" ", 1)[1].strip()
            arg_lower = argline.lower()
            if arg_lower in {"off", "clear", "none", "reset"}:
                pinned_skill = ""
                console.print("[green]Pinned skill avstängd.[/green]")
                continue
            if arg_lower in {"list", "show"}:
                _render_superpower_skills_panel()
                _render_chat_control_modes(
                    pinned_skill=pinned_skill,
                    force_mcp_mode=force_mcp_mode,
                )
                continue
            token, _, prompt = argline.partition(" ")
            resolved_skill = _resolve_chat_skill_name(token)
            if not resolved_skill:
                console.print(f"[yellow]Okänd skill:[/yellow] {token}")
                _render_superpower_skills_panel()
                _render_chat_control_modes(
                    pinned_skill=pinned_skill,
                    force_mcp_mode=force_mcp_mode,
                )
                continue
            if not prompt.strip():
                pinned_skill = resolved_skill
                console.print(f"[green]Pinned skill:[/green] {resolved_skill}")
                continue
            raw = f"/skill {resolved_skill} {prompt.strip()}"
            raw_lower = raw.lower()
        if raw_lower in {"/check", "/review"}:
            if not _ensure_daemon_online():
                continue
            try:
                queue = client.get_queue_status(limit=6, status="all")
                hitl = client.get_hitl_interrupts(status="pending", limit=6)
                qstats = queue.get("stats") if isinstance(queue.get("stats"), dict) else {}
                hstats = hitl.get("stats") if isinstance(hitl.get("stats"), dict) else {}
                console.print(
                    Panel(
                        "[bold]Orchestrator Check[/bold]\n"
                        f"queue: pending={qstats.get('pending', '?')} "
                        f"awaiting_approval={qstats.get('awaiting_approval', '?')} "
                        f"failed={qstats.get('failed', '?')}\n"
                        f"hitl: pending={hstats.get('pending', '?')} total={hstats.get('total', '?')}",
                        border_style="magenta",
                    )
                )
                interrupts = hitl.get("interrupts") if isinstance(hitl.get("interrupts"), list) else []
                if interrupts:
                    console.print("[dim]Pending approvals:[/dim]")
                    for row in interrupts[:6]:
                        if not isinstance(row, dict):
                            continue
                        iid = row.get("id")
                        category = str(row.get("category") or "interrupt")
                        reason = str(row.get("reason") or "").strip()
                        task = row.get("task") if isinstance(row.get("task"), dict) else {}
                        query = str(task.get("query") or "").strip()
                        preview = query[:110] + ("..." if len(query) > 110 else "")
                        console.print(
                            f"[dim]-[/dim] #{iid} {category} · {reason[:90]}"
                            + (f"\n  [dim]{preview}[/dim]" if preview else "")
                        )
                else:
                    console.print("[dim]Inga pending approvals just nu.[/dim]")
            except Exception as exc:
                console.print(f"[red]Check-fel:[/red] {exc}")
            continue
        if raw_lower.startswith("/approve-all"):
            note = raw[len("/approve-all") :].strip()
            if not _ensure_daemon_online():
                continue
            try:
                payload = client.get_hitl_interrupts(status="pending", limit=5000)
                interrupts = payload.get("interrupts") if isinstance(payload.get("interrupts"), list) else []
                ids: list[int] = []
                for row in interrupts:
                    if not isinstance(row, dict):
                        continue
                    try:
                        iid = int(row.get("id", 0) or 0)
                    except Exception:
                        iid = 0
                    if iid > 0:
                        ids.append(iid)
                unique_ids = sorted(set(ids))
                if not unique_ids:
                    console.print("[dim]Inga pending approvals att godkänna.[/dim]")
                    continue

                approved = 0
                failed = 0
                bulk_note = note or "bulk approve via /approve-all"
                for iid in unique_ids:
                    try:
                        out = client.post_hitl_approve(
                            interrupt_id=iid,
                            reviewer="cli_chat_bulk",
                            note=bulk_note,
                        )
                        if bool(out.get("ok")):
                            approved += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1

                console.print(
                    f"[green]Approve-all:[/green] approved={approved} failed={failed} total={len(unique_ids)}"
                )
                if approved > 0:
                    retry_err = ""
                    run_err = ""
                    try:
                        retried = client.post_queue_retry_failed(
                            limit=max(5, approved),
                            reason="retry after /approve-all",
                        )
                        rows = retried.get("retried") if isinstance(retried, dict) else []
                        retry_count = len(rows) if isinstance(rows, list) else 0
                        console.print(f"[dim]queue retry_failed: retried={retry_count}[/dim]")
                    except Exception as exc:
                        retry_err = str(exc)
                    try:
                        run = client.post_queue_run(
                            count=min(25, max(1, approved)),
                            source="cli_chat_approve_all",
                            wait=False,
                        )
                        status = str(run.get("status") or "ok") if isinstance(run, dict) else "ok"
                        job_id = str(run.get("job_id") or "").strip() if isinstance(run, dict) else ""
                        if job_id:
                            console.print(f"[dim]queue run: status={status} job_id={job_id}[/dim]")
                        else:
                            console.print(f"[dim]queue run: status={status}[/dim]")
                    except Exception as exc:
                        run_err = str(exc)
                    if retry_err:
                        console.print(f"[yellow]retry_failed misslyckades:[/yellow] {retry_err}")
                    if run_err:
                        console.print(f"[yellow]queue run misslyckades:[/yellow] {run_err}")
            except Exception as exc:
                console.print(f"[red]Approve-all-fel:[/red] {exc}")
            continue
        if raw_lower.startswith("/approve "):
            parts = raw.split(" ", 2)
            if len(parts) < 2 or not parts[1].strip().isdigit():
                console.print("[yellow]Använd: /approve <interrupt_id> [note][/yellow]")
                continue
            if not _ensure_daemon_online():
                continue
            iid = int(parts[1].strip())
            note = parts[2].strip() if len(parts) > 2 else ""
            try:
                payload = client.post_hitl_approve(
                    interrupt_id=iid,
                    reviewer="cli_chat",
                    note=note,
                )
                if bool(payload.get("ok")):
                    console.print(f"[green]Approved interrupt #{iid}.[/green]")
                else:
                    console.print(f"[red]Approve misslyckades:[/red] {payload.get('error')}")
            except Exception as exc:
                console.print(f"[red]Approve-fel:[/red] {exc}")
            continue
        if raw_lower.startswith("/reject "):
            parts = raw.split(" ", 2)
            if len(parts) < 2 or not parts[1].strip().isdigit():
                console.print("[yellow]Använd: /reject <interrupt_id> [note][/yellow]")
                continue
            if not _ensure_daemon_online():
                continue
            iid = int(parts[1].strip())
            note = parts[2].strip() if len(parts) > 2 else ""
            try:
                payload = client.post_hitl_reject(
                    interrupt_id=iid,
                    reviewer="cli_chat",
                    note=note,
                )
                if bool(payload.get("ok")):
                    console.print(f"[green]Rejected interrupt #{iid}.[/green]")
                else:
                    console.print(f"[red]Reject misslyckades:[/red] {payload.get('error')}")
            except Exception as exc:
                console.print(f"[red]Reject-fel:[/red] {exc}")
            continue
        if raw_lower.startswith("/orchestrate "):
            task = raw.split(" ", 1)[1].strip()
            if not task:
                console.print("[yellow]Använd: /orchestrate <jobbtext>[/yellow]")
                continue
            if not _ensure_daemon_online():
                continue
            try:
                wake = client.post_system_wake(
                    text=task,
                    session_id=session_id,
                    source="cli_chat_orchestrator",
                    mode="now",
                    reason="delegated_chat_task",
                    context_key="chat_orchestrator",
                )
                console.print(
                    "[green]Orchestrator:[/green] jobb skickat till bakgrundsagenter. "
                    "Kör /check för review."
                )
                if isinstance(wake, dict):
                    stats = wake.get("stats") if isinstance(wake.get("stats"), dict) else {}
                    pending = stats.get("pending_total")
                    if pending is not None:
                        console.print(f"[dim]system_events.pending_total={pending}[/dim]")
            except Exception as exc:
                console.print(f"[red]Orchestrate-fel:[/red] {exc}")
            continue
        if raw_lower.startswith("/model "):
            choice = raw.split(" ", 1)[1].strip()
            try:
                chosen_provider, chosen_model = _resolve_main_model_choice(
                    choice,
                    menu=menu,
                    explicit_provider=str(provider or ""),
                )
                run_provider, run_model, note = _normalize_model_choice_for_runtime(
                    chosen_provider,
                    chosen_model,
                )
                _apply_main_chat_model_policy(provider=run_provider, model=run_model)
                console.print(
                    f"[green]Main chat-modell uppdaterad:[/green] "
                    f"{run_provider} · {run_model}"
                )
                if note:
                    console.print(f"[yellow]{note}[/yellow]")
                menu = _collect_main_chat_model_menu()
                _render_main_chat_model_menu(menu)
                quick_model_pick_enabled = False
            except Exception as exc:
                console.print(f"[red]Modelbyte misslyckades:[/red] {exc}")
            continue
        if raw_lower.startswith("/tri ") or raw_lower.startswith("/triangulate "):
            prompt = raw.split(" ", 1)[1].strip()
            if not prompt:
                console.print("[yellow]Använd: /tri <jobbtext>[/yellow]")
                continue
            raw = f"/tri {prompt}"
            raw_lower = raw.lower()
        elif raw_lower in {"/tri", "/triangulate"}:
            console.print("[yellow]Använd: /tri <jobbtext>[/yellow]")
            continue
        if raw_lower.startswith("/mcp "):
            prompt = raw.split(" ", 1)[1].strip()
            if prompt.lower() in {"on", "off", "clear", "reset"}:
                force_mcp_mode = prompt.lower() == "on"
                console.print(
                    f"[green]MCP mode:[/green] {'på' if force_mcp_mode else 'av'}"
                )
                continue
            if not prompt:
                console.print("[yellow]Använd: /mcp <jobbtext>[/yellow]")
                continue
            raw = f"/mcp {prompt}"
            raw_lower = raw.lower()
        elif raw_lower == "/mcp":
            console.print(
                "[yellow]Använd: /mcp <jobbtext> eller /mcp on|off[/yellow]"
            )
            console.print(
                f"[dim]MCP mode är nu {'på' if force_mcp_mode else 'av'}.[/dim]"
            )
            continue
        if raw_lower.startswith("/selfdevelop "):
            prompt = raw.split(" ", 1)[1].strip()
            if not prompt:
                console.print("[yellow]Använd: /selfdevelop <plan>[/yellow]")
                continue
            raw = f"/selfdevelop {prompt}"
            raw_lower = raw.lower()
        elif raw_lower == "/selfdevelop":
            console.print("[yellow]Använd: /selfdevelop <plan>[/yellow]")
            continue
        if raw_lower in {"quit", "exit", "q"}:
            console.print("Hejdå")
            return
        passthrough_prefixes = ("/tri ", "/mcp ", "/selfdevelop ", "/skill ")
        if raw.startswith("/") and (not any(raw_lower.startswith(p) for p in passthrough_prefixes)):
            token = raw.split(" ", 1)[0]
            console.print(f"[yellow]Okänt slash-kommando:[/yellow] {token}")
            _render_chat_command_palette(token.lstrip("/"))
            continue

        if not _ensure_daemon_online():
            continue

        quick_model_pick_enabled = False
        outbound_raw = raw
        if not outbound_raw.startswith("/"):
            if pinned_skill:
                outbound_raw = f"/skill {pinned_skill} {outbound_raw}"
            elif force_mcp_mode:
                outbound_raw = f"/mcp {outbound_raw}"
        response = ""
        seen_trace: str | None = None
        seen_model: str | None = None
        graph_write_ops = 0
        try:
            for item in client.stream_chat(outbound_raw, session_id=session_id):
                t = str(item.get("type", ""))
                if not seen_trace and item.get("trace_id"):
                    seen_trace = str(item.get("trace_id"))
                if not seen_model and item.get("model"):
                    seen_model = str(item.get("model"))
                if t == "status":
                    msg = str(item.get("msg") or "").strip()
                    if msg and show_events:
                        console.print(f"[dim]{msg}[/dim]")
                if t == "tool":
                    name = str(item.get("name") or "").strip()
                    if name and show_events:
                        console.print(f"[cyan]tool[/cyan] {name}")
                if t == "tool_result":
                    name = str(item.get("name") or "").strip()
                    result = item.get("result")
                    if name in {"upsert_concept", "add_relation"}:
                        graph_write_ops += 1
                        if show_events:
                            console.print(f"[green]graph update[/green] via {name}")
                    elif name and show_events:
                        console.print(f"[dim]tool ok: {name}[/dim]")
                if t == "tool_error":
                    name = str(item.get("name") or "").strip()
                    err = str(item.get("error") or "").strip()
                    console.print(f"[red]tool error[/red] {name}: {err}")
                if t == "done":
                    response = str(item.get("msg") or "").strip()
                    if item.get("model"):
                        seen_model = str(item.get("model"))
                if t == "error":
                    console.print(f"[red]Fel:[/red] {item.get('msg')}")
        except Exception as exc:
            console.print(f"[red]Chat-fel:[/red] {exc}")
            continue

        if response:
            console.print(Markdown(f"**nouse>** {response}"))
        else:
            console.print("[yellow]Inget svar returnerades.[/yellow]")
        if seen_trace:
            console.print(f"[dim]trace_id: {seen_trace}[/dim]")
        if seen_model:
            console.print(f"[dim]model: {seen_model}[/dim]")
        if show_events and graph_write_ops:
            console.print(f"[green]Nous writes this turn:[/green] {graph_write_ops}")


@app.command(name="daemon")
def daemon_cmd(
    action: str = typer.Argument("start", help="start | web | status"),
    port: int = typer.Option(8765, "--port", "-p", help="Webb-port (med action=web)"),
) -> None:
    import nouse.client as client
    from nouse.config.env import load_env_files

    # Läs lokal .env (projektprofil) innan daemon-moduler importeras.
    load_env_files(force=True)
    from nouse.daemon.main import run

    act = str(action or "start").strip().lower()
    if act not in {"start", "web", "status"}:
        console.print("[red]Ogiltig action.[/red] Använd: start | web | status")
        raise typer.Exit(1)

    if act == "status":
        if not client.daemon_running():
            console.print("[yellow]Daemon ej igång[/yellow]")
            return
        try:
            status = client.get_status()
            console.print(
                "[green]Daemon online[/green] "
                f"concepts={status.get('concepts', '?')} "
                f"relations={status.get('relations', '?')} "
                f"cycle={status.get('cycle', '?')}"
            )
        except Exception:
            console.print("[green]Daemon online[/green]")
        return

    if client.daemon_running():
        console.print("[yellow]Daemon verkar redan vara igång.[/yellow]")
        if act == "web":
            console.print(f"[bold cyan]http://127.0.0.1:{port}[/bold cyan]")
        return

    try:
        if act == "web":
            console.print(f"[green]Startar daemon + web UI på port {port}...[/green]")
            console.print(f"[bold cyan]http://127.0.0.1:{port}[/bold cyan]")
            run(with_web=True, web_port=port)
            return

        console.print("[green]Startar daemon (headless)...[/green]")
        run(with_web=False, web_port=port)
    except RuntimeError as exc:
        msg = str(exc)
        if "Could not set lock on file" in msg:
            console.print(
                "[red]Kunde inte starta daemon: databasen är låst av en annan process.[/red]"
            )
            raise typer.Exit(1)
        raise


@app.command(name="ingestd")
def ingestd_cmd(
    action: str = typer.Argument("status", help="start | run | status"),
    port: int = typer.Option(8766, "--port", "-p", help="Port for Rust ingest daemon."),
    host: str = typer.Option("127.0.0.1", "--host", help="Listen host for Rust ingest daemon."),
    release: bool = typer.Option(True, "--release/--debug", help="Use release build when available."),
) -> None:
    from nouse.config.env import load_env_files
    import nouse.ingestd_client as ingestd_client

    load_env_files(force=True)

    act = str(action or "status").strip().lower()
    if act not in {"start", "run", "status"}:
        console.print("[red]Ogiltig action.[/red] Använd: start | run | status")
        raise typer.Exit(1)

    connect_host = "127.0.0.1" if str(host).strip() == "0.0.0.0" else str(host).strip()
    health_url = f"http://{connect_host}:{int(port)}"

    if act == "status":
        if not ingestd_client.daemon_running(base=health_url):
            console.print("[yellow]ingestd ej igång[/yellow]")
            return
        try:
            payload = ingestd_client.get_health(base=health_url)
            console.print(
                "[green]ingestd online[/green] "
                f"service={payload.get('service', 'nouse-ingestd')} "
                f"version={payload.get('version', '?')}"
            )
        except Exception:
            console.print("[green]ingestd online[/green]")
        console.print(f"[dim]{health_url}[/dim]")
        return

    process_env = dict(os.environ)
    process_env.setdefault("NOUSE_INGESTD_BASE", health_url)

    if ingestd_client.daemon_running(base=health_url):
        console.print("[yellow]ingestd verkar redan vara igång.[/yellow]")
        console.print(f"[dim]{health_url}[/dim]")
        return

    if act == "run":
        console.print(f"[green]Startar ingestd i foreground på {health_url}...[/green]")
        rc = _run_ingestd_foreground(host=host, port=int(port), release=bool(release), env=process_env)
        raise typer.Exit(rc)

    ok, detail = _start_ingestd_background(
        host=host,
        port=int(port),
        release=bool(release),
        env=process_env,
    )
    if not ok:
        console.print("[red]Kunde inte starta ingestd.[/red]")
        if detail:
            console.print(f"[dim]{detail}[/dim]")
        raise typer.Exit(1)

    console.print(f"[green]ingestd-start initierad.[/green] {health_url}")
    console.print(f"[dim]Env: NOUSE_INGESTD_BASE={health_url}[/dim]")


@app.command(name="snapshot")
def snapshot_cmd(
    action: str = typer.Argument("list", help="list | create | restore"),
    snapshot: str = typer.Argument("", help="Snapshot-namn eller sökväg (vid restore)."),
    tag: str = typer.Option("manual", "--tag", help="Tag vid create."),
    limit: int = typer.Option(20, "--limit", help="Max antal snapshots vid list."),
    create_backup: bool = typer.Option(
        True,
        "--backup/--no-backup",
        help="Skapa pre-restore backup av live-db.",
    ),
) -> None:
    import nouse.client as client
    from nouse.field.surface import FieldSurface
    from nouse.metacognition.snapshot import create_snapshot, list_snapshots, restore_snapshot

    op = str(action or "list").strip().lower()
    if op not in {"list", "create", "restore"}:
        console.print("[red]Ogiltig action.[/red] Använd: list | create | restore")
        raise typer.Exit(1)

    if op == "list":
        try:
            if client.daemon_running():
                payload = client.get_snapshot_list(limit=max(1, int(limit)))
                rows = payload.get("snapshots") if isinstance(payload, dict) else []
            else:
                rows = list_snapshots(limit=max(1, int(limit)))
        except Exception as exc:
            console.print(f"[red]Snapshot-lista misslyckades:[/red] {exc}")
            raise typer.Exit(1)
        if not rows:
            console.print("[yellow]Inga snapshots hittades.[/yellow]")
            return
        lines = ["[bold cyan]Snapshots[/bold cyan]"]
        for row in rows[: max(1, int(limit))]:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            tag_value = str(row.get("tag") or "").strip()
            ts = str(row.get("timestamp") or row.get("mtime") or "").strip()
            size = int(row.get("size_bytes") or 0)
            lines.append(
                f"- [cyan]{name}[/cyan]"
                + (f" [dim](tag={tag_value})[/dim]" if tag_value else "")
                + (f" [dim]{ts}[/dim]" if ts else "")
                + f" [dim]{size} B[/dim]"
            )
        console.print(Panel("\n".join(lines), border_style="cyan"))
        return

    if op == "create":
        try:
            field = FieldSurface(read_only=False)
            snap_path = create_snapshot(field, tag=str(tag or "manual").strip() or "manual")
            console.print(f"[green]Snapshot skapad:[/green] {snap_path}")
        except Exception as exc:
            console.print(f"[red]Snapshot create misslyckades:[/red] {exc}")
            raise typer.Exit(1)
        return

    # restore
    ref = str(snapshot or "").strip()
    if not ref:
        console.print("[yellow]Använd: nouse snapshot restore <snapshot_namn_eller_path>[/yellow]")
        raise typer.Exit(1)
    try:
        if client.daemon_running():
            out = client.post_snapshot_restore(snapshot=ref, create_backup=bool(create_backup))
        else:
            out = restore_snapshot(ref, create_backup=bool(create_backup))
        if bool(out.get("ok", True)) or str(out.get("status") or "").lower() == "ok":
            console.print("[green]Restore OK.[/green]")
            if out.get("backup_path"):
                console.print(f"[dim]backup:[/dim] {out.get('backup_path')}")
            if out.get("restored_from"):
                console.print(f"[dim]from:[/dim] {out.get('restored_from')}")
            if out.get("live_sha256"):
                console.print(f"[dim]sha256:[/dim] {out.get('live_sha256')}")
            return
        console.print(f"[red]Restore misslyckades:[/red] {out.get('error')}")
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red]Restore-fel:[/red] {exc}")
        raise typer.Exit(1)


@app.command(name="chat")
def chat_cmd(
    session_id: str = typer.Option("main", "--session-id", "-s", help="Session-id"),
    model: str = typer.Option("", "--model", help="Sätt main chat-modell direkt."),
    provider: str = typer.Option("", "--provider", help="Provider för --model (valfritt)."),
    list_models: bool = typer.Option(
        True,
        "--list-models/--no-list-models",
        help="Visa tillgängliga main chat-modeller vid start.",
    ),
    show_events: bool = typer.Option(
        False,
        "--show-events/--quiet",
        help="Visa interna status/tool-events i chatten.",
    ),
) -> None:
    from nouse.config.env import load_env_files

    load_env_files(force=True)
    _chat_via_api(
        session_id=session_id,
        model=model,
        provider=provider,
        list_models=list_models,
        show_events=show_events,
    )


@app.command(name="api-key")
@app.command(name="simply-api-key")
@app.command(name="simply_api_key")
def simply_api_key_cmd(
    key: str = typer.Option(
        "",
        "--key",
        "-k",
        help="API-nyckel. Om tomt värde: säker prompt.",
    ),
    provider: str = typer.Option(
        "openai_compatible",
        "--provider",
        "-p",
        help="Provider: openai_compatible | anthropic | groq | openrouter | copilot",
    ),
    env_file: str = typer.Option(
        "~/.env",
        "--env-file",
        help="Var nyckeln sparas (dotenv-format).",
    ),
    apply_autodiscover: bool = typer.Option(
        True,
        "--apply-autodiscover/--no-apply-autodiscover",
        help="Om daemon kör: trigga model autodiscover efter uppdatering.",
    ),
) -> None:
    import httpx
    import nouse.client as client

    secret = str(key or "").strip()
    if not secret:
        secret = typer.prompt("Ange API-nyckel", hide_input=True).strip()
    if not secret:
        console.print("[red]Ingen nyckel angavs.[/red]")
        raise typer.Exit(1)

    target = Path(env_file).expanduser()
    plan = _simple_key_plan_for_provider(provider)
    env_keys = [str(x).strip() for x in (plan.get("keys") or []) if str(x).strip()]
    bridge_base_url = str(plan.get("openai_base_url") or "").strip()
    bridge_note = str(plan.get("note") or "").strip()
    try:
        for env_key in env_keys:
            _upsert_env_key(target, env_key, secret)
            os.environ[env_key] = secret
        if bridge_base_url:
            _upsert_env_key(target, "NOUSE_OPENAI_BASE_URL", bridge_base_url)
            os.environ["NOUSE_OPENAI_BASE_URL"] = bridge_base_url
    except Exception as exc:
        console.print(f"[red]Kunde inte spara nyckeln:[/red] {exc}")
        raise typer.Exit(1)

    console.print(
        f"[green]API-nyckel sparad.[/green] provider={provider} keys={', '.join(env_keys)} file={target}"
    )
    if bridge_base_url:
        console.print(f"[dim]OpenAI-kompatibel endpoint:[/dim] {bridge_base_url}")
    if bridge_note:
        console.print(f"[dim]{bridge_note}[/dim]")

    if client.daemon_running() and apply_autodiscover:
        try:
            resp = httpx.post(
                f"{client.DAEMON_BASE}/api/models/autodiscover",
                json={"apply": True},
                timeout=20.0,
            )
            if resp.status_code == 200:
                payload = resp.json() if hasattr(resp, "json") else {}
                chosen = payload.get("chosen") if isinstance(payload, dict) else None
                if isinstance(chosen, dict):
                    kind = str(chosen.get("kind") or "okänd")
                    label = str(chosen.get("label") or kind)
                    console.print(f"[green]Autodiscover uppdaterad:[/green] {label} ({kind})")
                else:
                    console.print("[dim]Autodiscover körd.[/dim]")
            else:
                console.print(f"[yellow]Autodiscover gav HTTP {resp.status_code}.[/yellow]")
        except Exception as exc:
            console.print(f"[yellow]Autodiscover misslyckades:[/yellow] {exc}")
    else:
        console.print(
            "[dim]Tips: starta om daemonen eller kör `nouse chat` igen för att läsa nyckeln från .env.[/dim]"
        )


@app.command(name="auth")
def auth_cmd(
    provider: str = typer.Option(
        "openai_compatible",
        "--provider",
        "-p",
        help="Provider: openai_compatible | codex | anthropic | copilot | groq | openrouter",
    ),
    key: str = typer.Option(
        "",
        "--key",
        "-k",
        help="API-nyckel (valfritt). Om satt sparas den direkt.",
    ),
    env_file: str = typer.Option(
        "~/.env",
        "--env-file",
        help="Var auth sparas (dotenv-format).",
    ),
    web: bool = typer.Option(
        True,
        "--web/--no-web",
        help="Öppna web-loginflödet (terminal -> web -> record auth).",
    ),
    open_browser: bool = typer.Option(
        True,
        "--open-browser/--no-open-browser",
        help="Öppna web-URL automatiskt i browser.",
    ),
    apply_autodiscover: bool = typer.Option(
        True,
        "--apply-autodiscover/--no-apply-autodiscover",
        help="Kör model autodiscover när nyckel sparas.",
    ),
) -> None:
    import httpx
    import nouse.client as client

    secret = str(key or "").strip()
    if secret:
        simply_api_key_cmd(
            key=secret,
            provider=provider,
            env_file=env_file,
            apply_autodiscover=apply_autodiscover,
        )
        return

    auth_url = f"{client.DAEMON_BASE}/#auth"

    if not web:
        if not client.daemon_running():
            console.print("[yellow]Daemon ej igång. Starta med `nouse daemon web`.[/yellow]")
            return
        try:
            resp = httpx.get(f"{client.DAEMON_BASE}/api/auth/status", timeout=10.0)
            if resp.status_code == 200:
                payload = resp.json() if hasattr(resp, "json") else {}
                rows = payload.get("providers") if isinstance(payload, dict) else []
                configured = 0
                total = 0
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        total += 1
                        if bool(row.get("configured")):
                            configured += 1
                console.print(
                    f"[green]Auth status:[/green] configured={configured}/{max(total, 1)} "
                    f"[dim]({client.DAEMON_BASE}/api/auth/status)[/dim]"
                )
                return
            console.print(f"[yellow]Auth status HTTP {resp.status_code}[/yellow]")
        except Exception as exc:
            console.print(f"[yellow]Auth status misslyckades:[/yellow] {exc}")
        return

    console.print(
        Panel(
            "[bold cyan]Nous Auth[/bold cyan]\n"
            "[dim]Flow: terminal → web-login → record auth[/dim]\n"
            f"[dim]URL:[/dim] {auth_url}\n"
            "[dim]I webben: välj provider, klistra in API-nyckel, klicka 'Record auth key'.[/dim]",
            border_style="blue",
        )
    )

    if not client.daemon_running():
        console.print(
            "[yellow]Daemon ej igång.[/yellow] Starta med `nouse daemon web` och öppna sedan URL:en ovan."
        )
        return

    if open_browser:
        try:
            subprocess.Popen(
                ["xdg-open", auth_url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            console.print("[dim]Öppnar web auth-panel i browser...[/dim]")
        except Exception:
            console.print("[yellow]Kunde inte öppna browser automatiskt. Öppna URL manuellt.[/yellow]")


@app.command(name="start")
def start_cmd(
    mode: str = typer.Argument("me", help="me | research | autonomy"),
    session_id: str = typer.Option("main", "--session-id", "-s", help="Session-id för chat"),
    web_port: int = typer.Option(8765, "--web-port", help="Port till web cockpit"),
    open_browser: bool = typer.Option(False, "--open-browser", help="Öppna webbläsare i research-läge"),
) -> None:
    import nouse.client as client

    choice = str(mode or "me").strip().lower()
    if choice not in {"me", "research", "autonomy"}:
        console.print("[red]Ogiltigt mode.[/red] Använd: me | research | autonomy")
        raise typer.Exit(1)

    if choice == "me":
        _chat_via_api(session_id=session_id, list_models=False)
        return

    if choice == "research":
        url = f"http://127.0.0.1:{web_port}"
        if not client.daemon_running():
            console.print("[yellow]Daemon ej igång. Starta först med `nouse daemon web`.[/yellow]")
            raise typer.Exit(1)
        console.print(f"[green]Research cockpit:[/green] {url}")
        if open_browser:
            try:
                subprocess.Popen(
                    ["xdg-open", url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
        return

    if not client.daemon_running():
        console.print("[yellow]Daemon ej igång. Starta först med `nouse daemon web`.[/yellow]")
        raise typer.Exit(1)

    status = client.get_status()
    events = client.get_system_events(limit=8)
    allow = client.brain_clawbot_allowlist(channel="ops")
    console.print(
        Panel(
            f"[bold]Autonomy Overview[/bold]\n"
            f"concepts={status.get('concepts', '?')} relations={status.get('relations', '?')} "
            f"cycle={status.get('cycle', '?')}\n"
            f"pending_system_events={events.get('stats', {}).get('pending_total', '?')}\n"
            f"clawbot_ops_allowed={len(allow.get('allowed') or [])} "
            f"pending_pairings={len(allow.get('pending') or [])}",
            border_style="magenta",
        )
    )


@app.command(name="governance")
def governance_cmd(
    action: str = typer.Argument("list", help="list | show | apply"),
    profile: str = typer.Argument("", help="Profilnamn: high_precision | conservative | exploratory | trusted_local"),
    env_file: str = typer.Option(
        "~/.env",
        "--env-file",
        help="Var profilens env-värden skrivs vid apply.",
    ),
) -> None:
    from nouse.config.governance_profiles import (
        list_governance_profiles,
        resolve_governance_profile,
    )

    op = str(action or "list").strip().lower()
    if op not in {"list", "show", "apply"}:
        console.print("[red]Ogiltig action.[/red] Använd: list | show | apply")
        raise typer.Exit(1)

    rows = list_governance_profiles()
    if op == "list":
        lines = ["[bold cyan]Governance Profiles[/bold cyan]"]
        for row in rows:
            lines.append(f"- [cyan]{row.name}[/cyan]: {row.description}")
        console.print(Panel("\n".join(lines), border_style="cyan"))
        return

    try:
        chosen = resolve_governance_profile(profile)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if op == "show":
        lines = [
            f"[bold cyan]Profile:[/bold cyan] {chosen.name}",
            chosen.description,
            "",
            "[bold]Env overrides[/bold]",
        ]
        for key, value in chosen.env.items():
            lines.append(f"- [cyan]{key}[/cyan]={value}")
        console.print(Panel("\n".join(lines), border_style="cyan"))
        return

    target = Path(env_file).expanduser()
    try:
        for key, value in chosen.env.items():
            _upsert_env_key(target, key, value)
            os.environ[str(key)] = str(value)
    except Exception as exc:
        console.print(f"[red]Kunde inte applicera governance-profil:[/red] {exc}")
        raise typer.Exit(1)

    console.print(
        f"[green]Governance-profil applicerad:[/green] {chosen.name} -> {target}"
    )
    console.print(
        "[dim]Tips: starta om daemon/chat för att läsa nya trösklar från .env.[/dim]"
    )


@app.command(name="visualize")
@app.command(name="viz")
def visualize_cmd(
    port: int = typer.Option(8765, "--port", "-p", help="Web-port för visualisering."),
    open_browser: bool = typer.Option(True, "--open-browser/--no-open-browser", help="Öppna webbläsare automatiskt."),
    auto_start: bool = typer.Option(True, "--auto-start/--no-auto-start", help="Starta daemon i bakgrunden om den inte körs."),
    wait_sec: float = typer.Option(8.0, "--wait-sec", help="Hur länge vi väntar på daemon-start."),
) -> None:
    import nouse.client as client

    url = f"http://127.0.0.1:{int(port)}"
    if not client.daemon_running():
        if not auto_start:
            console.print(
                "[red]Daemon ej igång.[/red] Starta med `nouse daemon web` eller kör `nouse visualize --auto-start`."
            )
            raise typer.Exit(1)
        console.print("[yellow]Daemon offline. Startar i bakgrunden...[/yellow]")
        ok, detail = _start_daemon_background(wait_sec=max(1.0, float(wait_sec)))
        if not ok:
            console.print(
                f"[red]Kunde inte starta daemon automatiskt ({detail}).[/red] "
                "Kör `nouse daemon web` manuellt."
            )
            raise typer.Exit(1)

    console.print(
        Panel(
            "[bold cyan]Nous Visualize[/bold cyan]\n"
            f"[green]URL:[/green] {url}\n"
            "[dim]Inkluderar graf, länkar, findings/claims och basis-data.[/dim]\n"
            "[dim]Tips: kör `nouse research --query \"...\" --annotate` för att fylla findings-panelen.[/dim]",
            border_style="cyan",
        )
    )

    if open_browser:
        try:
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            console.print("[dim]Öppnar visualisering i browser...[/dim]")
        except Exception:
            console.print("[yellow]Kunde inte öppna browser automatiskt. Öppna URL manuellt.[/yellow]")


@app.command(name="strap")
def strap_cmd(
    mission: str = typer.Option("", "--mission", "-m", help="Missiontext för kickstart"),
    focus_domains: str = typer.Option("", "--focus-domains", "-d", help="CSV med domäner"),
    session_id: str = typer.Option("main", "--session-id", "-s", help="Session-id"),
    repo_root: str = typer.Option("", "--repo-root", help="Repo-root för dokumentunderlag"),
    iic1_root: str = typer.Option("", "--iic1-root", help="IIC-root för dokumentunderlag"),
    max_tasks: int = typer.Option(8, "--max-tasks", help="Max antal seedade tasks"),
    max_docs: int = typer.Option(8, "--max-docs", help="Max antal dokument i kickstart"),
    provider: str = typer.Option("", "--provider", help="ollama | codex | openai_compatible"),
    model: str = typer.Option("", "--model", help="Primär modell, t.ex. codex/gpt-5-codex"),
    workloads: str = typer.Option(
        "chat,agent",
        "--workloads",
        help="CSV workloads att uppdatera när --model anges (nouse chat använder agent).",
    ),
    run_now: bool = typer.Option(
        True,
        "--run-now/--seed-only",
        help="Kör research queue direkt efter kickstart",
    ),
    run_count: int = typer.Option(1, "--run-count", help="Antal queue-tasker att köra"),
    wait: bool = typer.Option(False, "--wait", help="Vänta på queue-run svaret"),
) -> None:
    import nouse.client as client
    from nouse.llm.policy import set_workload_candidates

    if not client.daemon_running():
        console.print("[red]Daemon ej igång. Starta först med `nouse daemon web`.[/red]")
        raise typer.Exit(1)

    clean_model = str(model or "").strip()
    clean_provider = str(provider or "").strip()

    if clean_model:
        workload_rows = [
            str(x).strip().lower()
            for x in str(workloads or "").split(",")
            if str(x).strip()
        ]
        if not workload_rows:
            workload_rows = ["chat", "agent", "extract", "synthesize", "curiosity"]

        inferred_provider = clean_provider
        if not inferred_provider:
            if "/" in clean_model:
                inferred_provider = clean_model.split("/", 1)[0].strip() or "ollama"
            else:
                inferred_provider = "ollama"

        applied: list[dict[str, Any]] = []
        for workload in workload_rows:
            applied.append(
                set_workload_candidates(
                    workload=workload,
                    candidates=[clean_model],
                    provider=inferred_provider,
                )
            )
        console.print_json(data={"ok": True, "policy_updated": applied})
        if inferred_provider.lower() != "ollama":
            console.print(
                "[dim]Obs: icke-ollama kräver att daemonen har "
                "NOUSE_OPENAI_BASE_URL + NOUSE_OPENAI_API_KEY i miljön.[/dim]"
            )
    elif clean_provider:
        console.print("[yellow]--provider satt utan --model, policy uppdaterades inte.[/yellow]")

    payload = client.post_kickstart(
        session_id=session_id,
        mission=mission,
        focus_domains=focus_domains,
        repo_root=repo_root,
        iic1_root=iic1_root,
        max_tasks=max(1, int(max_tasks)),
        max_docs=max(1, int(max_docs)),
        source="cli_strap",
    )
    console.print_json(data=payload)

    if run_now:
        run_payload = client.post_queue_run(
            count=max(1, int(run_count)),
            source="cli_strap",
            wait=bool(wait),
        )
        console.print_json(data={"queue_run": run_payload})


@app.command(name="learn-from")
def learn_from_cmd(
    sources: list[str] = typer.Argument(
        [],
        help="URL, fil eller katalog (kan anges flera gånger).",
    ),
    include_home: bool = typer.Option(
        False,
        "--home",
        help="Lär från hemkatalogen.",
    ),
    include_iic: bool = typer.Option(
        False,
        "--iic",
        help="Lär från IIC-disken (autodetekteras).",
    ),
    iic_root: str = typer.Option(
        "",
        "--iic-root",
        help="Explicit sökväg till IIC-root.",
    ),
    max_files: int = typer.Option(
        300,
        "--max-files",
        help="Max antal lokala filer från kataloger.",
    ),
    min_chars: int = typer.Option(
        100,
        "--min-chars",
        help="Minsta textlängd för ingest.",
    ),
    extensions: str = typer.Option(
        ".md,.txt,.py,.pdf",
        "--extensions",
        help="Filändelser för katalogscan (csv).",
    ),
    debug_extract: bool = typer.Option(
        False,
        "--debug-extract",
        help="Visa extraktionsdiagnostik per källa.",
    ),
) -> None:
    import httpx
    import nouse.client as client
    import nouse.ingestd_client as ingestd_client
    from nouse.daemon.file_text import extract_text
    from nouse.daemon.sources import DEFAULT_INGEST_EXTENSIONS, iter_ingest_files
    from nouse.daemon.web_text import extract_text_from_url, is_url

    requested: list[str] = [str(x).strip() for x in (sources or []) if str(x).strip()]
    if include_home:
        requested.append(str(Path.home()))

    if str(iic_root or "").strip():
        requested.append(str(Path(iic_root).expanduser()))
    elif include_iic:
        found_roots = _discover_iic_roots()
        if not found_roots:
            console.print(
                "[yellow]Ingen IIC-disk hittades automatiskt. "
                "Ange --iic-root <path>.[/yellow]"
            )
        requested.extend(str(p) for p in found_roots)

    if not requested:
        console.print(
            "[red]Ange minst en källa.[/red] Exempel: "
            "`nouse learn-from <url|path>`, `--home`, `--iic`."
        )
        raise typer.Exit(1)

    seen_sources: set[str] = set()
    normalized: list[str] = []
    for raw in requested:
        key = str(raw)
        if not is_url(raw):
            key = str(Path(raw).expanduser())
        if key in seen_sources:
            continue
        seen_sources.add(key)
        normalized.append(raw)

    file_limit = max(1, min(int(max_files), 20000))
    min_chars_safe = max(1, int(min_chars))

    parsed_extensions = _parse_extension_csv(extensions)
    active_extensions = parsed_extensions or sorted(DEFAULT_INGEST_EXTENSIONS)

    urls: list[str] = []
    files: list[Path] = []
    missing: list[str] = []
    truncated = False

    for raw in normalized:
        if is_url(raw):
            urls.append(raw)
            continue

        p = Path(raw).expanduser()
        if not p.exists():
            missing.append(raw)
            continue
        if p.is_file():
            if len(files) >= file_limit:
                truncated = True
                break
            files.append(p)
            continue

        for f in iter_ingest_files(p, extensions=active_extensions):
            if len(files) >= file_limit:
                truncated = True
                break
            files.append(f)
        if truncated:
            break

    if not urls and not files:
        for row in missing[:8]:
            console.print(f"[yellow]Hittade inte:[/yellow] {row}")
        console.print("[red]Inga giltiga källor hittades.[/red]")
        raise typer.Exit(1)

    daemon_up = client.daemon_running()
    if daemon_up:
        console.print("[dim]learn-from: daemon online, använder /api/ingest.[/dim]")
    else:
        console.print(
            "[yellow]Daemon ej nåbar. Extraherad text köas i capture_queue för senare ingest.[/yellow]"
        )
    ingestd_up = bool(files) and ingestd_client.daemon_running()
    if ingestd_up:
        console.print("[dim]learn-from: ingestd online, använder Rust-extraktion för lokala filer.[/dim]")

    processed = 0
    skipped_short = 0
    queued = 0
    added_total = 0
    failed = 0
    queue_paths: list[str] = []

    def _handle_payload(*, text: str, source_value: str, display: str, reason_hint: str = "") -> None:
        nonlocal processed, skipped_short, queued, added_total, failed

        if len(str(text or "").strip()) < min_chars_safe:
            skipped_short += 1
            if debug_extract:
                console.print(
                    f"[dim]skip-short: {display} · chars={len(text or '')} < {min_chars_safe}[/dim]"
                )
            return

        if debug_extract:
            extra = f" · reason={reason_hint}" if reason_hint else ""
            console.print(
                f"[dim]extract: {display} · chars={len(text)}{extra}[/dim]"
            )

        if daemon_up:
            try:
                resp = httpx.post(
                    f"{client.DAEMON_BASE}/api/ingest",
                    json={"text": text, "source": source_value},
                    timeout=120.0,
                )
                resp.raise_for_status()
                payload = resp.json() if hasattr(resp, "json") else {}
                added_total += int((payload or {}).get("added", 0) or 0)
                processed += 1
                return
            except Exception as exc:
                q = _queue_learn_fallback(text, source=source_value, reason=f"api_error:{exc}")
                queue_paths.append(str(q))
                queued += 1
                failed += 1
                return

        q = _queue_learn_fallback(text, source=source_value, reason="daemon_offline")
        queue_paths.append(str(q))
        queued += 1

    for url in urls:
        try:
            text, meta = extract_text_from_url(url)
        except Exception as exc:
            failed += 1
            if debug_extract:
                console.print(f"[yellow]url-fel:[/yellow] {url} · {exc}")
            continue
        source_tag = str((meta or {}).get("source") or "web")
        reason = str((meta or {}).get("extract_reason") or "")
        _handle_payload(
            text=text,
            source_value=f"{source_tag}:{url}",
            display=url,
            reason_hint=reason,
        )

    file_items: list[tuple[str, str, str]] = []
    if files and ingestd_up:
        try:
            extracted = ingestd_client.extract_local_sources(
                sources=[str(f) for f in files],
                max_files=file_limit,
                min_chars=min_chars_safe,
                extensions=active_extensions,
            )
            file_items = [
                (
                    str(item.get("text") or ""),
                    str(item.get("source") or f"manual:{item.get('path') or ''}"),
                    str(item.get("display") or item.get("path") or item.get("source") or "ingestd"),
                )
                for item in (extracted.get("items") or [])
                if str(item.get("text") or "").strip()
            ]
            rust_errors = extracted.get("errors") or []
            failed += len(rust_errors)
            if debug_extract:
                for row in rust_errors[:8]:
                    if not isinstance(row, dict):
                        continue
                    console.print(
                        f"[yellow]ingestd-fel:[/yellow] {row.get('path', '?')} · {row.get('error', 'okänt fel')}"
                    )
        except Exception as exc:
            if debug_extract:
                console.print(f"[yellow]ingestd fallback:[/yellow] {exc}")
            file_items = []

    if file_items:
        for text, source_value, display in file_items:
            _handle_payload(
                text=text,
                source_value=source_value,
                display=display,
            )
    else:
        for f in files:
            text = extract_text(f)
            _handle_payload(
                text=text,
                source_value=f"manual:{f}",
                display=str(f),
            )

    console.print(
        f"[green]learn-from klart.[/green] "
        f"källor={len(normalized)} urls={len(urls)} filer={len(files)}"
    )
    console.print(
        f"[dim]ingested={processed} added_relations={added_total} "
        f"queued={queued} skipped_short={skipped_short} failed={failed} "
        f"missing={len(missing)}[/dim]"
    )

    if truncated:
        console.print(
            f"[yellow]Filscan trunkerad vid --max-files={file_limit}. "
            "Öka gränsen för större körning.[/yellow]"
        )
    if missing:
        for row in missing[:8]:
            console.print(f"[yellow]saknas:[/yellow] {row}")
    if queue_paths:
        console.print(f"[dim]queue: {queue_paths[0]}[/dim]")


@app.command(name="research")
def research_cmd(
    query: str = typer.Option(
        "",
        "--query",
        "-q",
        help="Forskningsfråga att escalera (graf -> web -> lär).",
    ),
    source: list[str] = typer.Option(
        [],
        "--source",
        "-s",
        help="Källor att ingestera först (URL, fil eller katalog).",
    ),
    include_home: bool = typer.Option(
        False,
        "--home",
        help="Inkludera hemkatalogen i ingest-steget.",
    ),
    include_iic: bool = typer.Option(
        False,
        "--iic",
        help="Inkludera IIC-disken i ingest-steget.",
    ),
    iic_root: str = typer.Option(
        "",
        "--iic-root",
        help="Explicit IIC-root för ingest.",
    ),
    learn: bool = typer.Option(
        True,
        "--learn/--no-learn",
        help="Skriv tillbaka ny kunskap till Nous vid query-escalation.",
    ),
    threshold: float = typer.Option(
        0.5,
        "--threshold",
        help="Escalation threshold för query-steget.",
    ),
    annotate: bool = typer.Option(
        True,
        "--annotate/--no-annotate",
        help="Extrahera findings/claims (insiktskandidater) från grafen.",
    ),
    top_k_insights: int = typer.Option(
        12,
        "--top-k-insights",
        help="Antal findings att returnera i annoteringssteget.",
    ),
    insight_limit: int = typer.Option(
        8000,
        "--insight-limit",
        help="Antal relationsrader att analysera i annoteringssteget.",
    ),
    insight_min_evidence: float = typer.Option(
        0.52,
        "--insight-min-evidence",
        help="Min evidensnivå för findings/claims.",
    ),
    insight_bridges: bool = typer.Option(
        True,
        "--insight-bridges/--no-insight-bridges",
        help="Inkludera domänbro-fynd.",
    ),
    save_insights: bool = typer.Option(
        True,
        "--save-insights/--no-save-insights",
        help="Spara findings till insights.jsonl.",
    ),
    promote_insights: bool = typer.Option(
        False,
        "--promote-insights/--no-promote-insights",
        help="Promovera starka findings till concept knowledge.",
    ),
    promote_min_score: float = typer.Option(
        0.74,
        "--promote-min-score",
        help="Min score för promotion.",
    ),
    max_promotions: int = typer.Option(
        8,
        "--max-promotions",
        help="Max antal findings att promovera.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Visa summering som JSON.",
    ),
) -> None:
    from nouse.field.surface import FieldSurface
    from nouse.insights import (
        extract_insight_candidates,
        promote_insight_candidates,
        save_insight_candidates,
    )
    from nouse.inject import attach

    query_clean = str(query or "").strip()
    sources = [str(x).strip() for x in (source or []) if str(x).strip()]
    safe_threshold = max(0.0, min(1.0, float(threshold)))

    console.print(
        "[bold cyan]Research Pipeline[/bold cyan] "
        "[dim](search/escalate -> fetch/ingest -> annotate findings/claims)[/dim]"
    )

    summary: dict[str, Any] = {
        "query": {},
        "ingest": {},
        "insights": {},
    }

    if sources or include_home or include_iic or str(iic_root or "").strip():
        learn_from_cmd(
            sources=sources,
            include_home=include_home,
            include_iic=include_iic,
            iic_root=iic_root,
            max_files=300,
            min_chars=100,
            extensions=".md,.txt,.py,.pdf",
            debug_extract=False,
        )
        summary["ingest"] = {
            "ran": True,
            "sources": len(sources),
            "include_home": bool(include_home),
            "include_iic": bool(include_iic),
        }

    if query_clean:
        result = attach(prefer_http=True).escalate_sync(
            query_clean,
            threshold=safe_threshold,
            learn=bool(learn),
        )
        console.print(
            f"[green]query:[/green] escalated={bool(result.escalated)} "
            f"learned={bool(result.learned)} sources={len(result.sources)} "
            f"confidence_before={float(result.confidence_before):.2f}"
        )
        summary["query"] = {
            "ran": True,
            "query": query_clean,
            "escalated": bool(result.escalated),
            "learned": bool(result.learned),
            "confidence_before": float(result.confidence_before),
            "sources": list(result.sources),
            "snippets": len(result.snippets),
        }

    if annotate:
        field = FieldSurface(read_only=(not promote_insights))
        extraction = extract_insight_candidates(
            field,
            limit=max(100, min(int(insight_limit), 50000)),
            top_k=max(1, min(int(top_k_insights), 200)),
            min_evidence=max(0.0, min(1.0, float(insight_min_evidence))),
            include_bridges=bool(insight_bridges),
        )
        candidates = extraction.get("candidates") or []
        console.print(
            f"[green]insights:[/green] selected={int(extraction.get('selected_count', 0) or 0)} "
            f"relation_candidates={int(extraction.get('relation_candidates', 0) or 0)} "
            f"bridge_candidates={int(extraction.get('bridge_candidates', 0) or 0)}"
        )

        save_result: dict[str, Any] | None = None
        if save_insights:
            save_result = save_insight_candidates(candidates, source="cli:research")
            console.print(
                f"[dim]insights sparat: {save_result.get('path')} "
                f"(written={int(save_result.get('written', 0) or 0)})[/dim]"
            )

        promote_result: dict[str, Any] | None = None
        if promote_insights:
            promote_result = promote_insight_candidates(
                field,
                candidates,
                max_items=max(1, min(int(max_promotions), 200)),
                min_score=max(0.0, min(1.0, float(promote_min_score))),
            )
            console.print(
                f"[dim]insights promotion: promoted={int(promote_result.get('promoted', 0) or 0)}[/dim]"
            )

        summary["insights"] = {
            "ran": True,
            "selected_count": int(extraction.get("selected_count", 0) or 0),
            "relation_candidates": int(extraction.get("relation_candidates", 0) or 0),
            "bridge_candidates": int(extraction.get("bridge_candidates", 0) or 0),
            "save_result": save_result,
            "promote_result": promote_result,
        }

    if not query_clean and not (sources or include_home or include_iic or str(iic_root or "").strip()) and not annotate:
        console.print(
            "[yellow]Inget att köra.[/yellow] Ange --query eller --source, "
            "eller kör med --annotate."
        )
        raise typer.Exit(1)

    if as_json:
        console.print_json(data=summary)


@app.command(name="research-output")
def research_output_cmd(
    query: str = typer.Option(
        "",
        "--query",
        "-q",
        help="Filter för relationer, annotations och insights.",
    ),
    concept: list[str] = typer.Option(
        [],
        "--concept",
        "-c",
        help="Pinna ett eller flera koncept i exporten.",
    ),
    relation_limit: int = typer.Option(
        40,
        "--relations",
        help="Max antal relationer i exporten.",
    ),
    annotation_limit: int = typer.Option(
        20,
        "--annotations",
        help="Max antal annotations/concept summaries i exporten.",
    ),
    insight_limit: int = typer.Option(
        15,
        "--insights",
        help="Max antal insights i exporten.",
    ),
    output_dir: str = typer.Option(
        "exports",
        "--out",
        help="Målkatalog för markdown/json-export.",
    ),
    stem: str = typer.Option(
        "",
        "--stem",
        help="Basnamn för outputfilerna.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Skriv även paketet till stdout som JSON.",
    ),
) -> None:
    from nouse.field.surface import FieldSurface
    from nouse.reports import build_research_output, render_research_output_markdown

    safe_relations = max(1, min(int(relation_limit), 500))
    safe_annotations = max(1, min(int(annotation_limit), 200))
    safe_insights = max(1, min(int(insight_limit), 200))
    query_clean = str(query or "").strip()
    concepts = [str(item).strip() for item in (concept or []) if str(item).strip()]

    field = FieldSurface(read_only=True)
    bundle = build_research_output(
        field,
        query=query_clean,
        concepts=concepts,
        relation_limit=safe_relations,
        annotation_limit=safe_annotations,
        insight_limit=safe_insights,
    )

    out_dir = Path(output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = str(stem or "").strip()
    if not safe_stem:
        slug_bits = []
        if query_clean:
            slug_bits.append(re.sub(r"[^a-z0-9]+", "-", query_clean.lower()).strip("-"))
        elif concepts:
            slug_bits.append(re.sub(r"[^a-z0-9]+", "-", concepts[0].lower()).strip("-"))
        slug_bits.append(datetime.now().strftime("%Y%m%d-%H%M%S"))
        safe_stem = "-".join(bit for bit in slug_bits if bit) or "research-output"

    md_path = out_dir / f"{safe_stem}.md"
    json_path = out_dir / f"{safe_stem}.json"
    md_path.write_text(render_research_output_markdown(bundle), encoding="utf-8")
    json_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    counts = bundle.get("counts") if isinstance(bundle.get("counts"), dict) else {}
    console.print(
        "[bold cyan]Research Output[/bold cyan] "
        f"relations={int(counts.get('relations', 0) or 0)} "
        f"annotations={int(counts.get('annotations', 0) or 0)} "
        f"insights={int(counts.get('insights', 0) or 0)}"
    )
    console.print(f"[green]markdown:[/green] {md_path}")
    console.print(f"[green]json:[/green] {json_path}")

    if as_json:
        console.print_json(data=bundle)


@app.command(name="research-bank")
def research_bank_cmd(
    paper: list[str] = typer.Option(
        [],
        "--paper",
        "-p",
        help="Paper eller lokal fil som ska användas för ordbank.",
    ),
    tag: list[str] = typer.Option(
        [],
        "--tag",
        "-t",
        help="Manuell tag eller seed-term.",
    ),
    max_terms: int = typer.Option(
        24,
        "--max-terms",
        help="Max antal ord/fraser i ordbanken.",
    ),
    max_queries: int = typer.Option(
        8,
        "--max-queries",
        help="Max antal webbsökningar att generera.",
    ),
    results_per_query: int = typer.Option(
        5,
        "--results-per-query",
        help="Max antal träffar per sökning.",
    ),
    provider: str = typer.Option(
        "",
        "--provider",
        help="Valfri sökprovider, t.ex. brave eller serper.",
    ),
    articles: bool = typer.Option(
        True,
        "--articles/--no-articles",
        help="Generera artikel/paper-sökningar.",
    ),
    data: bool = typer.Option(
        True,
        "--data/--no-data",
        help="Generera dataset/data-sökningar.",
    ),
    output_dir: str = typer.Option(
        "exports",
        "--out",
        help="Målkatalog för markdown/json-export.",
    ),
    stem: str = typer.Option(
        "",
        "--stem",
        help="Basnamn för outputfilerna.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Skriv även paketet till stdout som JSON.",
    ),
) -> None:
    from nouse.reports import build_research_bank, render_research_bank_markdown

    papers = [str(item).strip() for item in (paper or []) if str(item).strip()]
    tags = [str(item).strip() for item in (tag or []) if str(item).strip()]
    if not papers and not tags:
        console.print("[yellow]Ange minst ett --paper eller en --tag.[/yellow]")
        raise typer.Exit(1)
    if not articles and not data:
        console.print("[yellow]Minst ett av --articles eller --data måste vara aktivt.[/yellow]")
        raise typer.Exit(1)

    bundle = build_research_bank(
        paper_paths=papers,
        tags=tags,
        max_terms=max_terms,
        max_queries=max_queries,
        results_per_query=results_per_query,
        provider=provider,
        include_articles=bool(articles),
        include_data=bool(data),
    )

    out_dir = Path(output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = str(stem or "").strip()
    if not safe_stem:
        base = tags[0] if tags else Path(papers[0]).stem
        safe_stem = f"{re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-') or 'research-bank'}-bank"

    md_path = out_dir / f"{safe_stem}.md"
    json_path = out_dir / f"{safe_stem}.json"
    md_path.write_text(render_research_bank_markdown(bundle), encoding="utf-8")
    json_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    counts = bundle.get("counts") if isinstance(bundle.get("counts"), dict) else {}
    console.print(
        "[bold cyan]Research Bank[/bold cyan] "
        f"terms={int(counts.get('word_bank', 0) or 0)} "
        f"queries={int(counts.get('queries', 0) or 0)} "
        f"results={int(counts.get('results', 0) or 0)}"
    )
    console.print(f"[green]markdown:[/green] {md_path}")
    console.print(f"[green]json:[/green] {json_path}")

    if as_json:
        console.print_json(data=bundle)


@app.command(name="status")
def status_cmd() -> None:
    status_mod.run_status()


@app.command(name="brain")
def brain_cmd(
    action: str = typer.Argument(
        "status",
        help="status | health | state | gap | metrics | live | step | save",
    ),
    last_n: int = typer.Option(20, "--last-n", help="Antal cykler för metrics"),
    limit_nodes: int = typer.Option(12, "--limit-nodes", help="Max noder i live-vy"),
    limit_edges: int = typer.Option(16, "--limit-edges", help="Max kanter i live-vy"),
    events_json: str = typer.Option("", "--events-json", help="JSON-lista med events för step"),
) -> None:
    import nouse.client as client

    act = str(action or "status").strip().lower()

    if act == "step":
        parsed_events: list[dict[str, Any]] = []
        if events_json.strip():
            try:
                loaded = json.loads(events_json)
            except json.JSONDecodeError:
                console.print("[red]Ogiltig --events-json[/red]")
                raise typer.Exit(1)
            if not isinstance(loaded, list):
                console.print("[red]Ogiltig --events-json: måste vara en JSON-lista.[/red]")
                raise typer.Exit(1)
            parsed_events = [row for row in loaded if isinstance(row, dict)]

        if not client.brain_db_running():
            console.print("[red]brain-db-core offline[/red]")
            raise typer.Exit(1)
        console.print_json(data=client.brain_step(events=parsed_events))
        return

    if act in {"status", "health"}:
        if not client.brain_db_running():
            console.print("[red]brain-db-core offline[/red]")
            raise typer.Exit(1)
        health = client.brain_get_health()
        runtime = health.get("runtime") if isinstance(health.get("runtime"), dict) else {}
        console.print(
            "[green]brain-db-core online[/green] "
            f"cycle={runtime.get('cycle', '?')} "
            f"nodes={runtime.get('nodes', '?')} "
            f"edges={runtime.get('edges', '?')}"
        )
        return

    if not client.brain_db_running():
        console.print("[red]brain-db-core offline[/red]")
        raise typer.Exit(1)

    if act == "state":
        console.print_json(data=client.brain_get_state())
        return
    if act == "gap":
        console.print_json(data=client.brain_get_gap_map())
        return
    if act == "metrics":
        console.print_json(data=client.brain_get_metrics(last_n=last_n))
        return
    if act == "live":
        console.print_json(data=client.brain_get_live(limit_nodes=limit_nodes, limit_edges=limit_edges))
        return
    if act == "save":
        console.print_json(data=client.brain_save())
        return

    console.print("[red]Ogiltig action.[/red] Använd: status | health | state | gap | metrics | live | step | save")
    raise typer.Exit(1)


@app.command(name="clawbot")
def clawbot_cmd(
    action: str = typer.Argument("status", help="status | allowlist | approve | ingest"),
    channel: str = typer.Option("default", "--channel", "-c", help="Ingress-kanal"),
    code: str = typer.Option("", "--code", help="Pairing-kod"),
    text: str = typer.Option("", "--text", "-t", help="Text att ingestera"),
    actor_id: str = typer.Option("", "--actor-id", help="Avsändar-ID"),
    mode: str = typer.Option("now", "--mode", help="now | next-heartbeat"),
    strict_pairing: bool = typer.Option(True, "--strict-pairing/--open", help="Kräv allowlist/pairing"),
    context_key: str = typer.Option("", "--context-key", help="Valfri kontext-tag"),
) -> None:
    import nouse.client as client

    if not client.daemon_running():
        console.print("[red]nouse daemon ej nåbar[/red]")
        raise typer.Exit(1)

    act = str(action or "status").strip().lower()
    if act in {"status", "allowlist"}:
        console.print("[green]bridge online[/green]")
        console.print_json(data=client.brain_clawbot_allowlist(channel=channel))
        return

    if act == "approve":
        if not code.strip():
            console.print("[red]Ange --code för approve.[/red]")
            raise typer.Exit(1)
        console.print_json(data=client.brain_clawbot_approve(channel=channel, code=code.strip()))
        return

    if act == "ingest":
        if not text.strip():
            console.print("[red]Ange --text för ingest.[/red]")
            raise typer.Exit(1)
        console.print_json(
            data=client.brain_clawbot_ingest(
                text=text,
                channel=channel,
                actor_id=actor_id,
                source="cli",
                mode=mode,
                strict_pairing=strict_pairing,
                context_key=context_key,
            )
        )
        return

    console.print("[red]Okänd action.[/red] Använd: status | allowlist | approve | ingest")
    raise typer.Exit(1)


@app.command(name="hitl")
def hitl_cmd(
    action: str = typer.Argument("status", help="status | approve | approve-all | reject"),
    status: str = typer.Option("all", "--status", help="Filter för status") ,
    limit: int = typer.Option(20, "--limit", "-l", help="Max antal rader"),
    interrupt_id: int = typer.Option(0, "--id", help="Interrupt-id för approve/reject"),
    reviewer: str = typer.Option("cli", "--reviewer", help="Reviewer-id"),
    note: str = typer.Option("", "--note", help="Valfri notering"),
    run_queue: bool = typer.Option(
        True,
        "--run-queue/--no-run-queue",
        help="Efter approve-all: kör retry_failed + queue run.",
    ),
    run_count: int = typer.Option(25, "--run-count", help="Antal tasks att trigga vid queue run"),
    api_timeout: float = typer.Option(60.0, "--api-timeout", help="HTTP-timeout i sekunder för queue API"),
) -> None:
    from nouse.daemon.hitl import approve_interrupt, interrupt_stats, list_interrupts, reject_interrupt
    from nouse.daemon.research_queue import approve_task_after_hitl, reject_task_after_hitl

    act = str(action or "status").strip().lower()

    if act == "status":
        stats = interrupt_stats()
        rows = list_interrupts(status=None if status == "all" else status, limit=max(1, limit))
        console.print(
            f"[bold cyan]HITL[/bold cyan] total={stats.get('total', 0)} "
            f"pending={stats.get('pending', 0)} "
            f"approved={stats.get('approved', 0)} "
            f"rejected={stats.get('rejected', 0)}"
        )
        for row in rows:
            task = row.get("task") if isinstance(row.get("task"), dict) else {}
            console.print(
                f"  [dim]#{row.get('id')}[/dim] [yellow]{row.get('status')}[/yellow] "
                f"task=#{task.get('id', '?')} "
                f"domän=[green]{task.get('domain', 'okänd')}[/green] "
                f"reason={row.get('reason', '')}"
            )
        return

    if act in {"approve-all", "approve_all", "all"}:
        rows = list_interrupts(status="pending", limit=max(1, int(limit or 1)))
        if not rows:
            console.print("[dim]Inga pending interrupts att godkänna.[/dim]")
            return

        approved = 0
        failed = 0
        affected_task_ids: list[int] = []
        note_text = note or "approved via CLI approve-all"
        for row in rows:
            try:
                iid = int(row.get("id", 0) or 0) if isinstance(row, dict) else 0
            except Exception:
                iid = 0
            if iid <= 0:
                continue
            try:
                approved_row = approve_interrupt(iid, reviewer=reviewer, note=note_text)
                if not approved_row:
                    failed += 1
                    continue
                task_id = int(approved_row.get("task_id", -1) or -1)
                if task_id > 0:
                    approve_task_after_hitl(task_id, note=note_text)
                    affected_task_ids.append(task_id)
                approved += 1
            except Exception:
                failed += 1

        console.print(
            f"[green]Approve-all:[/green] approved={approved} failed={failed} total={len(rows)}"
        )
        if affected_task_ids:
            sample = ", ".join(str(x) for x in sorted(set(affected_task_ids))[:8])
            console.print(f"[dim]tasks återköade: {sample}[/dim]")

        if not run_queue:
            return

        import nouse.client as client

        if not client.daemon_running():
            console.print(
                "[yellow]Daemon ej nåbar för queue-run.[/yellow] "
                "Kör senare: `nouse strap --run-now --run-count 25` eller `/orchestrate` i chat."
            )
            return

        timeout = max(10.0, float(api_timeout or 60.0))
        try:
            retried = client.post_queue_retry_failed(
                limit=max(5, min(100, approved or 5)),
                reason="retry after nouse hitl approve-all",
                timeout=timeout,
            )
            retried_rows = retried.get("retried") if isinstance(retried, dict) else []
            retry_count = len(retried_rows) if isinstance(retried_rows, list) else 0
            console.print(f"[dim]queue retry_failed: retried={retry_count}[/dim]")
        except Exception as exc:
            console.print(f"[yellow]queue retry_failed misslyckades:[/yellow] {exc}")

        try:
            run_payload = client.post_queue_run(
                count=max(1, min(int(run_count or 1), 25)),
                source="cli_hitl_approve_all",
                wait=False,
                timeout=timeout,
            )
            status_text = str(run_payload.get("status") or "ok") if isinstance(run_payload, dict) else "ok"
            job_id = str(run_payload.get("job_id") or "").strip() if isinstance(run_payload, dict) else ""
            if job_id:
                console.print(f"[green]queue run:[/green] status={status_text} job_id={job_id}")
            else:
                console.print(f"[green]queue run:[/green] status={status_text}")
        except Exception as exc:
            console.print(f"[yellow]queue run misslyckades:[/yellow] {exc}")
        return

    if act == "approve":
        if interrupt_id <= 0:
            console.print("[red]Ange --id för interrupt.[/red]")
            raise typer.Exit(2)
        row = approve_interrupt(interrupt_id, reviewer=reviewer, note=note)
        if not row:
            console.print(f"[red]Interrupt #{interrupt_id} hittades inte.[/red]")
            raise typer.Exit(1)
        task_id = int(row.get("task_id", -1) or -1)
        if task_id > 0:
            approve_task_after_hitl(task_id, note=(note or "approved via CLI"))
        console.print(f"[green]Godkänd[/green] interrupt #{interrupt_id} -> task #{task_id} återköad.")
        return

    if act == "reject":
        if interrupt_id <= 0:
            console.print("[red]Ange --id för interrupt.[/red]")
            raise typer.Exit(2)
        row = reject_interrupt(interrupt_id, reviewer=reviewer, note=note)
        if not row:
            console.print(f"[red]Interrupt #{interrupt_id} hittades inte.[/red]")
            raise typer.Exit(1)
        task_id = int(row.get("task_id", -1) or -1)
        if task_id > 0:
            reject_task_after_hitl(task_id, reason=(note or "rejected via CLI"))
        console.print(f"[yellow]Avslagen[/yellow] interrupt #{interrupt_id} -> task #{task_id} markerad failed.")
        return

    console.print("[red]Ogiltig action.[/red] Använd: status | approve | approve-all | reject")
    raise typer.Exit(1)


@app.command(name="output-trace")
def output_trace_cmd(
    trace_id: str = typer.Option("", "--trace-id", help="Filtrera på trace-id"),
    limit: int = typer.Option(200, "--limit", "-l", help="Antal events"),
    as_json: bool = typer.Option(False, "--json", help="Skriv rå JSON"),
) -> None:
    import nouse.client as client
    from nouse.trace.output_trace import load_events

    safe_limit = max(1, min(limit, 5000))

    if client.daemon_running():
        try:
            payload = client.get_output_trace(trace_id=trace_id or None, limit=safe_limit)
            events = payload.get("events") if isinstance(payload.get("events"), list) else []
        except Exception:
            events = load_events(limit=safe_limit, trace_id=trace_id or None)
    else:
        events = load_events(limit=safe_limit, trace_id=trace_id or None)

    if not events:
        msg = (
            f"Ingen trace hittad för trace_id={trace_id}" if trace_id else "Inga trace-events hittade ännu."
        )
        console.print(f"[yellow]{msg}[/yellow]")
        return

    if as_json:
        console.print(json.dumps(events, ensure_ascii=False, indent=2))
        return

    _render_trace_rows(events, trace_id=trace_id)


@app.command(name="journal")
def journal_cmd(
    action: str = typer.Argument("show", help="show | summary | tail | path"),
    limit: int = typer.Option(12, "--limit", "-l", help="Antal rader i tail / urval för summary"),
    stage: str = typer.Option("", "--stage", help="Filtrera cycle_trace på stage (t.ex. source_ingest)"),
    as_json: bool = typer.Option(False, "--json", help="Skriv JSON"),
) -> None:
    from nouse.daemon.journal import (
        latest_journal_file,
        latest_research_file,
        load_research_events,
        summarize_research_events,
    )

    act = str(action or "show").strip().lower()
    if act not in {"show", "summary", "tail", "path"}:
        console.print("[red]Ogiltig action.[/red] Använd: show | summary | tail | path")
        raise typer.Exit(1)

    md_path = latest_journal_file()
    events_path = latest_research_file()
    safe_limit = max(1, min(int(limit), 200))

    if act == "path":
        payload = {
            "journal_markdown": str(md_path) if md_path else None,
            "journal_events": str(events_path) if events_path else None,
        }
        if as_json:
            console.print_json(data=payload)
            return
        console.print(
            f"[bold cyan]Journal Paths[/bold cyan]\n"
            f"md: {payload['journal_markdown']}\n"
            f"events: {payload['journal_events']}"
        )
        return

    _, events = load_research_events(limit=max(400, safe_limit * 40))
    summary = summarize_research_events(events)
    tail_rows = _journal_tail_rows(events, stage=stage, limit=safe_limit)
    payload = {
        "journal_markdown": str(md_path) if md_path else None,
        "journal_events": str(events_path) if events_path else None,
        "summary": summary,
        "tail": tail_rows,
    }

    if as_json:
        console.print_json(data=payload)
        return

    if not md_path and not events_path:
        console.print("[yellow]Ingen Nous journal hittades ännu.[/yellow]")
        console.print("[dim]Starta daemonen och kör några cykler/chat-anrop först.[/dim]")
        return

    console.print(
        f"[bold cyan]Nous Journal[/bold cyan] "
        f"[dim]md={str(md_path) if md_path else '-'} · events={str(events_path) if events_path else '-'}[/dim]"
    )

    if act in {"show", "summary"}:
        evidence = summary.get("evidence") if isinstance(summary.get("evidence"), dict) else {}
        console.print(
            f"[dim]events={int(summary.get('events_total', 0) or 0)} "
            f"cycle_trace={int(summary.get('cycle_trace_total', 0) or 0)} "
            f"avg_ev_mean={float(evidence.get('avg_evidence_mean', 0.0) or 0.0):.3f} "
            f"max_ev_peak={float(evidence.get('max_evidence_peak', 0.0) or 0.0):.3f} "
            f"quality_mean={float(evidence.get('quality_mean', 0.0) or 0.0):.3f}[/dim]"
        )
        stage_top = summary.get("stage_top") if isinstance(summary.get("stage_top"), list) else []
        if stage_top:
            console.print("[bold]Top stages[/bold]")
            for row in stage_top[:8]:
                if not isinstance(row, dict):
                    continue
                console.print(
                    f"- {str(row.get('stage') or 'unknown_stage')}: "
                    f"{int(row.get('count', 0) or 0)}"
                )

    if act in {"show", "tail"}:
        if stage:
            console.print(f"[bold]Tail (stage={stage})[/bold]")
        else:
            console.print("[bold]Tail[/bold]")
        _render_journal_tail(tail_rows)


@app.command(name="cc")
def center_cmd(
    set_node: str = typer.Option("", "--set", "-s", help="Sätt center-nod (CC)."),
    clear: bool = typer.Option(False, "--clear", help="Rensa center-nod (CC)."),
    as_json: bool = typer.Option(False, "--json", help="Skriv JSON"),
) -> None:
    import nouse.client as client

    if not client.daemon_running():
        console.print("[red]Daemon är inte igång.[/red] Starta med `nouse daemon web`.")
        raise typer.Exit(1)

    try:
        if clear:
            payload = client.delete_graph_center()
        elif str(set_node or "").strip():
            payload = client.post_graph_center(str(set_node).strip())
        else:
            payload = client.get_graph_center()
    except Exception as exc:
        console.print(f"[red]CC-anrop misslyckades:[/red] {exc}")
        raise typer.Exit(1)

    if as_json:
        console.print_json(data=payload)
        return

    if clear:
        if payload.get("cleared"):
            console.print("[green]CC rensad.[/green]")
        else:
            console.print("[yellow]Ingen CC var satt.[/yellow]")
        return

    if payload.get("ok") is False:
        console.print(f"[red]CC-fel:[/red] {payload.get('error') or 'okänt fel'}")
        raise typer.Exit(1)

    if str(set_node or "").strip():
        console.print(f"[green]CC satt:[/green] {payload.get('node') or '-'}")
        return

    if payload.get("configured"):
        exists = bool(payload.get("exists"))
        state = "finns i grafen" if exists else "saknas i grafen"
        console.print(
            f"[bold cyan]CC[/bold cyan] {payload.get('node') or '-'} [dim]({state})[/dim]"
        )
    else:
        console.print("[yellow]CC är inte satt ännu.[/yellow]")


@app.command(name="mission")
def mission_cmd(
    action: str = typer.Argument("show", help="show | set | clear | metrics"),
    text: str = typer.Option("", "--text", "-t", help="Mission-text (för action=set)"),
    north_star: str = typer.Option("", "--north-star", help="Övergripande riktning"),
    focus_domain: list[str] = typer.Option([], "--focus-domain", "-d", help="Domänfokus (kan anges flera gånger)"),
    kpi: list[str] = typer.Option([], "--kpi", help="KPI/utfallsmått (kan anges flera gånger)"),
    constraint: list[str] = typer.Option([], "--constraint", help="Begränsningar (kan anges flera gånger)"),
    lines: int = typer.Option(10, "--lines", "-n", help="Rader vid action=metrics"),
) -> None:
    from nouse.daemon.mission import clear_mission, load_mission, read_recent_metrics, save_mission

    act = str(action or "show").strip().lower()

    if act == "show":
        row = load_mission()
        if not row:
            console.print("[yellow]Ingen aktiv mission.[/yellow]")
            return
        console.print_json(data=row)
        return

    if act == "set":
        if not text.strip():
            console.print("[red]Ange --text för action=set.[/red]")
            raise typer.Exit(1)
        row = save_mission(
            text.strip(),
            north_star=north_star,
            focus_domains=focus_domain,
            kpis=kpi,
            constraints=constraint,
        )
        console.print("[green]Mission sparad.[/green]")
        console.print_json(data=row)
        return

    if act == "clear":
        cleared = clear_mission()
        if cleared:
            console.print("[green]Mission rensad.[/green]")
        else:
            console.print("[yellow]Ingen mission att rensa.[/yellow]")
        return

    if act == "metrics":
        rows = read_recent_metrics(limit=max(1, lines))
        if not rows:
            console.print("[yellow]Inga mission-metrics hittade.[/yellow]")
            return
        for row in rows:
            console.print_json(data=row)
        return

    console.print("[red]Ogiltig action.[/red] Använd: show | set | clear | metrics")
    raise typer.Exit(1)


@app.command(name="feedback")
def feedback_cmd(
    verdict: str = typer.Argument("good", help="good | bad — thumbs up eller down"),
    comment: str = typer.Option("", "--comment", "-c", help="Valfri kommentar"),
    as_json: bool = typer.Option(False, "--json", help="Skriv JSON"),
    summary: bool = typer.Option(False, "--summary", "-s", help="Visa feedback-sammanfattning"),
) -> None:
    """Operatörs-feedback (thumbs up/down). Använd: nouse feedback good/bad"""
    from nouse.daemon.eval_log import write_feedback, feedback_summary, read_feedback

    v = str(verdict or "good").strip().lower()
    if v not in ("good", "bad", "up", "down", "+", "-", "1", "0"):
        console.print("[red]Ogiltig verdict.[/red] Använd: good | bad")
        raise typer.Exit(1)

    if summary:
        s = feedback_summary()
        if as_json:
            console.print_json(data=s)
        else:
            console.print(f"[bold]Feedback-sammanfattning[/bold]")
            console.print(f"  Total: {s['total']}  Good: {s['good']}  Bad: {s['bad']}")
            console.print(f"  Ratio: {s['ratio']:.0%}  Recent: {s.get('recent_ratio', 0):.0%}  Trend: {s['trend']}")
        return

    # Hämta kontext om daemon är igång
    cycle = 0
    active_nodes: list[str] = []
    model = ""
    energy = 0.0
    try:
        import nouse.client as client
        if client.daemon_running():
            status = client.brain_status()
            cycle = int(status.get("cycle", 0) or 0)
            energy = float(status.get("homeostasis", {}).get("energy", 0) or 0)
            # Hämta topp-5 aktiva noder
            try:
                top = client.brain_top_relations(limit=5)
                active_nodes = [str(r.get("src", "")) for r in (top or []) if r.get("src")]
            except Exception:
                pass
    except Exception:
        pass

    path = write_feedback(
        v, comment=comment, cycle=cycle,
        active_nodes=active_nodes, model=model, energy=energy,
    )
    label = "[green]THUMBS UP[/green]" if v in ("good", "up", "+", "1") else "[red]THUMBS DOWN[/red]"
    console.print(f"{label} — loggat till {path.name}")
    if comment:
        console.print(f"  Kommentar: {comment[:80]}")
    if as_json:
        console.print_json(data={"verdict": v, "path": str(path)})


@app.command(name="goal")
def goal_cmd(
    action: str = typer.Argument("list", help="list | add | status | metrics"),
    title: str = typer.Option("", "--title", "-t", help="Måltitel (för add)"),
    kind: str = typer.Option("operator_mission", "--kind", "-k", help="Goal kind"),
    concepts: str = typer.Option("", "--concepts", "-c", help="Komma-separerade koncept"),
    domain: str = typer.Option("", "--domain", "-d", help="Domän"),
    goal_id: str = typer.Option("", "--id", help="Mål-ID (för status)"),
    as_json: bool = typer.Option(False, "--json", help="Skriv JSON"),
) -> None:
    """Hantera Intrinsic Drive-mål. Använd: nouse goal list/add/status/metrics"""
    from nouse.daemon.goal_registry import (
        active_goals, create_goal, goal_by_id, goal_metrics,
        load_goals, satisfy_goals, KIND_OPERATOR_MISSION,
    )

    action = (action or "list").strip().lower()

    if action == "metrics":
        m = goal_metrics()
        if as_json:
            console.print_json(data=m)
        else:
            console.print("[bold]Goal Metrics[/bold]")
            console.print(f"  Total: {m['goals_total']}  Active: {m['goals_active']}  Satisfied: {m['goals_satisfied_total']}")
            console.print(f"  Satisfaction rate: {m['goal_satisfaction_rate']:.0%}  Progress mean: {m['goal_progress_mean']:.0%}")
            if m['goals_by_kind']:
                console.print("  By kind:")
                for kind, count in m['goals_by_kind'].items():
                    console.print(f"    {kind}: {count}")
        return

    if action == "add":
        if not title:
            console.print("[red]Använd --title för att ange måltitel[/red]")
            raise typer.Exit(1)
        concept_list = [c.strip() for c in concepts.split(",") if c.strip()] if concepts else []
        from nouse.daemon.nightrun import NightRunConfig
        config = NightRunConfig.load()
        # Använd nuvarande cykel om daemon är igång
        cycle = 0
        try:
            import nouse.client as client
            if client.daemon_running():
                status = client.brain_status()
                cycle = int(status.get("cycle", 0) or 0)
        except Exception:
            pass
        goal = create_goal(
            title=title,
            kind=kind,
            target_concepts=concept_list,
            target_domain=domain,
            source="operator",
            created_cycle=cycle,
        )
        if as_json:
            from dataclasses import asdict
            console.print_json(data=asdict(goal))
        else:
            console.print(f"[green]Mål skapat:[/green] {goal.id}")
            console.print(f"  Titel: {goal.title}")
            console.print(f"  Kind: {goal.kind}  Prioritet: {goal.priority:.2f}")
            console.print(f"  Koncept: {', '.join(goal.target_concepts) or '(inga)'}")
            if domain:
                console.print(f"  Domän: {domain}")
        return

    if action == "status":
        if not goal_id:
            # Visa alla aktiva
            goals = active_goals()
            if not goals:
                console.print("[dim]Inga aktiva mål.[/dim]")
                return
            for g in goals:
                console.print(f"[bold]{g.id}[/bold] {g.title[:60]}")
                console.print(f"  kind={g.kind} prio={g.priority:.2f} progress={g.progress:.0%} cycle={g.created_cycle}")
            return
        g = goal_by_id(goal_id)
        if g is None:
            console.print(f"[red]Mål {goal_id} hittades inte[/red]")
            raise typer.Exit(1)
        if as_json:
            from dataclasses import asdict
            console.print_json(data=asdict(g))
        else:
            console.print(f"[bold]Mål {g.id}[/bold]")
            console.print(f"  Titel: {g.title}")
            console.print(f"  Kind: {g.kind}  Status: {g.status}")
            console.print(f"  Prioritet: {g.priority:.2f}  Progress: {g.progress:.0%}")
            console.print(f"  Koncept: {', '.join(g.target_concepts) or '(inga)'}")
            console.print(f"  Domän: {g.target_domain or '-'}")
            console.print(f"  Skapat: cycle {g.created_cycle}  Uppdaterat: cycle {g.updated_cycle}")
            console.print(f"  Deadline: {g.deadline_cycle or 'ingen'}")
            if g.satisfaction_criteria:
                console.print(f"  Kriterier: {g.satisfaction_criteria}")
        return

    if action in ("satisfy", "close", "done"):
        if not goal_id:
            console.print("[red]Använd --id för att ange mål-ID[/red]")
            raise typer.Exit(1)
        n = satisfy_goals([goal_id], cycle=0)
        if n > 0:
            console.print(f"[green]Mål {goal_id} markerat som uppnått[/green]")
        else:
            console.print(f"[yellow]Mål {goal_id} hittades inte eller redan stängt[/yellow]")
        return

    # Default: list
    goals = active_goals()
    if not goals:
        console.print("[dim]Inga aktiva mål.[/dim]")
        return
    if as_json:
        from dataclasses import asdict
        console.print_json(data=[asdict(g) for g in goals])
    else:
        console.print(f"[bold]Aktiva mål ({len(goals)})[/bold]")
        for g in goals:
            bar = "█" * int(g.progress * 10) + "░" * (10 - int(g.progress * 10))
            console.print(
                f"  {g.id[:8]}  {g.kind[:20]:<20} {bar} {g.progress:.0%}  "
                f"prio={g.priority:.2f}  {g.title[:40]}"
            )


@app.command(name="revenue")
def revenue_cmd(
    action: str = typer.Argument(
        "status",
        help=(
            "init | prospect | scan | score | draft | outbox | "
            "hitl-status | hitl-sync | approve | reject | sent | paid | kpi | run-daily | status"
        ),
    ),
    root: str = typer.Option(".", "--root", help="Projektrot för revenue-filer."),
    lead: list[str] = typer.Option(
        [],
        "--lead",
        help='Leadrad: "Company|domain|contact|note" (kan anges flera gånger).',
    ),
    lead_file: str = typer.Option(
        "",
        "--lead-file",
        help="Textfil med en leadrad per rad i format Company|domain|contact|note.",
    ),
    query: list[str] = typer.Option(
        [],
        "--query",
        help="Web-query för prospect-läget (kan anges flera gånger).",
    ),
    max_results_per_query: int = typer.Option(
        8,
        "--max-results-per-query",
        help="Max träffar per query i prospect.",
    ),
    segment: str = typer.Option("ai-research", "--segment", help="Segmentprofil för scoring."),
    top: int = typer.Option(10, "--top", help="Max antal leads/drafts att processa."),
    min_score: float = typer.Option(0.55, "--min-score", help="Min score för qualified/draft."),
    ids: str = typer.Option("", "--ids", help="CSV med outbox-id (t.ex. 1,2,3). Tom = alla relevanta."),
    amount: float = typer.Option(0.0, "--amount", help="Belopp SEK för action=paid."),
    note: str = typer.Option("", "--note", help="Valfri note för action=paid."),
    date: str = typer.Option("", "--date", help="Datum (YYYY-MM-DD) för action=kpi."),
    as_json: bool = typer.Option(False, "--json", help="Skriv JSON-output."),
) -> None:
    from nouse.daemon.mission import save_mission
    from nouse.revenue.loop import (
        append_leads,
        approve_outreach,
        create_outreach_drafts,
        ensure_revenue_scaffold,
        hitl_status,
        list_outbox,
        log_paid_order,
        mark_outreach_sent,
        parse_lead_line,
        prospect_leads_from_web,
        reject_outreach,
        revenue_kpi_summary,
        revenue_paths,
        sync_outbox_from_hitl,
        score_leads,
    )

    act = str(action or "status").strip().lower()
    project_root = Path(root).expanduser().resolve()

    def _parse_ids_csv(raw: str) -> list[int]:
        out: list[int] = []
        for part in str(raw or "").split(","):
            text = part.strip()
            if not text:
                continue
            try:
                value = int(text)
            except ValueError:
                continue
            if value > 0:
                out.append(value)
        return out

    if act == "init":
        payload = ensure_revenue_scaffold(project_root)
        local_mission_path = project_root / "mission" / "mission_runtime.json"
        mission_payload = save_mission(
            "Revenue Loop v1: första verifierbara intäkt inom 14 dagar",
            north_star="Nous tjänar första egna pengar kontrollerat och mätbart",
            focus_domains=["AI", "go-to-market", "sales", "customer_insight"],
            kpis=[
                "new_leads_count",
                "qualified_leads_count",
                "approved_outreach_count",
                "paid_orders_count",
                "revenue_sek",
            ],
            constraints=[
                "no_autonomous_contract_signing",
                "no_autonomous_payments",
                "no_outbound_without_hitl_approval",
            ],
            path=local_mission_path,
        )
        payload["mission_applied"] = True
        payload["mission_version"] = int(mission_payload.get("version", 0) or 0)
        payload["mission_path"] = str(local_mission_path)
        if as_json:
            console.print_json(data=payload)
            return
        console.print("[green]Revenue scaffold init klar.[/green]")
        for row in payload.get("created") or []:
            console.print(f"[dim]created: {row}[/dim]")
        return

    if act == "scan":
        ensure_revenue_scaffold(project_root)
        parsed: list[dict[str, str]] = []
        for raw in lead:
            row = parse_lead_line(raw)
            if row:
                parsed.append(row)
        if str(lead_file or "").strip():
            file_path = Path(lead_file).expanduser()
            if not file_path.exists():
                console.print(f"[red]lead-file hittades inte:[/red] {file_path}")
                raise typer.Exit(1)
            for raw_line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                row = parse_lead_line(raw_line)
                if row:
                    parsed.append(row)
        if not parsed:
            console.print("[yellow]Inga giltiga leads. Ange --lead eller --lead-file.[/yellow]")
            raise typer.Exit(1)
        out = append_leads(project_root, parsed, source="revenue_scan")
        if as_json:
            console.print_json(data=out)
            return
        console.print(
            f"[green]scan:[/green] added={int(out.get('added', 0) or 0)} total={int(out.get('total', 0) or 0)}"
        )
        return

    if act == "prospect":
        ensure_revenue_scaffold(project_root)
        queries = [str(q or "").strip() for q in query if str(q or "").strip()]
        if not queries:
            queries = [
                "AI consultancy Sweden",
                "applied AI research lab",
                "LLM governance consulting",
            ]
        out = prospect_leads_from_web(
            project_root,
            queries=queries,
            max_results_per_query=max(1, min(int(max_results_per_query), 25)),
        )
        if as_json:
            console.print_json(data=out)
            return
        console.print(
            f"[green]prospect:[/green] prospected={int(out.get('prospected', 0) or 0)} "
            f"added={int(out.get('added', 0) or 0)} total={int(out.get('total', 0) or 0)}"
        )
        return

    if act == "score":
        ensure_revenue_scaffold(project_root)
        out = score_leads(
            project_root,
            segment=segment,
            min_score=max(0.0, min(1.0, float(min_score))),
            top=max(1, int(top)),
        )
        if as_json:
            console.print_json(data=out)
            return
        console.print(
            f"[green]score:[/green] scored={int(out.get('scored', 0) or 0)} "
            f"qualified={int(out.get('qualified', 0) or 0)} segment={out.get('segment')}"
        )
        return

    if act == "draft":
        ensure_revenue_scaffold(project_root)
        out = create_outreach_drafts(
            project_root,
            min_score=max(0.0, min(1.0, float(min_score))),
            max_items=max(1, int(top)),
        )
        if as_json:
            console.print_json(data=out)
            return
        console.print(
            f"[green]draft:[/green] drafted={int(out.get('drafted', 0) or 0)} "
            f"total_outbox={int(out.get('total_outbox', 0) or 0)}"
        )
        return

    if act == "outbox":
        ensure_revenue_scaffold(project_root)
        rows = list_outbox(project_root, status="all", limit=max(1, int(top)))
        if as_json:
            console.print_json(data={"rows": rows})
            return
        if not rows:
            console.print("[yellow]Outbox tom.[/yellow]")
            return
        console.print("[bold cyan]Revenue Outbox[/bold cyan]")
        for row in rows:
            console.print(
                f"- id={int(row.get('id', 0) or 0)} status={row.get('status')} "
                f"lead_id={int(row.get('lead_id', 0) or 0)} company={row.get('company')} "
                f"hitl_id={int(row.get('hitl_interrupt_id', 0) or 0)} "
                f"hitl={row.get('hitl_status')}"
            )
        return

    if act == "hitl-status":
        ensure_revenue_scaffold(project_root)
        out = hitl_status(project_root)
        if as_json:
            console.print_json(data=out)
            return
        console.print(
            f"[green]hitl:[/green] pending={int(out.get('pending', 0) or 0)} "
            f"approved={int(out.get('approved', 0) or 0)} rejected={int(out.get('rejected', 0) or 0)}"
        )
        return

    if act == "hitl-sync":
        ensure_revenue_scaffold(project_root)
        out = sync_outbox_from_hitl(project_root)
        if as_json:
            console.print_json(data=out)
            return
        console.print(
            f"[green]hitl-sync:[/green] approved={int(out.get('changed_approved', 0) or 0)} "
            f"rejected={int(out.get('changed_rejected', 0) or 0)}"
        )
        return

    if act == "approve":
        ensure_revenue_scaffold(project_root)
        out = approve_outreach(project_root, ids=_parse_ids_csv(ids))
        if as_json:
            console.print_json(data=out)
            return
        console.print(
            f"[green]approve:[/green] approved={int(out.get('changed_approved', out.get('changed', 0)) or 0)} "
            f"rejected={int(out.get('changed_rejected', 0) or 0)}"
        )
        return

    if act == "reject":
        ensure_revenue_scaffold(project_root)
        out = reject_outreach(project_root, ids=_parse_ids_csv(ids), note=note)
        if as_json:
            console.print_json(data=out)
            return
        console.print(
            f"[green]reject:[/green] approved={int(out.get('changed_approved', 0) or 0)} "
            f"rejected={int(out.get('changed_rejected', 0) or 0)}"
        )
        return

    if act == "sent":
        ensure_revenue_scaffold(project_root)
        sync_outbox_from_hitl(project_root)
        out = mark_outreach_sent(project_root, ids=_parse_ids_csv(ids))
        if as_json:
            console.print_json(data=out)
            return
        console.print(f"[green]sent:[/green] changed={int(out.get('changed', 0) or 0)}")
        return

    if act == "paid":
        ensure_revenue_scaffold(project_root)
        if float(amount) <= 0.0:
            console.print("[red]Ange --amount > 0 för action=paid.[/red]")
            raise typer.Exit(1)
        out = log_paid_order(project_root, amount_sek=float(amount), note=note)
        if as_json:
            console.print_json(data=out)
            return
        console.print(f"[green]paid:[/green] amount_sek={float(out.get('amount_sek', 0.0) or 0.0):.2f}")
        return

    if act == "run-daily":
        ensure_revenue_scaffold(project_root)
        summary: dict[str, Any] = {"ok": True}
        if lead or str(lead_file or "").strip():
            parsed: list[dict[str, str]] = []
            for raw in lead:
                row = parse_lead_line(raw)
                if row:
                    parsed.append(row)
            if str(lead_file or "").strip():
                file_path = Path(lead_file).expanduser()
                if file_path.exists():
                    for raw_line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                        row = parse_lead_line(raw_line)
                        if row:
                            parsed.append(row)
            if parsed:
                summary["scan"] = append_leads(project_root, parsed, source="revenue_daily_scan")
        if query:
            summary["prospect"] = prospect_leads_from_web(
                project_root,
                queries=[str(q).strip() for q in query if str(q).strip()],
                max_results_per_query=max(1, min(int(max_results_per_query), 25)),
            )
        summary["score"] = score_leads(
            project_root,
            segment=segment,
            min_score=max(0.0, min(1.0, float(min_score))),
            top=max(1, int(top)),
        )
        summary["draft"] = create_outreach_drafts(
            project_root,
            min_score=max(0.0, min(1.0, float(min_score))),
            max_items=max(1, int(top)),
        )
        summary["hitl_sync"] = sync_outbox_from_hitl(project_root)
        summary["kpi"] = revenue_kpi_summary(project_root, date_key=(date.strip() or None))
        if as_json:
            console.print_json(data=summary)
            return
        console.print(
            f"[green]run-daily:[/green] "
            f"qualified={int((summary.get('score') or {}).get('qualified', 0) or 0)} "
            f"drafted={int((summary.get('draft') or {}).get('drafted', 0) or 0)} "
            f"approved_outreach={int((summary.get('kpi') or {}).get('approved_outreach_count', 0) or 0)}"
        )
        return

    if act in {"kpi", "status"}:
        ensure_revenue_scaffold(project_root)
        summary = revenue_kpi_summary(project_root, date_key=(date.strip() or None))
        if as_json:
            console.print_json(data=summary)
            return
        console.print(
            Panel(
                "[bold cyan]Revenue KPI[/bold cyan]\n"
                f"date={summary.get('date')}\n"
                f"new_leads={summary.get('new_leads_count', 0)} "
                f"qualified={summary.get('qualified_leads_count', 0)} "
                f"approved_outreach={summary.get('approved_outreach_count', 0)}\n"
                f"paid_orders={summary.get('paid_orders_count', 0)} "
                f"revenue_sek={float(summary.get('revenue_sek', 0.0) or 0.0):.2f}\n"
                f"[dim]root={revenue_paths(project_root)['root']}[/dim]",
                border_style="cyan",
            )
        )
        return

    console.print(
        "[red]Ogiltig action.[/red] "
        "Använd: init | prospect | scan | score | draft | outbox | hitl-status | hitl-sync | "
        "approve | reject | sent | paid | kpi | run-daily | status"
    )
    raise typer.Exit(1)


@app.command(name="trace-probe")
def trace_probe_cmd(
    set_path: str = typer.Option(
        "results/eval_set_trace_observability.yaml",
        "--set",
        help="YAML med testproblem för trace-observability",
    ),
    limit: int = typer.Option(8, "--limit", "-l", help="Max antal problem att köra"),
    timeout_sec: float = typer.Option(90.0, "--timeout", help="Timeout per fråga"),
) -> None:
    path = Path(set_path)
    if not path.exists():
        console.print(f"[red]Testset hittades inte:[/red] {path}")
        raise typer.Exit(1)

    raw = path.read_text(encoding="utf-8", errors="ignore")
    entries = [line for line in raw.splitlines() if line.lstrip().startswith("-")]
    available = len(entries)
    planned = min(max(1, limit), available if available > 0 else max(1, limit))

    console.print(
        f"[bold cyan]Trace Probe[/bold cyan] set={path} "
        f"available={available} planned={planned} timeout={timeout_sec:.1f}s"
    )


@app.command(name="knowledge-audit")
def knowledge_audit_cmd(
    limit: int = typer.Option(50, "--limit", "-l", help="Antal saknade noder att visa"),
    strict: bool = typer.Option(True, "--strict/--basic", help="Strict kräver stark evidens"),
    min_evidence_score: float = typer.Option(0.65, "--min-evidence-score", help="Min score för strong-facts"),
) -> None:
    import nouse.client as client
    from nouse.field.surface import FieldSurface

    safe_limit = max(1, min(limit, 5000))
    min_score = max(0.0, min(1.0, float(min_evidence_score)))

    if client.daemon_running():
        try:
            audit = client.get_knowledge_audit(
                limit=safe_limit,
                strict=strict,
                min_evidence_score=min_score,
            )
        except Exception:
            field = FieldSurface(read_only=True)
            audit = field.knowledge_audit(limit=safe_limit, strict=strict, min_evidence_score=min_score)
    else:
        field = FieldSurface(read_only=True)
        audit = field.knowledge_audit(limit=safe_limit, strict=strict, min_evidence_score=min_score)

    total = int(audit.get("total_concepts", 0) or 0)
    complete = int(audit.get("complete_nodes", 0) or 0)
    missing_total = int(audit.get("missing_total", 0) or 0)
    cov = audit.get("coverage") if isinstance(audit.get("coverage"), dict) else {}
    context_cov = float(cov.get("context", 0.0) or 0.0)
    facts_cov = float(cov.get("facts", 0.0) or 0.0)
    strong_cov = float(cov.get("strong_facts", 0.0) or 0.0)
    complete_cov = float(cov.get("complete", 0.0) or 0.0)

    console.print(
        f"[bold cyan]Knowledge Audit[/bold cyan] total={total} complete={complete} missing={missing_total}"
    )
    console.print(
        f"[dim]coverage: context={context_cov:.1%} facts={facts_cov:.1%} "
        f"strong_facts={strong_cov:.1%} complete={complete_cov:.1%}[/dim]"
    )

    for row in (audit.get("missing") or [])[:safe_limit]:
        reasons = ",".join(row.get("reasons") or [])
        console.print(
            f"- [yellow]{row.get('name', '?')}[/yellow] "
            f"[dim]domain={row.get('domain', '?')} reasons={reasons} "
            f"claims={row.get('claims', 0)} evidence={row.get('evidence_refs', 0)}[/dim]"
        )


@app.command(name="extract-insights")
def extract_insights_cmd(
    limit: int = typer.Option(8000, "--limit", "-l", help="Antal relationsrader att analysera"),
    top_k: int = typer.Option(12, "--top-k", "-k", help="Antal insiktskandidater att visa"),
    min_evidence: float = typer.Option(0.52, "--min-evidence", help="Min evidensnivå för kandidater"),
    bridges: bool = typer.Option(True, "--bridges/--no-bridges", help="Inkludera domänbro-insikter"),
    save: bool = typer.Option(True, "--save/--no-save", help="Spara kandidater till insights.jsonl"),
    plasticity_feedback: bool = typer.Option(
        False,
        "--plasticity-feedback/--no-plasticity-feedback",
        help="Applicera första plasticitetsfeedback på stödkanter från insight-gaten",
    ),
    promote: bool = typer.Option(False, "--promote", help="Promovera starka kandidater till concept knowledge"),
    promote_min_score: float = typer.Option(0.74, "--promote-min-score", help="Min score för promotion"),
    max_promotions: int = typer.Option(8, "--max-promotions", help="Max antal promotions per körning"),
    as_json: bool = typer.Option(False, "--json", help="Skriv även full JSON-output"),
) -> None:
    from nouse.field.surface import FieldSurface
    from nouse.insights import (
        apply_insight_plasticity,
        extract_insight_candidates,
        promote_insight_candidates,
        save_insight_candidates,
    )

    safe_limit = max(100, min(int(limit), 50000))
    safe_top_k = max(1, min(int(top_k), 200))
    safe_min_ev = max(0.0, min(1.0, float(min_evidence)))
    safe_promote_min = max(0.0, min(1.0, float(promote_min_score)))
    safe_max_promotions = max(1, min(int(max_promotions), 200))

    field = FieldSurface(read_only=(not (promote or plasticity_feedback)))
    result = extract_insight_candidates(
        field,
        limit=safe_limit,
        top_k=safe_top_k,
        min_evidence=safe_min_ev,
        include_bridges=bool(bridges),
    )

    console.print(
        f"[bold cyan]Insight Extraction[/bold cyan] "
        f"rows={int(result.get('total_relation_rows', 0) or 0)} "
        f"selected={int(result.get('selected_count', 0) or 0)} "
        f"(relation={int(result.get('relation_candidates', 0) or 0)}, "
        f"bridge={int(result.get('bridge_candidates', 0) or 0)}, "
        f"gate_pass={int(result.get('gate_passed', 0) or 0)}, "
        f"gate_review={int(result.get('gate_review', 0) or 0)})"
    )

    candidates = result.get("candidates") or []
    for idx, item in enumerate(candidates, start=1):
        score = float(item.get("score", 0.0) or 0.0)
        ev = float(item.get("mean_evidence", 0.0) or 0.0)
        support = int(item.get("support", 0) or 0)
        tier = str(item.get("tier") or "hypotes")
        statement = str(item.get("statement") or "").strip()
        kind = str(item.get("kind") or "insight")
        basis = item.get("basis") if isinstance(item.get("basis"), dict) else {}
        method = str(basis.get("method") or "-")
        support_rows = int(basis.get("support_rows", support) or support)
        distinct_why = int(basis.get("distinct_why", 0) or 0)
        comp = basis.get("score_components") if isinstance(basis.get("score_components"), dict) else {}
        c_ev = float(comp.get("evidence", ev) or ev)
        c_sup = float(comp.get("support", 0.0) or 0.0)
        c_nov = float(comp.get("novelty", 0.0) or 0.0)
        c_act = float(comp.get("actionability", 0.0) or 0.0)
        gate = item.get("insight_gate") if isinstance(item.get("insight_gate"), dict) else {}
        gate_status = str(gate.get("status") or "unknown")
        gate_overall = float(gate.get("overall", 0.0) or 0.0)
        gate_comp = gate.get("components") if isinstance(gate.get("components"), dict) else {}
        g_ground = float(gate_comp.get("grounding", 0.0) or 0.0)
        g_expl = float(gate_comp.get("explanation", 0.0) or 0.0)
        g_gain = float(gate_comp.get("epistemic_gain", 0.0) or 0.0)
        g_contra = float(gate_comp.get("contradiction_resilience", 0.0) or 0.0)
        g_cons = float(gate_comp.get("consequence", 0.0) or 0.0)
        console.print(
            f"{idx}. [yellow]{tier}[/yellow] score={score:.2f} ev={ev:.2f} "
            f"support={support} [dim]{kind}[/dim]"
        )
        if statement:
            console.print(f"   {statement}")
        console.print(
            "   [dim]"
            f"data: method={method} rows={support_rows} why={distinct_why} "
            f"components(ev={c_ev:.2f}, sup={c_sup:.2f}, nov={c_nov:.2f}, act={c_act:.2f})"
            "[/dim]"
        )
        console.print(
            "   [dim]"
            f"gate: status={gate_status} overall={gate_overall:.2f} "
            f"(ground={g_ground:.2f}, expl={g_expl:.2f}, gain={g_gain:.2f}, "
            f"contra={g_contra:.2f}, cons={g_cons:.2f})"
            "[/dim]"
        )
        understanding = item.get("understanding") if isinstance(item.get("understanding"), dict) else {}
        why_it_matters = str(understanding.get("why_it_matters") or "").strip()
        bridge_reason = str(understanding.get("bridge_reason") or "").strip()
        if why_it_matters:
            console.print(f"   [dim]understanding: {why_it_matters}[/dim]")
        if kind == "relation_pattern":
            src_node = understanding.get("source_node") if isinstance(understanding.get("source_node"), dict) else {}
            tgt_node = understanding.get("target_node") if isinstance(understanding.get("target_node"), dict) else {}
            src_summary = str(src_node.get("summary") or "").strip()
            tgt_summary = str(tgt_node.get("summary") or "").strip()
            if src_summary:
                console.print(f"   [dim]src: {src_summary[:180]}[/dim]")
            if tgt_summary:
                console.print(f"   [dim]tgt: {tgt_summary[:180]}[/dim]")
        elif kind == "domain_bridge":
            anchor_node = understanding.get("anchor_node") if isinstance(understanding.get("anchor_node"), dict) else {}
            anchor_summary = str(anchor_node.get("summary") or "").strip()
            if anchor_summary:
                console.print(f"   [dim]anchor: {anchor_summary[:180]}[/dim]")
        if bridge_reason:
            console.print(f"   [dim]why: {bridge_reason[:220]}[/dim]")

    save_result: dict[str, Any] | None = None
    if save:
        save_result = save_insight_candidates(candidates, source="cli:extract-insights")
        console.print(
            f"[dim]sparat: {save_result.get('path')} "
            f"(written={int(save_result.get('written', 0) or 0)})[/dim]"
        )

    plasticity_result: dict[str, Any] | None = None
    if plasticity_feedback:
        plasticity_result = apply_insight_plasticity(
            field,
            candidates,
            max_items=safe_top_k,
        )
        by_status = plasticity_result.get("by_status") if isinstance(plasticity_result.get("by_status"), dict) else {}
        console.print(
            "[dim]"
            "plasticity: "
            f"considered={int(plasticity_result.get('considered', 0) or 0)} "
            f"edges={int(plasticity_result.get('edges_touched', 0) or 0)} "
            f"reinforced={int(plasticity_result.get('reinforced', 0) or 0)} "
            f"weakened={int(plasticity_result.get('weakened', 0) or 0)} "
            f"status(pass={int(by_status.get('pass', 0) or 0)}, "
            f"review={int(by_status.get('review', 0) or 0)}, "
            f"reject={int(by_status.get('reject', 0) or 0)})"
            "[/dim]"
        )

    promote_result: dict[str, Any] | None = None
    if promote:
        promote_result = promote_insight_candidates(
            field,
            candidates,
            max_items=safe_max_promotions,
            min_score=safe_promote_min,
        )
        console.print(
            f"[green]promotion:[/green] promoted={int(promote_result.get('promoted', 0) or 0)} "
            f"min_score={safe_promote_min:.2f}"
        )

    if as_json:
        payload = {
            **result,
            "save_result": save_result,
            "plasticity_result": plasticity_result,
            "promote_result": promote_result,
        }
        console.print_json(data=payload)


@app.command(name="capability-graph")
def capability_graph_cmd(
    route: str = typer.Option("", "--route", help="Intent eller uppgift att route:a genom capability graph"),
    state: str = typer.Option("", "--state", help="Operator state, t.ex. stalled, overload, low_energy"),
    needs_web: bool = typer.Option(False, "--needs-web", help="Markera att färsk webbinformation behövs"),
    needs_files: bool = typer.Option(False, "--needs-files", help="Markera att lokala filer/systemytor behövs"),
    needs_memory_write: bool = typer.Option(False, "--needs-memory-write", help="Markera att resultatet bör kunna skrivas till minne"),
    needs_action: bool = typer.Option(False, "--needs-action", help="Markera att agentisk handling behövs"),
    probe_models: bool = typer.Option(False, "--probe-models", help="Proba tillgängliga model providers live"),
    save: bool = typer.Option(True, "--save/--no-save", help="Spara snapshot till capability_graph.json"),
    write_to_field: bool = typer.Option(False, "--write-to-field", help="Indexera planes och bryggor i Nous-fältet"),
    as_json: bool = typer.Option(False, "--json", help="Skriv full JSON-output"),
) -> None:
    from nouse.capability import (
        build_capability_graph,
        index_capability_graph,
        recommend_capability_route,
        save_capability_graph,
    )
    from nouse.field.surface import FieldSurface

    snapshot = build_capability_graph(probe_models=bool(probe_models))
    counts = snapshot.get("counts") if isinstance(snapshot.get("counts"), dict) else {}
    planes = snapshot.get("planes") if isinstance(snapshot.get("planes"), dict) else {}

    save_result: dict[str, Any] | None = None
    if save:
        save_result = save_capability_graph(snapshot)

    field_result: dict[str, Any] | None = None
    if write_to_field:
        field = FieldSurface()
        field_result = index_capability_graph(field, snapshot)

    route_result: dict[str, Any] | None = None
    if str(route or "").strip():
        route_result = recommend_capability_route(
            route,
            state=state,
            needs_web=bool(needs_web),
            needs_files=bool(needs_files),
            needs_memory_write=bool(needs_memory_write),
            needs_action=bool(needs_action),
            probe_models=bool(probe_models),
        )

    if as_json:
        payload = {
            "snapshot": snapshot,
            "save_result": save_result,
            "field_result": field_result,
            "route_result": route_result,
        }
        console.print_json(data=payload)
        return

    console.print(
        f"[bold cyan]Capability Graph[/bold cyan] "
        f"planes={int(counts.get('planes', 0) or 0)} "
        f"bridges={int(counts.get('bridges', 0) or 0)} "
        f"tools={int(counts.get('tools', 0) or 0)} "
        f"skills={int(counts.get('skills', 0) or 0)} "
        f"providers={int(counts.get('providers', 0) or 0)} "
        f"models={int(counts.get('models', 0) or 0)}"
    )
    model_plane = (planes.get("opencode_model_plane") or {}) if isinstance(planes, dict) else {}
    tool_plane = (planes.get("mcp_plane") or {}) if isinstance(planes, dict) else {}
    skill_plane = (planes.get("skill_plane") or {}) if isinstance(planes, dict) else {}

    workload_rows = list(model_plane.get("workloads") or [])
    if workload_rows:
        preview = ", ".join(
            f"{row.get('name')}->{row.get('provider')}"
            for row in workload_rows[:6]
        )
        console.print(f"[dim]model plane:[/dim] {preview}")

    tool_rows = list(tool_plane.get("tools") or [])
    if tool_rows:
        preview = ", ".join(str(row.get("name") or "") for row in tool_rows[:8])
        console.print(f"[dim]mcp/tool plane:[/dim] {preview}")

    skill_rows = list(skill_plane.get("skills") or [])
    if skill_rows:
        preview = ", ".join(str(row.get("name") or "") for row in skill_rows[:6])
        console.print(f"[dim]skill plane:[/dim] {preview}")

    if save_result:
        console.print(f"[dim]sparat:[/dim] {save_result.get('path')}")
    if field_result:
        console.print(
            "[dim]"
            f"indexed_to_field: anchor={field_result.get('anchor')} "
            f"nodes={int(field_result.get('nodes_touched', 0) or 0)} "
            f"relations={int(field_result.get('relations_touched', 0) or 0)}"
            "[/dim]"
        )

    if route_result:
        chosen_skill = route_result.get("chosen_skill") if isinstance(route_result.get("chosen_skill"), dict) else {}
        workload = route_result.get("workload") if isinstance(route_result.get("workload"), dict) else {}
        governance = route_result.get("governance") if isinstance(route_result.get("governance"), dict) else {}
        top_candidates = route_result.get("top_skill_candidates") if isinstance(route_result.get("top_skill_candidates"), list) else []
        tool_preview = ", ".join(str(x) for x in (chosen_skill.get("tools") or [])[:8]) or "-"
        candidate_preview = ", ".join(
            f"{row.get('name')}:{float(row.get('score', 0.0) or 0.0):.2f}"
            for row in top_candidates[:3]
        )
        console.print("")
        console.print(f"[bold]Route[/bold] {route}")
        console.print(
            f"[green]skill:[/green] {chosen_skill.get('name', '-')} "
            f"(score={float(route_result.get('skill_score', 0.0) or 0.0):.2f})"
        )
        console.print(f"[dim]reasons:[/dim] {', '.join(route_result.get('skill_reasons') or [])}")
        console.print(
            f"[dim]workload:[/dim] {workload.get('name', '-')} "
            f"provider={workload.get('provider', '-')} "
            f"candidates={', '.join(workload.get('candidates') or []) or '-'}"
        )
        console.print(f"[dim]tools:[/dim] {tool_preview}")
        console.print(f"[dim]governance:[/dim] {governance.get('name', '-')}")
        if candidate_preview:
            console.print(f"[dim]top skill candidates:[/dim] {candidate_preview}")


@app.command(name="memory-audit")
def memory_audit_cmd(
    limit: int = typer.Option(20, "--limit", "-l", help="Antal unconsolidated att visa"),
) -> None:
    import nouse.client as client
    from nouse.memory.store import MemoryStore

    safe_limit = max(1, min(limit, 5000))
    if client.daemon_running():
        try:
            audit = client.get_memory_audit(limit=safe_limit)
        except Exception:
            audit = MemoryStore().audit(limit=safe_limit)
    else:
        audit = MemoryStore().audit(limit=safe_limit)

    console.print(
        f"[bold cyan]Memory Audit[/bold cyan] "
        f"episodes={int(audit.get('episodes_total', 0) or 0)} "
        f"unconsolidated={int(audit.get('unconsolidated_total', 0) or 0)} "
        f"working={int(audit.get('working_items', 0) or 0)} "
        f"facts={int(audit.get('semantic_facts', 0) or 0)}"
    )

    preview = audit.get("unconsolidated_preview") or []
    for row in preview:
        console.print(
            f"- [yellow]{row.get('id', '?')}[/yellow] "
            f"[dim]{row.get('source', '?')} · domain={row.get('domain_hint', '?')} · "
            f"rels={int(row.get('relation_count', 0) or 0)} · ts={row.get('ts', '')}[/dim]"
        )


@app.command(name="consolidation-run")
def consolidation_run_cmd(
    max_episodes: int = typer.Option(40, "--max-episodes", "-m", help="Max antal episoder"),
    strict_min_evidence: float = typer.Option(0.65, "--min-evidence", help="Min evidence-score"),
) -> None:
    import nouse.client as client
    from nouse.field.surface import FieldSurface
    from nouse.memory.store import MemoryStore

    if client.daemon_running():
        try:
            result = client.post_memory_consolidate(
                max_episodes=max(1, int(max_episodes)),
                strict_min_evidence=max(0.0, min(1.0, float(strict_min_evidence))),
            )
            console.print_json(data=result)
            return
        except Exception:
            pass

    field = FieldSurface()
    result = MemoryStore().consolidate(
        field,
        max_episodes=max(1, int(max_episodes)),
        strict_min_evidence=max(0.0, min(1.0, float(strict_min_evidence))),
    )
    console.print_json(data=result)


@app.command(name="mcp")
def mcp_cmd(
    action: str = typer.Argument("serve", help="serve | serve-http"),
) -> None:
    from nouse.mcp_gateway import server as mcp_server

    act = str(action or "serve").strip().lower()
    if act in {"serve", "stdio"}:
        mcp_server.run_stdio()
        return
    if act in {"serve-http", "http"}:
        mcp_server.run_http()
        return

    console.print("[red]Ogiltig action.[/red] Använd: serve | serve-http")
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
