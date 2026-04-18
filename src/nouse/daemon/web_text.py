from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from nouse.daemon.file_text import extract_text


def is_url(value: str) -> bool:
    try:
        p = urllib.parse.urlparse(value)
        return p.scheme in {"http", "https"} and bool(p.netloc)
    except Exception:
        return False


def _collect_meta_content(soup: BeautifulSoup) -> dict[str, str]:
    out: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        try:
            attrs = dict(tag.attrs or {})
        except Exception:
            continue
        content_raw = attrs.get("content")
        content = str(content_raw or "").strip()
        if not content:
            continue
        for key in ("name", "property", "itemprop"):
            raw = attrs.get(key)
            meta_key = str(raw or "").strip().lower()
            if meta_key and meta_key not in out:
                out[meta_key] = content
    return out


def _first_nonempty(values: list[str]) -> str:
    for value in values:
        clean = str(value or "").strip()
        if clean:
            return clean
    return ""


def _collect_jsonld_objects(soup: BeautifulSoup) -> list[dict]:
    rows: list[dict] = []
    scripts = soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.IGNORECASE)})
    for tag in scripts:
        raw = str(tag.string or tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        stack = [payload]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                rows.append(current)
                graph = current.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
            elif isinstance(current, list):
                stack.extend(current)
    return rows


def _jsonld_author_name(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("name") or "").strip()
    if isinstance(value, list):
        for item in value:
            name = _jsonld_author_name(item)
            if name:
                return name
    return ""


def _extract_jsonld_fields(rows: list[dict]) -> dict[str, str]:
    title = ""
    author = ""
    published = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not title:
            title = str(
                row.get("headline")
                or row.get("name")
                or row.get("title")
                or ""
            ).strip()
        if not author:
            author = _jsonld_author_name(row.get("author"))
        if not published:
            published = str(
                row.get("datePublished")
                or row.get("dateCreated")
                or row.get("dateModified")
                or ""
            ).strip()
        if title and author and published:
            break
    out: dict[str, str] = {}
    if title:
        out["title"] = title
    if author:
        out["author"] = author
    if published:
        out["published_at"] = published
    return out


def extract_text_from_url(url: str, timeout_s: float = 45.0) -> tuple[str, dict]:
    if _is_youtube(url):
        text, meta = _extract_youtube_text(url, timeout_s=timeout_s)
        if text.strip():
            return text, meta

    with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()

    ctype = (r.headers.get("content-type") or "").lower()
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(r.content)
            tmp_path = Path(tmp.name)
        try:
            text = extract_text(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
        return text, {"source": "web_pdf", "url": url}

    soup = BeautifulSoup(r.text, "lxml")
    meta_content = _collect_meta_content(soup)
    jsonld_fields = _extract_jsonld_fields(_collect_jsonld_objects(soup))
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    title = _first_nonempty(
        [
            (soup.title.string if soup.title and soup.title.string else ""),
            meta_content.get("og:title", ""),
            meta_content.get("twitter:title", ""),
            meta_content.get("headline", ""),
            jsonld_fields.get("title", ""),
        ]
    )
    author = _first_nonempty(
        [
            meta_content.get("author", ""),
            meta_content.get("article:author", ""),
            meta_content.get("og:article:author", ""),
            meta_content.get("parsely-author", ""),
            meta_content.get("twitter:creator", ""),
            jsonld_fields.get("author", ""),
        ]
    )
    published = _first_nonempty(
        [
            meta_content.get("article:published_time", ""),
            meta_content.get("og:published_time", ""),
            meta_content.get("datepublished", ""),
            meta_content.get("pubdate", ""),
            meta_content.get("parsely-pub-date", ""),
            meta_content.get("date", ""),
            jsonld_fields.get("published_at", ""),
        ]
    )

    body = "\n".join(s.strip() for s in soup.stripped_strings if s.strip())
    header_lines = ["Web article" + (f": {title}" if title else "")]
    if author:
        header_lines.append(f"Author: {author}")
    if published:
        header_lines.append(f"Published: {published}")
    header_lines.append(f"URL: {url}")

    header = "\n".join(header_lines).strip()
    text = f"{header}\n\n{body}".strip() if body else header
    meta = {"source": "web_article", "url": url, "title": title}
    if author:
        meta["author"] = author
    if published:
        meta["published_at"] = published
    return text, meta


def _is_youtube(url: str) -> bool:
    host = (urllib.parse.urlparse(url).netloc or "").lower()
    return "youtube.com" in host or "youtu.be" in host


def _extract_video_id(url: str) -> str | None:
    p = urllib.parse.urlparse(url)
    host = (p.netloc or "").lower()
    if "youtu.be" in host:
        vid = p.path.strip("/")
        return vid or None
    if "youtube.com" in host:
        qs = urllib.parse.parse_qs(p.query)
        if qs.get("v"):
            return qs["v"][0]
        parts = [x for x in p.path.split("/") if x]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed"}:
            return parts[1]
    return None


def _parse_vtt_text(raw: str) -> str:
    parts: list[str] = []
    for line in raw.splitlines():
        l = line.strip()
        if not l:
            continue
        if l.startswith("WEBVTT"):
            continue
        if "-->" in l:
            continue
        if re.fullmatch(r"\d+", l):
            continue
        if l.startswith("NOTE"):
            continue
        cleaned = re.sub(r"<[^>]+>", "", l).strip()
        if cleaned:
            decoded = html.unescape(cleaned)
            if not parts or decoded != parts[-1]:
                parts.append(decoded)
    return "\n".join(parts)


def _extract_youtube_text_via_ytdlp(url: str, vid: str) -> tuple[str, str]:
    # shutil.which respekterar aktuellt PATH — om nouse kör under en annan Python-version
    # (t.ex. 3.13) kanske yt-dlp bara finns i pyenv-shims eller en annan venv.
    # Direkta sökvägar prioriteras framför pyenv-shims (shims misslyckas om aktiv
    # Python-version inte har yt-dlp installerat).
    _YTDLP_CANDIDATES = [
        os.path.expanduser("~/.pyenv/versions/3.11.11/bin/yt-dlp"),
        os.path.expanduser("~/.local/bin/yt-dlp"),
        "/usr/local/bin/yt-dlp",
        "/usr/bin/yt-dlp",
    ]
    ytdlp = next((p for p in _YTDLP_CANDIDATES if os.path.isfile(p)), None)
    # Sista utväg: låt PATH avgöra (funkar om shim matchar aktiv Python-version)
    if not ytdlp:
        ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        return "", "yt_dlp_missing"

    with tempfile.TemporaryDirectory(prefix="b76_yt_") as td:
        out_tmpl = str(Path(td) / "%(id)s.%(ext)s")
        cmd = [
            ytdlp,
            "--skip-download",
            "--write-auto-sub",
            "--write-sub",
            "--sub-langs",
            "en,en-orig,en-US",
            "--sub-format",
            "vtt",
            "--no-abort-on-error",
            "-o",
            out_tmpl,
            url,
        ]

        try:
            subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=90,
            )
        except Exception:
            return "", "yt_dlp_exec_error"

        candidates = list(Path(td).glob(f"{vid}*.vtt")) + list(Path(td).glob("*.vtt"))
        for c in candidates:
            try:
                raw = c.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            parsed = _parse_vtt_text(raw)
            if len(parsed.strip()) >= 80:
                return parsed, "yt_dlp_vtt"

    return "", "yt_dlp_no_subtitles"


def _extract_youtube_text(url: str, timeout_s: float = 45.0) -> tuple[str, dict]:
    vid = _extract_video_id(url)
    if not vid:
        return "", {"source": "youtube", "url": url, "extract_reason": "invalid_video_id"}

    title = ""
    author = ""
    captions_text = ""
    extract_reason = ""

    with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
        try:
            oembed = client.get(
                "https://www.youtube.com/oembed",
                params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"},
            )
            if oembed.is_success:
                od = oembed.json()
                title = str(od.get("title") or "")
                author = str(od.get("author_name") or "")
        except Exception:
            pass

        for lang in ("sv", "en"):
            try:
                cap = client.get(
                    "https://www.youtube.com/api/timedtext",
                    params={"v": vid, "lang": lang},
                )
                if not cap.is_success or not cap.text.strip():
                    continue
                root = ET.fromstring(cap.text)
                parts: list[str] = []
                for node in root.findall("text"):
                    raw = "".join(node.itertext())
                    val = html.unescape(raw).strip()
                    if val:
                        parts.append(val)
                if parts:
                    captions_text = "\n".join(parts)
                    extract_reason = f"timedtext_{lang}"
                    break
            except Exception:
                continue

    if not captions_text:
        captions_text, extract_reason = _extract_youtube_text_via_ytdlp(url, vid)

    header = f"YouTube video: {title}\nKanal: {author}\nURL: {url}\n"
    if captions_text:
        src_tag = "youtube_transcript_ytdlp" if extract_reason.startswith("yt_dlp") else "youtube_transcript"
        return f"{header}\nTranscript:\n{captions_text}", {
            "source": src_tag,
            "url": url,
            "video_id": vid,
            "title": title,
            "extract_reason": extract_reason or "ok",
        }

    return f"{header}\n(Transcript kunde inte hämtas.)", {
        "source": "youtube_meta",
        "url": url,
        "video_id": vid,
        "title": title,
        "extract_reason": extract_reason or "timedtext_empty",
    }
