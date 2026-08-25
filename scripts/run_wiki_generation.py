"""
run_wiki_generation.py -- one-shot manual trigger for the wiki layer.

Not wired into NightRun yet (see STATUS.md 2026-08-25) -- this is the
explicit, Björn-approved manual run against the live graph, read-only
FieldSurface access only. Prints progress and a final summary; a
non-zero exit code means something raised outside the per-concept
try/except blocks already inside wiki_generator.py.
"""
from __future__ import annotations

import sys
import time
import traceback

sys.path.insert(0, "src")

from nouse.field.surface import FieldSurface
from nouse.daemon.wiki_generator import generate_wiki_pages, generate_wiki_index, wiki_dir


def main() -> int:
    t0 = time.monotonic()
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] start, wiki_dir={wiki_dir()}", flush=True)

    field = FieldSurface(db_path="/home/bjornwikstrom/.local/share/nouse/field.sqlite", read_only=True)

    try:
        pages_result = generate_wiki_pages(field)
        print(f"generate_wiki_pages: {pages_result}", flush=True)
    except Exception:
        print("generate_wiki_pages RAISED (unexpected -- everything inside it is meant to be caught):", flush=True)
        traceback.print_exc()
        return 1

    try:
        index_result = generate_wiki_index(field)
        print(f"generate_wiki_index: {index_result}", flush=True)
    except Exception:
        print("generate_wiki_index RAISED (unexpected):", flush=True)
        traceback.print_exc()
        return 1

    dt = time.monotonic() - t0
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] done in {dt:.1f}s", flush=True)

    # Sanity checks worth flagging even though the run itself "succeeded" --
    # these would indicate the real numbers drifted from what was verified
    # in STATUS.md before this run started, worth a human look either way.
    if pages_result["generated"] == 0:
        print("ANOMALY: 0 pages generated -- expected several thousand.", flush=True)
    if abs(pages_result["generated"] - index_result["indexed"]) > pages_result["generated"] * 0.5:
        print("ANOMALY: generated count and indexed count diverge by >50% -- "
              f"generated={pages_result['generated']} indexed={index_result['indexed']}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
