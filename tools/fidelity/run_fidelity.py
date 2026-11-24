#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Fidelity harness: run every corpus file through an office engine.

Per file (see ``uno_worker.py`` for the engine side): open, measure,
export to PDF, save again in the format it was loaded with, reopen,
measure again; then compare here (document model, package structure,
PDF page count) and assign ``pass`` / ``partial`` / ``fail``.

Usage (from the repository root)::

    python3 -m tools.fidelity.run_fidelity \
        --engine-home <dir containing program/soffice> \
        --upstream-tree <pinned upstream checkout> \
        --manifest corpus/MANIFEST.csv

Environment defaults (docs/CONFIG.md): ``SUITE_ENGINE_HOME``,
``SUITE_UPSTREAM_TREE``, ``SUITE_WORK_DIR``, ``SUITE_LOG_DIR``.

Exit codes: 0 run completed (document verdicts are data, not errors);
2 bad input; 3 engine unusable; 4 manifest or provenance error;
6 pass rate below the supplied baseline (``--baseline``).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from tools.common.jsonlog import JsonlLogger, default_log_dir, new_run_id
from tools.common.metrics import update_metrics
from tools.common.netfetch import sha256_file
from tools.corpus.manifest import Entry, ManifestError, load_manifest, verify_entry
from tools.fidelity import compare, pkgdiff
from tools.fidelity.report import write_html

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_ENGINE = 3
EXIT_MANIFEST = 4
EXIT_BELOW_BASELINE = 6

SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).resolve().parent / "uno_worker.py"
_BUILDID_RE = re.compile(r"^buildid=([0-9a-f]{7,64})\s*$", re.M)


class EngineError(Exception):
    """The engine installation cannot be used."""


def engine_identity(engine_home: Path, scratch: Path) -> Dict[str, str]:
    """Describe the engine: executables, build id and reported version."""
    program = engine_home / "program"
    soffice = program / "soffice"
    python = program / "python"
    for path in (soffice, python):
        if not path.is_file():
            raise EngineError(f"not found: {path}")
    versionrc = program / "versionrc"
    buildid = ""
    if versionrc.is_file():
        match = _BUILDID_RE.search(versionrc.read_text(encoding="utf-8", errors="replace"))
        buildid = match.group(1) if match else ""
    profile = scratch / "version-profile"
    profile.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [str(soffice), "--headless", f"-env:UserInstallation={profile.as_uri()}",
             "--version"],
            capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EngineError(f"cannot run {soffice}: {exc}") from exc
    version_line = (completed.stdout or "").strip().splitlines()[:1]
    if completed.returncode != 0 or not version_line:
        raise EngineError(f"{soffice} --version failed with code {completed.returncode}")
    return {"home": str(engine_home), "soffice": str(soffice), "python": str(python),
            "buildid": buildid, "version": version_line[0]}


def _inside(child: Path, parent: Path) -> bool:
    child, parent = child.resolve(), parent.resolve()
    return parent == child or parent in child.parents


def _remove_tree(path: Path, work_root: Path) -> None:
    """Delete a scratch directory, refusing anything outside the work root."""
    if path.exists() and _inside(path, work_root) and path.resolve() != work_root.resolve():
        shutil.rmtree(path, ignore_errors=True)


def run_worker(engine: Dict[str, str], source: Path, workdir: Path, password: str,
               timeout: float) -> Dict[str, Any]:
    """Run the probe for one file in its own process group."""
    workdir.mkdir(parents=True, exist_ok=True)
    request = {"input": str(source), "workdir": str(workdir / "w"),
               "result": str(workdir / "worker-result.json"), "soffice": engine["soffice"]}
    if password:
        request["password"] = password
    request_path = workdir / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    result_path = Path(request["result"])
    result_path.unlink(missing_ok=True)

    started = time.monotonic()
    timed_out = False
    exit_code: Optional[int] = None
    with (workdir / "worker.log").open("ab") as log:
        process = subprocess.Popen(
            [engine["python"], str(WORKER), "--request", str(request_path)],
            stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # The engine is a child of the worker: always sweep the whole group.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            if timed_out:
                process.wait(timeout=30)
    worker: Optional[Dict[str, Any]] = None
    if result_path.is_file():
        try:
            worker = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            worker = None
    return {"worker": worker, "timed_out": timed_out, "exit_code": exit_code,
            "duration_ms": int((time.monotonic() - started) * 1000)}


def evaluate(entry: Entry, source: Path, run: Dict[str, Any]) -> Dict[str, Any]:
    """Combine probe output with file-level checks into one report row."""
    worker = run["worker"]
    outputs = (worker or {}).get("outputs", {})
    pdf_path = outputs.get("pdf")
    roundtrip = outputs.get("roundtrip")

    pdf_valid: Optional[bool] = None
    pdf_pages: Optional[int] = None
    if pdf_path:
        pdf = Path(pdf_path)
        pdf_valid = pdf.is_file() and pdf.stat().st_size > 0 and \
            pdf.read_bytes()[:5] == b"%PDF-"
        if pdf_valid:
            pdf_pages = pkgdiff.pdf_page_count(pdf)

    package: Dict[str, Any] = {}
    package_diff: Optional[Dict[str, Any]] = None
    if pkgdiff.is_zip_package(source):
        try:
            before = pkgdiff.inspect_package(source)
            package["before"] = before
            if roundtrip and pkgdiff.is_zip_package(Path(roundtrip)):
                after = pkgdiff.inspect_package(Path(roundtrip))
                package["after"] = after
                package_diff = pkgdiff.diff_inventories(before, after)
        except pkgdiff.PackageError as exc:
            package["error"] = str(exc)

    verdict = compare.classify(worker, package_diff, pdf_pages, pdf_valid,
                               timed_out=run["timed_out"], worker_exit=run["exit_code"])
    before_model = (worker or {}).get("before") or {}
    after_model = (worker or {}).get("after") or {}
    steps = {name: {"ok": bool(step.get("ok")), "duration_ms": step.get("duration_ms", 0),
                    **({"error": step["error"]} if step.get("error") else {})}
             for name, step in ((worker or {}).get("steps") or {}).items()}
    fonts_model = before_model.get("metrics", {}).get("fonts", [])
    fonts_package = package.get("before", {}).get("fonts", [])
    return {
        "id": entry.id, "path": entry.path, "source": entry.source, "format": entry.format,
        "app": entry.app, "features": list(entry.features), "sha256": entry.sha256,
        "status": verdict["status"], "reasons": verdict["reasons"], "info": verdict["info"],
        "import_filter": (worker or {}).get("import_filter", ""),
        "kind": before_model.get("kind", ""),
        "units_before": before_model.get("unit_count"),
        "units_after": after_model.get("unit_count"),
        "pdf_pages": pdf_pages,
        "critical_diffs": verdict["critical_diffs"], "info_diffs": verdict["info_diffs"],
        "package_diff": package_diff, "package_error": package.get("error", ""),
        "package_before": package.get("before"),
        "metrics_before": before_model.get("metrics"),
        "fonts": sorted(set(fonts_model) | set(fonts_package)),
        "steps": steps, "timed_out": run["timed_out"], "worker_exit": run["exit_code"],
        "duration_ms": run["duration_ms"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    env = os.environ.get
    parser.add_argument("--manifest", type=Path, default=REPO_ROOT / "corpus" / "MANIFEST.csv")
    parser.add_argument("--engine-home", type=Path,
                        default=Path(env("SUITE_ENGINE_HOME")) if env("SUITE_ENGINE_HOME") else None)
    parser.add_argument("--upstream-tree", type=Path,
                        default=Path(env("SUITE_UPSTREAM_TREE")) if env("SUITE_UPSTREAM_TREE") else None)
    parser.add_argument("--work-dir", type=Path,
                        default=Path(env("SUITE_WORK_DIR") or REPO_ROOT / "work"))
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "reports" / "fidelity.json")
    parser.add_argument("--html", type=Path, default=REPO_ROOT / "reports" / "fidelity.html")
    parser.add_argument("--metrics", type=Path,
                        default=REPO_ROOT / "reports" / "build-metrics.json")
    parser.add_argument("--label", default="baseline",
                        help="name of this run in the report, e.g. baseline or product")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=240.0,
                        help="hard limit per document, seconds")
    parser.add_argument("--only", nargs="*", default=[], metavar="ID")
    parser.add_argument("--resume", action="store_true",
                        help="reuse per-file results of an earlier run with the same engine")
    parser.add_argument("--keep-outputs", action="store_true",
                        help="keep exported PDFs and round-trip files in the work dir")
    parser.add_argument("--baseline", type=Path, default=None,
                        help="earlier fidelity.json; exit 6 if the pass rate is lower")
    parser.add_argument("--run-id", default=None)
    return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.engine_home is None:
        print("error: --engine-home (or SUITE_ENGINE_HOME) is required", file=sys.stderr)
        return EXIT_USAGE
    if not 1 <= args.jobs <= 16:
        print("error: --jobs must be between 1 and 16", file=sys.stderr)
        return EXIT_USAGE
    if not 10 <= args.timeout <= 3600:
        print("error: --timeout must be between 10 and 3600 seconds", file=sys.stderr)
        return EXIT_USAGE
    if not re.match(r"^[a-z0-9][a-z0-9-]{0,31}$", args.label):
        print("error: --label must match [a-z0-9-]{1,32}", file=sys.stderr)
        return EXIT_USAGE
    if not args.manifest.is_file():
        print(f"error: manifest not found: {args.manifest}", file=sys.stderr)
        return EXIT_USAGE
    baseline_rate: Optional[float] = None
    if args.baseline is not None:
        try:
            baseline_rate = float(json.loads(
                args.baseline.read_text(encoding="utf-8"))["summary"]["pass_rate"])
        except (OSError, KeyError, TypeError, ValueError) as exc:
            print(f"error: unusable baseline {args.baseline}: {exc}", file=sys.stderr)
            return EXIT_USAGE

    run_id = args.run_id or new_run_id()
    log = JsonlLogger(default_log_dir(REPO_ROOT) / f"fidelity-{run_id}.jsonl",
                      phase="fidelity", run_id=run_id)
    work_root = args.work_dir / "fidelity"
    work_root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    try:
        with log.timed("engine_identity", engine_home=str(args.engine_home)) as ctx:
            engine = engine_identity(args.engine_home, work_root / "scratch")
            ctx.update(buildid=engine["buildid"], version=engine["version"])
    except EngineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ENGINE

    try:
        with log.timed("manifest", manifest=str(args.manifest)) as ctx:
            entries = load_manifest(args.manifest)
            if args.only:
                wanted = set(args.only)
                unknown = sorted(wanted - {entry.id for entry in entries})
                if unknown:
                    raise ManifestError(f"unknown id(s): {', '.join(unknown)}")
                entries = [entry for entry in entries if entry.id in wanted]
            sources = {entry.id: verify_entry(entry, REPO_ROOT, args.upstream_tree)
                       for entry in entries}
            ctx.update(entries=len(entries))
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_MANIFEST

    cache_tag = (engine["buildid"] or "nobuildid")[:16]

    def process(entry: Entry) -> Dict[str, Any]:
        workdir = work_root / "files" / f"{entry.id}-{entry.sha256[:12]}-{cache_tag}"
        cached = workdir / "row.json"
        if args.resume and cached.is_file():
            try:
                row = json.loads(cached.read_text(encoding="utf-8"))
                row["cached"] = True
                return row
            except (json.JSONDecodeError, OSError):
                pass
        _remove_tree(workdir, work_root)
        outcome = run_worker(engine, sources[entry.id], workdir, entry.password, args.timeout)
        row = evaluate(entry, sources[entry.id], outcome)
        row["cached"] = False
        cached.write_text(json.dumps(row, sort_keys=True), encoding="utf-8")
        _remove_tree(workdir / "w" / "profile", work_root)
        if not args.keep_outputs:
            _remove_tree(workdir / "w", work_root)
        return row

    rows: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(process, entry): entry for entry in entries}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                row = future.result()
            except Exception as exc:  # noqa: BLE001 - one file must not stop the run
                row = {"id": entry.id, "path": entry.path, "source": entry.source,
                       "format": entry.format, "app": entry.app,
                       "features": list(entry.features), "sha256": entry.sha256,
                       "status": "fail", "reasons": ["harness-error"],
                       "info": [f"{type(exc).__name__}: {exc}"], "duration_ms": 0,
                       "cached": False}
            rows.append(row)
            log.log("document", result="ok" if row["status"] == "pass" else
                    ("info" if row["status"] == "partial" else "fail"),
                    level="INFO" if row["status"] != "fail" else "WARN",
                    duration_ms=row.get("duration_ms", 0), id=row["id"],
                    status=row["status"], reasons=row.get("reasons", []),
                    cached=row.get("cached", False))

    rows.sort(key=lambda row: row["id"])
    summary = compare.summarise(rows)
    duration_ms = int((time.monotonic() - started) * 1000)
    report = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "label": args.label,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "engine": {"version": engine["version"], "buildid": engine["buildid"]},
        "platform": {"system": os.uname().sysname, "machine": os.uname().machine},
        "corpus": {"manifest": str(args.manifest.relative_to(REPO_ROOT))
                   if _inside(args.manifest, REPO_ROOT) else str(args.manifest),
                   "manifest_sha256": sha256_file(args.manifest), "files": len(rows)},
        "settings": {"timeout_s": args.timeout, "jobs": args.jobs,
                     "criteria_version": compare.CRITERIA_VERSION},
        "summary": summary,
        "duration_ms": duration_ms,
        "files": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    write_html(report, args.html)
    update_metrics(args.metrics, f"fidelity_{args.label}", {
        "run_id": run_id, "engine_buildid": engine["buildid"], "files": summary["total"],
        "pass": summary["pass"], "partial": summary["partial"], "fail": summary["fail"],
        "pass_rate": summary["pass_rate"], "duration_ms": duration_ms})

    code = EXIT_OK
    if baseline_rate is not None and (summary["pass_rate"] or 0.0) < baseline_rate:
        code = EXIT_BELOW_BASELINE
    log.log("finish", result="ok" if code == EXIT_OK else "fail",
            level="INFO" if code == EXIT_OK else "ERROR", duration_ms=duration_ms,
            exit_code=code, total=summary["total"], passed=summary["pass"],
            partial=summary["partial"], failed=summary["fail"],
            pass_rate=summary["pass_rate"], baseline_rate=baseline_rate)
    print(json.dumps({"run_id": run_id, "total": summary["total"], "pass": summary["pass"],
                      "partial": summary["partial"], "fail": summary["fail"],
                      "pass_rate": summary["pass_rate"], "report": str(args.out),
                      "html": str(args.html), "log": str(log.path), "exit_code": code}))
    return code


if __name__ == "__main__":
    sys.exit(run())
