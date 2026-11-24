#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Build ``corpus/MANIFEST.csv`` from the three permitted sources.

* ``self-authored``: files written by ``tools.corpus.gen_seed`` (must be
  byte-identical to what the generator produces now);
* ``derived``: files listed in ``corpus/derived/DERIVED.json`` (made from
  self-authored files by an engine, see ``tools.corpus.derive``);
* ``upstream-test-file``: paths listed in ``corpus/upstream-selection.json``
  resolved against the pinned upstream tree.  These files are *not*
  copied into this repository; the manifest records path, tag and
  SHA-256 so the harness can verify it reads the same bytes.

Exit codes: 0 ok; 2 bad input; 4 a listed file is missing or a
self-authored file differs from the generator output.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from tools.common.netfetch import sha256_file
from tools.corpus import gen_seed
from tools.corpus.manifest import ManifestError, load_manifest, write_manifest

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_PROVENANCE = 4

REPO_ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_LICENCE = "NOASSERTION (ledger row corpus-upstream-test-documents)"
OWN_LICENCE = "MPL-2.0"
_TAG_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def slug(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def self_rows(self_dir: Path) -> List[Dict[str, str]]:
    produced = gen_seed.generate()
    rows = []
    for name, (_builder, app, tags) in sorted(gen_seed.CATALOGUE.items()):
        target = self_dir / name
        if not target.is_file() or target.read_bytes() != produced[name]:
            raise ManifestError(
                f"{target} is missing or differs from the generator output; "
                "run: python3 -m tools.corpus.gen_seed --out corpus/self")
        rows.append({
            "id": "self-" + slug(name), "path": target.relative_to(REPO_ROOT).as_posix(),
            "source": "self-authored", "origin": "tools/corpus/gen_seed.py",
            "sha256": sha256_file(target), "bytes": str(target.stat().st_size),
            "format": name.rsplit(".", 1)[1], "app": app, "features": tags,
            "licence": OWN_LICENCE, "password": "",
            "notes": "written from public format specifications"})
    return rows


def derived_rows(derived_dir: Path) -> List[Dict[str, str]]:
    index = derived_dir / "DERIVED.json"
    if not index.is_file():
        return []
    rows = []
    for item in json.loads(index.read_text(encoding="utf-8"))["files"]:
        target = derived_dir / item["name"]
        if not target.is_file() or sha256_file(target) != item["sha256"]:
            raise ManifestError(f"{target} is missing or differs from DERIVED.json")
        rows.append({
            "id": "derived-" + slug(item["name"]),
            "path": target.relative_to(REPO_ROOT).as_posix(), "source": "derived",
            "origin": f"{item['source_id']} via {item['engine']} filter '{item['filter']}'",
            "sha256": item["sha256"], "bytes": str(target.stat().st_size),
            "format": item["name"].rsplit(".", 1)[1], "app": item["app"],
            "features": item["features"], "licence": OWN_LICENCE, "password": "",
            "notes": "binary-format copy of a self-authored file"})
    return rows


def upstream_rows(selection: Path, tree: Path, tag: str, commit: str) -> List[Dict[str, str]]:
    document = json.loads(selection.read_text(encoding="utf-8"))
    rows = []
    seen = set()
    for item in document["files"]:
        relative = item["path"]
        target = (tree / relative).resolve()
        if tree.resolve() not in target.parents or not target.is_file():
            raise ManifestError(f"upstream file not found in the tree: {relative}")
        identifier = "up-" + slug(relative)[-58:].strip("-")
        if identifier in seen:
            raise ManifestError(f"id collision for {relative}")
        seen.add(identifier)
        producer = item.get("producer") or "unknown"
        rows.append({
            "id": identifier, "path": relative, "source": "upstream-test-file",
            "origin": f"{tag}@{commit}", "sha256": sha256_file(target),
            "bytes": str(target.stat().st_size), "format": item["format"], "app": item["app"],
            "features": ";".join(item["features"]), "licence": UPSTREAM_LICENCE,
            "password": "",
            "notes": f"producer: {producer}; feature evidence: {item['evidence']}"})
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--upstream-tree", required=True, type=Path)
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument("--upstream-commit", required=True)
    parser.add_argument("--selection", type=Path,
                        default=REPO_ROOT / "corpus" / "upstream-selection.json")
    parser.add_argument("--self-dir", type=Path, default=REPO_ROOT / "corpus" / "self")
    parser.add_argument("--derived-dir", type=Path, default=REPO_ROOT / "corpus" / "derived")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "corpus" / "MANIFEST.csv")
    return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.upstream_tree.is_dir():
        print(f"error: not a directory: {args.upstream_tree}", file=sys.stderr)
        return EXIT_USAGE
    if not _TAG_RE.match(args.upstream_tag) or not _COMMIT_RE.match(args.upstream_commit):
        print("error: bad --upstream-tag or --upstream-commit", file=sys.stderr)
        return EXIT_USAGE
    if not args.selection.is_file():
        print(f"error: selection not found: {args.selection}", file=sys.stderr)
        return EXIT_USAGE
    try:
        rows = (self_rows(args.self_dir) + derived_rows(args.derived_dir)
                + upstream_rows(args.selection, args.upstream_tree, args.upstream_tag,
                                args.upstream_commit))
        write_manifest(args.out, rows)
        entries = load_manifest(args.out)  # round-trip validation of what was written
    except (ManifestError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PROVENANCE
    by_source: Dict[str, int] = {}
    for entry in entries:
        by_source[entry.source] = by_source.get(entry.source, 0) + 1
    print(json.dumps({"entries": len(entries), "by_source": by_source, "out": str(args.out)}))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(run())
