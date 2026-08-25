"""
Sources — vad hjärnan lyssnar på
=================================
FileSource:         nya/ändrade filer på disk
ConversationSource: Claude Code-konversationssummaries

Alla sources returnerar (text, metadata)-tupler via read_new().
Staten sparas i ~/.local/share/nouse/source_state.json för att
undvika att samma fil processas två gånger.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator

from nouse.config.paths import path_from_env
from nouse.daemon.file_text import extract_text


def _state_file() -> Path:
    return path_from_env("NOUSE_SOURCE_STATE_FILE", "source_state.json")

DEFAULT_INGEST_EXTENSIONS = frozenset({".md", ".txt", ".py", ".pdf"})
DEFAULT_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        ".cache",
        "cache",
        "tmp",
        "temp",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".idea",
        ".vscode",
    }
)


def _load_state() -> dict:
    state_file = _state_file()
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {}


def _save_state(state: dict) -> None:
    state_file = _state_file()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2))


def is_path_excluded(
    path: Path,
    *,
    excluded_dir_names: Iterable[str] | None = None,
) -> bool:
    blocked = {
        d.strip().lower()
        for d in (excluded_dir_names or DEFAULT_EXCLUDED_DIR_NAMES)
        if d.strip()
    }
    return any(part.lower() in blocked for part in path.parts)


def iter_ingest_files(
    root: Path,
    *,
    extensions: Iterable[str] | None = None,
    excluded_dir_names: Iterable[str] | None = None,
) -> Iterator[Path]:
    ext = {e.lower() for e in (extensions or DEFAULT_INGEST_EXTENSIONS)}
    blocked = {
        d.strip().lower()
        for d in (excluded_dir_names or DEFAULT_EXCLUDED_DIR_NAMES)
        if d.strip()
    }
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ext:
            continue
        if is_path_excluded(path, excluded_dir_names=blocked):
            continue
        yield path


class FileSource:
    """Läser nya/ändrade filer i ett katalogträd."""

    def __init__(
        self,
        root: Path,
        extensions: list[str] | None = None,
        excluded_dir_names: Iterable[str] | None = None,
    ):
        self.root = root
        self.extensions = {e.lower() for e in (extensions or [".md", ".txt", ".py"])}
        self.excluded_dir_names = {
            d.strip().lower()
            for d in (excluded_dir_names or DEFAULT_EXCLUDED_DIR_NAMES)
            if d.strip()
        }
        self._state = _load_state()

    def read_new(self) -> Iterator[tuple[str, dict]]:
        _batch_count = 0
        for path in self.root.rglob("*"):
            if is_path_excluded(path, excluded_dir_names=self.excluded_dir_names):
                continue
            if path.suffix.lower() not in self.extensions:
                continue
            if not path.is_file():
                continue
            key = str(path)
            mtime = path.stat().st_mtime
            if self._state.get(key) == mtime:
                continue
            try:
                text = extract_text(path)
                if len(text.strip()) < 100:
                    continue
                yield text, {
                    "path": str(path),
                    "source": "file",
                    "domain_hint": _domain_from_path(path),
                    "scope_hint": scope_from_path(path),
                }
                self._state[key] = mtime
                _batch_count += 1
                if _batch_count % 50 == 0:
                    _save_state(self._state)
            except Exception:
                continue
        if _batch_count % 50 != 0:
            _save_state(self._state)


class ConversationSource:
    """Läser Claude Code-konversationssummaries från ~/.claude/projects/."""

    def __init__(self, root: Path):
        self.root = root
        self._state = _load_state()

    def read_new(self) -> Iterator[tuple[str, dict]]:
        _batch_count = 0
        for path in self.root.rglob("*.md"):
            if not path.is_file():
                continue
            key = str(path)
            mtime = path.stat().st_mtime
            if self._state.get(key) == mtime:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                if len(text.strip()) < 100:
                    continue
                yield text, {
                    "path": str(path),
                    "source": "conversation",
                    "domain_hint": "AI-forskning",
                }
                self._state[key] = mtime
                _batch_count += 1
                if _batch_count % 50 == 0:
                    _save_state(self._state)
            except Exception:
                continue
        if _batch_count % 50 != 0:
            _save_state(self._state)


class BashHistorySource:
    """
    Fångar nya bash-kommandon — terminal-aktivitet som lärningssignal.
    Hoppar över triviala kommandon (ls, cd, clear…).
    Levererar kommandobatchar som text till extraktorn.
    """

    _BORING = frozenset(
        {
            "ls",
            "cd",
            "clear",
            "exit",
            "pwd",
            "history",
            "echo",
            "man",
            "which",
            "help",
            "cat",
            "cp",
            "mv",
            "rm",
            "mkdir",
            "touch",
            "chmod",
            "sudo",
            "top",
            "htop",
            "ps",
            "kill",
        }
    )

    def __init__(self):
        self._hist = Path.home() / ".bash_history"
        self._state = _load_state()

    def read_new(self) -> Iterator[tuple[str, dict]]:
        if not self._hist.exists():
            return
        key = "__bash_history_pos__"
        last_pos = int(self._state.get(key, 0))
        lines = self._hist.read_text(errors="ignore").splitlines()
        new = lines[last_pos:]

        interesting = [
            l.strip()
            for l in new
            if l.strip() and not l.startswith("#") and l.split()[0] not in self._BORING
        ]
        if interesting:
            text = "Terminalsession — kommandon Björn kört:\n" + "\n".join(interesting[-60:])
            yield text, {"source": "bash_history", "domain_hint": "programmering"}

        self._state[key] = len(lines)
        _save_state(self._state)


class ChromeBookmarksSource:
    """
    Läser Chrome-bokmärken — vad Björn medvetet sparat är hög-signal.
    Kräver inget lösenord, filen är alltid läsbar.
    """

    def __init__(self):
        self._bm = Path.home() / ".config/google-chrome/Default/Bookmarks"
        self._state = _load_state()

    def read_new(self) -> Iterator[tuple[str, dict]]:
        if not self._bm.exists():
            return
        key = str(self._bm)
        mtime = self._bm.stat().st_mtime
        if self._state.get(key) == mtime:
            return

        data = json.loads(self._bm.read_text(encoding="utf-8"))
        bookmarks: list[dict] = []
        _flatten_bookmarks(data.get("roots", {}), bookmarks)

        if bookmarks:
            lines = [f"- {b['name']}: {b['url']}" for b in bookmarks[-200:] if b.get("url")]
            text = "Chrome-bokmärken (sidor Björn sparat):\n" + "\n".join(lines)
            yield text, {"source": "chrome_bookmarks", "domain_hint": "webbresearch"}

        self._state[key] = mtime
        _save_state(self._state)


def _flatten_bookmarks(node: object, out: list) -> None:
    if isinstance(node, dict):
        if node.get("type") == "url":
            out.append({"name": node.get("name", ""), "url": node.get("url", "")})
        for v in node.values():
            _flatten_bookmarks(v, out)
    elif isinstance(node, list):
        for item in node:
            _flatten_bookmarks(item, out)


class ChromeHistorySource:
    """
    Läser Chrome-webbhistorik (SQLite).
    Chrome låser filen — vi kopierar den och läser kopian.
    Filtrerar bort triviala navigerings-URLs, behåller sök-queries.
    """

    _SKIP = frozenset({"google.com/favicon", "chrome://", "chrome-extension://"})

    def __init__(self, max_entries: int = 100):
        self._hist = Path.home() / ".config/google-chrome/Default/History"
        self._state = _load_state()
        self._max = max_entries

    def read_new(self) -> Iterator[tuple[str, dict]]:
        if not self._hist.exists():
            return
        key = "__chrome_history_mtime__"
        mtime = self._hist.stat().st_mtime
        if self._state.get(key) == mtime:
            return

        import shutil
        import sqlite3
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            shutil.copy2(str(self._hist), tmp_path)
            con = sqlite3.connect(tmp_path)
            rows = con.execute(
                "SELECT url, title FROM urls ORDER BY last_visit_time DESC LIMIT ?",
                (self._max,),
            ).fetchall()
            con.close()
        except Exception:
            return
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        entries = [
            f"- {title or '(ingen titel)'}: {url}"
            for url, title in rows
            if not any(s in url for s in self._SKIP)
        ]
        if entries:
            text = "Chrome-webbhistorik (senast besökta sidor):\n" + "\n".join(entries)
            yield text, {"source": "chrome_history", "domain_hint": "webbresearch"}

        self._state[key] = mtime
        _save_state(self._state)


def capture_queue_dir() -> Path:
    return path_from_env("NOUSE_CAPTURE_QUEUE_DIR", "capture_queue")


class CaptureQueueSource:
    """
    Läser filer från capture_queue/ — skrivet dit av `cap`-shellfunktionen
    eller `b76 ingest` medan daemon kör.
    Tar bort filen efter inläsning (FIFO-kö).
    """

    def __init__(self):
        capture_queue_dir().mkdir(parents=True, exist_ok=True)

    def read_new(self) -> Iterator[tuple[str, dict]]:
        for path in sorted(capture_queue_dir().glob("*.txt")):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").strip()
                if len(text) >= 20:
                    yield text, {
                        "source": "capture",
                        "domain_hint": "övrigt",
                        "path": str(path),
                    }
                path.unlink()  # konsumerad
            except Exception:
                continue


def _domain_from_path(path: Path) -> str:
    """Gissa domän från sökvägen."""
    p = str(path).lower()
    if any(k in p for k in ["neuro", "brain", "kognit"]):
        return "neurovetenskap"
    if any(k in p for k in ["ekonomi", "finance", "market"]):
        return "ekonomi"
    if any(k in p for k in ["physik", "fysik", "quantum", "kvant"]):
        return "fysik"
    if any(k in p for k in ["math", "matematik", "algebra"]):
        return "matematik"
    # 2026-08-25 (Tududi-task "Nous — återstående nästa steg", subtask 1):
    # occipital_lobe i brain_atlas.py klassificerar via "perception" i sitt
    # domain_keywords, men ingen sökväg routades dit tidigare — Björns eget
    # perceptionsforskningsspann (PCPE, "Perceptual Coherence and Perceived
    # Exclusion") är det bekräftade källmaterialet. Måste stå FÖRE den
    # generella research/paper-regeln nedan, annars fångas PCPE-filer där
    # och blir "AI-forskning" i stället.
    if "pcpe" in p or "perceptual coherence and perceived exclusion" in p:
        return "perception"
    if any(k in p for k in ["bisociat", "research", "paper"]):
        return "AI-forskning"
    if any(k in p for k in ["bio", "svamp", "fungi"]):
        return "biologi"
    return "övrigt"


def scope_from_path(path: Path) -> str:
    """Gissa källgräns (Fas 2 steg 5, docs/NOUS_NEXT_GENERATION_PLAN.md) från
    sökvägen. Deterministisk och statisk — scope avgör vad som får lämna
    maskinen, så det avgörs INTE av LLM-extraktionen (som domain_hint är),
    utan av var filen faktiskt ligger i IIC-strukturen. Okänd sökväg →
    "general" (field.surface._normalize_scope faller ändå tillbaka dit)."""
    p = str(path).lower()
    if "halsa" in p or "hälsa" in p or "glp1" in p or "glp-1" in p:
        return "personal_health"
    if p.endswith("system/person.md") or (".claude/projects" in p and "/memory/" in p):
        return "user_model"
    if "/work/nous/" in p or "/nouse/" in p:
        return "nous_system"
    if "ljudanteckningar" in p or "voicenote" in p:
        return "voice_notes"
    if "library/research" in p or ("02_library" in p and "research" in p):
        return "research_plg"
    return "general"
