#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Choose upstream test documents for the seed corpus, reproducibly.

The pinned upstream tree ships thousands of test documents.  This tool
picks a small, feature-diverse subset with a fixed algorithm so that the
choice can be audited and repeated:

1. candidates are files with a wanted extension below the given roots,
   excluding directories and names that mark deliberately broken input
   (``fail``, ``indeterminate``, ``crash``, ``fuzz``, ``CVE-`` ...);
2. zip-based formats are inspected with ``tools.fidelity.pkgdiff`` and
   tagged with the features their XML actually contains;
3. binary formats (.doc, .ppt, .rtf) cannot be inspected from public
   specifications cheaply, so they are tagged from words in the file
   name only (weak evidence, recorded as such);
4. per format, the file that fills most still-open feature slots is taken
   until every observed feature is covered ``--cover`` times or the quota
   is reached; a remaining quota is filled with the files that carry most
   features.  Ties prefer documents written by another producer than this
   engine, then smaller files, then path order.

Nothing is copied: the output is a JSON list of paths relative to the
upstream tree, which ``tools.corpus.build_manifest`` turns into manifest
rows with SHA-256 values.

Exit codes: 0 ok; 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from tools.fidelity import pkgdiff

EXIT_OK = 0
EXIT_USAGE = 2
ALGORITHM = "greedy-feature-cover/2"

#: extension -> (application, quota)
QUOTAS: Dict[str, Tuple[str, int]] = {
    "docx": ("writer", 26), "docm": ("writer", 3), "dotx": ("writer", 2), "doc": ("writer", 8),
    "rtf": ("writer", 6), "odt": ("writer", 6),
    "pptx": ("impress", 26), "pptm": ("impress", 2), "ppsx": ("impress", 2),
    "potx": ("impress", 2), "ppt": ("impress", 8), "odp": ("impress", 6),
}
ZIP_FORMATS = ("docx", "docm", "dotx", "odt", "pptx", "pptm", "ppsx", "potx", "odp")
DEFAULT_ROOTS = ("sw/qa", "sd/qa", "oox/qa")
MAX_BYTES = 1_500_000
MIN_BYTES = 600
_BAD_DIR = re.compile(r"(^|/)(fail|indeterminate|crash\w*|fuzz\w*|hang\w*|cve\w*|ofz\w*)(/|$)", re.I)
_BAD_NAME = re.compile(r"^(cve|ofz|crash|hang|forcepoint|edb-|fuzz|invalid|broken|corrupt)", re.I)
PROPRIETARY_FONTS = frozenset((
    "Calibri", "Calibri Light", "Cambria", "Cambria Math", "Candara", "Consolas", "Constantia",
    "Corbel", "Aptos", "Aptos Display", "Segoe UI", "Arial", "Arial Narrow", "Times New Roman",
    "Courier New", "Verdana", "Tahoma", "Georgia", "Trebuchet MS", "Comic Sans MS", "Impact",
    "Symbol", "Wingdings", "Webdings", "Century Gothic", "Book Antiqua", "Garamond",
))
#: feature tag -> words searched in the file name (binary formats only)
NAME_HINTS: Dict[str, Tuple[str, ...]] = {
    "tables": ("table", "tbl", "cell"), "comments": ("comment", "annotation", "postit"),
    "tracked-changes": ("redline", "track", "change"), "footnotes": ("footnote", "ftn"),
    "endnotes": ("endnote",), "headers-footers": ("header", "footer"),
    "toc": ("toc", "index"), "fields": ("field",), "images": ("image", "picture", "pict", "graphic"),
    "lists": ("list", "number", "bullet"), "sections": ("section", "column"),
    "textboxes": ("textbox", "frame", "shape"), "ole": ("ole", "object", "embed"),
    "charts": ("chart",), "vba": ("macro", "vba", "basic"), "hyperlinks": ("hyperlink", "link"),
    "bookmarks": ("bookmark",), "animations": ("anim", "effect"),
    "transitions": ("transition",), "notes": ("notes",), "masters-layouts": ("master", "layout"),
    "media": ("sound", "audio", "video", "media"), "groups": ("group",),
    "fonts": ("font",), "math": ("math", "formula", "equation"),
}


def is_candidate(relative: str, size: int) -> bool:
    name = relative.rsplit("/", 1)[-1]
    if not MIN_BYTES <= size <= MAX_BYTES:
        return False
    if _BAD_DIR.search(relative) or _BAD_NAME.match(name):
        return False
    return True


def producer(path: Path) -> str:
    """Application string from docProps/app.xml or meta.xml (best effort)."""
    try:
        with zipfile.ZipFile(path) as archive:
            for part, pattern in (("docProps/app.xml", rb"<Application>([^<]{0,80})<"),
                                  ("meta.xml", rb"<meta:generator>([^<]{0,120})<")):
                if part in archive.namelist():
                    with archive.open(part) as handle:
                        match = re.search(pattern, handle.read(200_000))
                    if match:
                        return match.group(1).decode("utf-8", "replace").strip()
    except (zipfile.BadZipFile, OSError, RuntimeError):
        return ""
    return ""


def features_from_inventory(inv: Dict[str, object], fmt: str) -> Set[str]:
    counts: Dict[str, int] = inv["element_counts"]  # type: ignore[assignment]
    kinds: Dict[str, int] = inv["part_kinds"]  # type: ignore[assignment]
    fonts = set(inv["fonts"])  # type: ignore[arg-type]
    tags: Set[str] = set()

    def has(*names: str) -> bool:
        return any(counts.get(name, 0) > 0 for name in names)

    def kind(*names: str) -> bool:
        return any(kinds.get(name, 0) > 0 for name in names)

    rules = (
        ("tables", has("w:tbl", "a:tbl", "table:table")),
        ("images", has("w:drawing", "w:pict", "p:pic", "draw:image") and kind("media")),
        ("headers-footers", kind("word-header", "word-footer")),
        ("footnotes", has("w:footnoteReference") or (fmt == "odt" and has("text:note"))),
        ("endnotes", has("w:endnoteReference")),
        ("toc", has("toc-field", "text:table-of-content")),
        ("tracked-changes", has("w:ins", "w:del", "w:moveFrom", "w:rPrChange", "w:pPrChange",
                                "text:changed-region")),
        ("comments", has("w:commentReference", "office:annotation") or kind("slide-comments")),
        ("lists", has("w:numPr", "text:list")),
        ("hyperlinks", has("w:hyperlink", "a:hlinkClick", "text:a")),
        ("bookmarks", has("w:bookmarkStart", "text:bookmark-start")),
        ("sections", counts.get("w:sectPr", 0) > 1 or has("text:section")),
        ("textboxes", has("w:txbxContent", "v:textbox", "draw:text-box") and fmt in
         ("docx", "docm", "dotx", "odt")),
        ("math", has("m:oMath")),
        ("content-controls", has("w:sdt")),
        ("fields", has("w:fldSimple", "w:fldChar")),
        ("charts", kind("chart")),
        ("smartart", kind("diagram")),
        ("ole", kind("embedding") or has("p:oleObj", "w:object", "draw:object-ole")),
        ("vba", kind("vba-project", "odf-basic")),
        ("custom-xml", kind("custom-xml")),
        ("signature", kind("signature")),
        ("embedded-fonts", kind("embedded-font")),
        ("alternate-content", has("mc:AlternateContent")),
        ("notes", kind("notes-slide") or has("presentation:notes")),
        ("transitions", has("p:transition", "anim:transitionFilter")),
        ("newer-transitions", any(not str(name).startswith(("p:", "(")) and name != "extLst"
                                  for name in inv["transitions"])),  # type: ignore[union-attr]
        ("animations", has("p:timing") and has("p:par", "p:seq") or has("anim:par", "anim:seq")),
        ("media", has("a:videoFile", "a:audioFile", "p:video", "p:audio", "draw:plugin")),
        ("groups", has("p:grpSp", "draw:g")),
        ("connectors", has("p:cxnSp", "draw:connector")),
        ("multi-master", kinds.get("slide-master", 0) > 1 or counts.get("style:master-page", 0) > 1),
        ("many-layouts", kinds.get("slide-layout", 0) > 3),
        ("multi-slide", kinds.get("slide", 0) > 3 or counts.get("draw:page", 0) > 3),
        ("proprietary-fonts", bool(fonts & PROPRIETARY_FONTS)),
    )
    tags.update(tag for tag, present in rules if present)
    return tags


def features_from_name(name: str) -> Set[str]:
    lower = name.lower()
    return {tag for tag, words in NAME_HINTS.items() if any(word in lower for word in words)}


def scan(tree: Path, roots: Sequence[str]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for root in roots:
        base = tree / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            fmt = path.suffix.lower().lstrip(".")
            if fmt not in QUOTAS or not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(tree).as_posix()
            size = path.stat().st_size
            if not is_candidate(relative, size):
                continue
            row: Dict[str, object] = {"path": relative, "format": fmt, "bytes": size,
                                      "app": QUOTAS[fmt][0], "producer": "",
                                      "evidence": "file-name"}
            if fmt in ZIP_FORMATS:
                if not pkgdiff.is_zip_package(path):
                    continue  # e.g. encrypted OOXML (an OLE2 container): not selected in v0
                try:
                    inventory = pkgdiff.inspect_package(path)
                except pkgdiff.PackageError:
                    continue
                if inventory["skipped_parts"]:
                    continue
                row["features"] = sorted(features_from_inventory(inventory, fmt))
                row["producer"] = producer(path)
                row["evidence"] = "package-xml"
            else:
                row["features"] = sorted(features_from_name(path.name))
            rows.append(row)
    return rows


def _foreign(row: Dict[str, object]) -> int:
    """0 when written by another producer than LibreOffice/OpenOffice (preferred)."""
    text = str(row.get("producer", "")).lower()
    if not text:
        return 1
    return 2 if ("libreoffice" in text or "openoffice" in text) else 0


def choose(rows: Iterable[Dict[str, object]], quota: int, cover: int) -> List[Dict[str, object]]:
    """Greedy set cover: always take the file that fills most open feature slots."""
    pool = sorted(rows, key=lambda row: (_foreign(row), row["bytes"], row["path"]))
    need: Dict[str, int] = {}
    for row in pool:
        for tag in row["features"]:  # type: ignore[union-attr]
            need[tag] = cover
    chosen: List[Dict[str, object]] = []
    taken: Set[str] = set()
    while len(chosen) < quota and any(value > 0 for value in need.values()):
        best: Optional[Dict[str, object]] = None
        best_gain = 0
        for row in pool:  # pool order is the tie-break: other producer, smaller, path
            if row["path"] in taken:
                continue
            gain = sum(1 for tag in row["features"] if need[tag] > 0)  # type: ignore[union-attr]
            if gain > best_gain:
                best, best_gain = row, gain
        if best is None:
            break
        chosen.append(best)
        taken.add(str(best["path"]))
        for tag in best["features"]:  # type: ignore[union-attr]
            need[tag] = max(0, need[tag] - 1)
    rest = sorted((row for row in pool if row["path"] not in taken),
                  key=lambda row: (-len(row["features"]), _foreign(row),  # type: ignore[arg-type]
                                   row["bytes"], row["path"]))
    chosen.extend(rest[: max(0, quota - len(chosen))])
    return sorted(chosen, key=lambda row: str(row["path"]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--upstream-tree", required=True, type=Path)
    parser.add_argument("--roots", nargs="*", default=list(DEFAULT_ROOTS))
    parser.add_argument("--cover", type=int, default=2,
                        help="files wanted per feature and format")
    parser.add_argument("--out", required=True, type=Path)
    return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.upstream_tree.is_dir():
        print(f"error: not a directory: {args.upstream_tree}", file=sys.stderr)
        return EXIT_USAGE
    if not 1 <= args.cover <= 5:
        print("error: --cover must be between 1 and 5", file=sys.stderr)
        return EXIT_USAGE
    for root in args.roots:
        if root.startswith("/") or ".." in Path(root).parts:
            print(f"error: bad root {root!r}", file=sys.stderr)
            return EXIT_USAGE
    rows = scan(args.upstream_tree, args.roots)
    selection: List[Dict[str, object]] = []
    stats: Dict[str, Dict[str, int]] = {}
    for fmt, (_app, quota) in QUOTAS.items():
        candidates = [row for row in rows if row["format"] == fmt]
        picked = choose(candidates, quota, args.cover)
        selection.extend(picked)
        stats[fmt] = {"candidates": len(candidates), "selected": len(picked), "quota": quota}
    selection.sort(key=lambda row: str(row["path"]))
    document = {"algorithm": ALGORITHM, "roots": list(args.roots), "cover": args.cover,
                "max_bytes": MAX_BYTES, "stats": stats, "files": selection}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"selected": len(selection), "stats": stats, "out": str(args.out)}))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(run())
