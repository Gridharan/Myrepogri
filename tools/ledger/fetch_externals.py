#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Fetch every external named in the upstream ``download.lst``.

Purpose: the licence ledger must record the licence *read from the file*
inside each third-party archive, so the archives have to be present
locally.  Each file is verified against the SHA-256 that upstream pins
in ``download.lst``.  Safe to re-run: verified files are not re-fetched.

Usage (from the repository root)::

    python3 -m tools.ledger.fetch_externals \
        --download-lst <upstream>/download.lst --dest <dir>

Exit codes: 0 all present and verified; 2 bad input; 3 at least one
network failure; 4 at least one checksum mismatch (takes precedence).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Sequence

from tools.common.jsonlog import JsonlLogger, default_log_dir, new_run_id
from tools.common.netfetch import ChecksumMismatch, FetchError, fetch_verified
from tools.ledger.download_lst import UPSTREAM_BASE, DownloadLstError, External, load

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NETWORK = 3
EXIT_CHECKSUM = 4

REPO_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--download-lst", required=True, type=Path)
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--base-url", default=UPSTREAM_BASE)
    parser.add_argument("--only", nargs="*", default=[], metavar="KEY",
                        help="restrict to these variable prefixes, e.g. BOOST ZLIB")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=300.0,
                        help="socket timeout per request, seconds")
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--summary", type=Path, default=None,
                        help="write a JSON summary to this path")
    parser.add_argument("--run-id", default=None)
    return parser


def _fetch_one(item: External, dest: Path, timeout: float, retries: int) -> dict:
    started = time.monotonic()
    row = {"key": item.key, "variable": item.variable, "filename": item.filename,
           "url": item.url, "sha256": item.sha256}
    if not item.fetchable:
        row.update(status="no-url", error="Makefile.fetch defines no base URL for this kind")
    else:
        try:
            result = fetch_verified(item.url, dest / item.filename, item.sha256,
                                    timeout=timeout, retries=retries)
            row.update(status=result.status, size=result.size, attempts=result.attempts)
        except ChecksumMismatch as exc:
            row.update(status="checksum-mismatch", error=str(exc), actual_sha256=exc.actual)
        except FetchError as exc:
            row.update(status="network-error", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - one item must not abort the whole run
            row.update(status="network-error", error=f"{type(exc).__name__}: {exc}")
    row["duration_ms"] = int((time.monotonic() - started) * 1000)
    return row


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.jobs < 1 or args.jobs > 16:
        print("error: --jobs must be between 1 and 16", file=sys.stderr)
        return EXIT_USAGE
    if args.retries < 0 or args.retries > 10:
        print("error: --retries must be between 0 and 10", file=sys.stderr)
        return EXIT_USAGE
    if args.timeout <= 0:
        print("error: --timeout must be > 0", file=sys.stderr)
        return EXIT_USAGE
    if not args.download_lst.is_file():
        print(f"error: not a file: {args.download_lst}", file=sys.stderr)
        return EXIT_USAGE
    try:
        items: List[External] = load(args.download_lst, base_url=args.base_url)
    except (DownloadLstError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.only:
        wanted = set(args.only)
        unknown = sorted(wanted - {item.key for item in items})
        if unknown:
            print(f"error: unknown key(s): {', '.join(unknown)}", file=sys.stderr)
            return EXIT_USAGE
        items = [item for item in items if item.key in wanted]

    run_id = args.run_id or new_run_id()
    log = JsonlLogger(default_log_dir(REPO_ROOT) / f"fetch-externals-{run_id}.jsonl",
                      phase="phase0", run_id=run_id)
    log.log("start", count=len(items), dest=str(args.dest), download_lst=str(args.download_lst))
    args.dest.mkdir(parents=True, exist_ok=True)

    rows: List[dict] = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(_fetch_one, item, args.dest, args.timeout, args.retries)
                   for item in items]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            ok = row["status"] in ("downloaded", "cached")
            log.log("fetch", result="ok" if ok else "fail",
                    level="INFO" if ok else "ERROR", duration_ms=row["duration_ms"],
                    **{k: v for k, v in row.items() if k != "duration_ms"})

    rows.sort(key=lambda row: row["variable"])
    counts: dict = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    summary = {"run_id": run_id, "download_lst": str(args.download_lst),
               "base_url": args.base_url, "total": len(rows), "by_status": counts,
               "duration_ms": int((time.monotonic() - started) * 1000), "items": rows}
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    if counts.get("checksum-mismatch"):
        code = EXIT_CHECKSUM
    elif counts.get("network-error") or counts.get("no-url"):
        code = EXIT_NETWORK
    else:
        code = EXIT_OK
    log.log("finish", result="ok" if code == EXIT_OK else "fail",
            level="INFO" if code == EXIT_OK else "ERROR",
            duration_ms=summary["duration_ms"], exit_code=code, by_status=counts)
    print(json.dumps({"run_id": run_id, "total": len(rows), "by_status": counts,
                      "exit_code": code, "log": str(log.path)}))
    return code


if __name__ == "__main__":
    sys.exit(run())
