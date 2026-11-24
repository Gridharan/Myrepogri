#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Make binary-format copies of self-authored corpus files.

The legacy binary formats (.doc, .ppt) cannot reasonably be written by
hand, so the seed corpus gets them by letting an engine convert our own
self-authored files.  The result is still entirely our content; the
conversion is recorded in ``corpus/derived/DERIVED.json`` (source file,
engine build, export filter, SHA-256).

Converted files are not byte-reproducible (they embed timestamps), so
this tool is run once per corpus revision and its output is committed.

Exit codes: 0 ok; 2 bad input; 3 engine failed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from tools.common.netfetch import sha256_file
from tools.fidelity.run_fidelity import EngineError, engine_identity, run_isolated

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_ENGINE = 3

REPO_ROOT = Path(__file__).resolve().parents[2]
#: (self-authored file, new extension, export filter, app, feature tags)
PLAN = (
    ("seed-basic.docx", "doc", "MS Word 97", "writer",
     "styles;lists;tables;merged-cells;hyperlinks;bookmarks;sections;columns"),
    ("seed-notes-headers.docx", "doc", "MS Word 97", "writer",
     "headers-footers;footnotes;endnotes;toc;fields"),
    ("seed-review.docx", "doc", "MS Word 97", "writer", "tracked-changes;comments"),
    ("seed-basic.pptx", "ppt", "MS PowerPoint 97", "impress",
     "masters-layouts;notes;transitions;animations;tables;images;hidden-slides"),
)


def run(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine-home", required=True, type=Path)
    parser.add_argument("--self-dir", type=Path, default=REPO_ROOT / "corpus" / "self")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "corpus" / "derived")
    args = parser.parse_args(argv)
    if not args.self_dir.is_dir():
        print(f"error: not a directory: {args.self_dir}", file=sys.stderr)
        return EXIT_USAGE

    with tempfile.TemporaryDirectory(prefix="derive-") as scratch_name:
        scratch = Path(scratch_name)
        try:
            engine = engine_identity(args.engine_home, scratch)
        except EngineError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ENGINE
        args.out.mkdir(parents=True, exist_ok=True)
        records = []
        for index, (source_name, extension, export_filter, app, tags) in enumerate(PLAN):
            source = args.self_dir / source_name
            if not source.is_file():
                print(f"error: missing {source}", file=sys.stderr)
                return EXIT_USAGE
            outdir = scratch / f"out-{index}"
            outdir.mkdir()
            command = [engine["soffice"], "--headless", "--norestore", "--nologo",
                       f"-env:UserInstallation={(scratch / 'profile').as_uri()}",
                       "--convert-to", f"{extension}:{export_filter}",
                       "--outdir", str(outdir), str(source)]
            try:
                completed = run_isolated(command, timeout=300)
            except (OSError, subprocess.TimeoutExpired) as exc:
                print(f"error: conversion of {source_name} failed: {exc}", file=sys.stderr)
                return EXIT_ENGINE
            produced = outdir / f"{source.stem}.{extension}"
            if completed.returncode != 0 or not produced.is_file() or \
                    produced.stat().st_size == 0:
                print(f"error: engine did not produce {produced.name}: "
                      f"{completed.stderr.strip()[:300]}", file=sys.stderr)
                return EXIT_ENGINE
            name = f"{source.stem}.from-{source.suffix.lstrip('.')}.{extension}"
            target = args.out / name
            shutil.copyfile(produced, target)
            records.append({
                "name": name, "sha256": sha256_file(target), "app": app, "features": tags,
                "source_id": "self-" + source_name.replace(".", "-"),
                "source_sha256": sha256_file(source), "filter": export_filter,
                "engine": f"{engine['version']}"})
        (args.out / "DERIVED.json").write_text(
            json.dumps({"files": records}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"derived": [record["name"] for record in records]}))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(run())
