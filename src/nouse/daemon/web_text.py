from __future__ import annotations

import html
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
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    title = (soup.title.string or "").strip() if soup.title else ""
    body = "\n".join(s.strip() for s in soup.stripped_strings if s.strip())
    text = f"Web article: {title}\n\n{body}" if title else body
    return text, {"source": "web_article", "url": url, "title": title}


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
    if not shutil.which("yt-dlp"):
        return "", "yt_dlp_missing"

    with tempfile.TemporaryDirectory(prefix="b76_yt_") as td:
        out_tmpl = str(Path(td) / "%(id)s.%(ext)s")
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--write-auto-sub",
            "--write-sub",
            "--sub-langs",
            "en,sv,en.*,sv.*",
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
                stderr=subprocess.DEVNULL,
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
