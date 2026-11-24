#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Pull licence-bearing files out of third-party archives, safely.

The ledger rule is "SPDX ID read from the licence file at that commit,
never from memory".  This tool makes those files readable without
unpacking (or executing) anything else from an untrusted archive:

* archive members are only ever *read*; nothing is extracted with the
  archive's own paths, permissions or link targets;
* only regular files whose base name looks licence-related are copied
  out, capped in size and depth, under a sanitised path;
* every copied file is hashed, so a ledger row can cite
  ``<archive sha256> + <member path> + <member sha256>``;
* fonts (``.ttf``) get their OpenType ``name`` table records dumped
  instead (copyright, licence, licence URL).

Output per archive: ``<dest>/<KEY>/_inventory.json`` and the copied
files below ``<dest>/<KEY>/files/``.

Exit codes: 0 ok; 2 bad input; 3 at least one archive unreadable or
missing; 5 archive checksum does not match download.lst.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import shutil
import struct
import sys
import tarfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from tools.common.jsonlog import JsonlLogger, default_log_dir, new_run_id
from tools.common.netfetch import sha256_file
from tools.ledger.download_lst import DownloadLstError, External, load

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_ARCHIVE = 3
EXIT_CHECKSUM = 5

REPO_ROOT = Path(__file__).resolve().parents[2]

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_COPY_DEPTH = 64         # no practical depth limit; the per-archive cap bounds the work
MAX_COPIED_PER_ARCHIVE = 400
MAX_FONT_BYTES = 40 * 1024 * 1024
MAX_FONTS_PER_ARCHIVE = 8
FONT_SUFFIXES = (".ttf", ".otf")
ZIP_SUFFIXES = (".zip", ".jar", ".nupkg", ".oxt", ".whl")
TAR_SUFFIXES = (".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tar")

# Base-name patterns (case-insensitive) that mark a licence-related file.
LICENCE_PATTERNS = (
    "licen[cs]e*", "*licen[cs]e*", "copying*", "*copying", "copyright*", "*copyright",
    "notice*", "unlicense*", "patents*", "legal*", "ofl*", "authors*", "third*party*",
    "ftl.txt", "gpl*", "lgpl*", "mpl*", "apache*", "bsd*", "mit*", "cc0*", "cc-by*",
    "eula*", "fontlog*", "credits*", "trademark*", "license.terms", "*_lic.*",
    "agpl*", "gnu-*", "gnu_*", "*gpl*", "artistic*", "epl*", "cddl*",
)
# Directories whose direct children are always treated as licence files.
LICENCE_DIRS = ("licenses", "licences", "license", "licence", "legal", "copyright")
# Top-level documents that often state the licence when no dedicated file exists.
README_PATTERNS = ("readme*", "about*", "package.json", "cargo.toml", "pom.xml",
                   "*.nuspec", "meta-inf/manifest.mf", "setup.cfg", "pyproject.toml",
                   "meson.build", "configure.ac")
# Source/binary suffixes that match a licence pattern by accident (license.cpp ...).
CODE_SUFFIXES = (
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".java", ".py", ".js", ".ts",
    ".go", ".rs", ".cs", ".php", ".rb", ".pl", ".pm", ".sh", ".bat", ".cmake", ".m4", ".mk",
    ".am", ".in", ".o", ".obj", ".class", ".png", ".jpg", ".gif", ".svg", ".ico", ".xpm",
    ".3", ".1", ".man", ".po", ".pot", ".gmo", ".test", ".exp", ".ok", ".ref", ".json",
    ".yml", ".yaml", ".toml", ".xml", ".sgml", ".css", ".tex", ".dll", ".exe", ".so", ".a",
    ".lib", ".pdb", ".pyc", ".pyd", ".ttf", ".otf", ".woff", ".woff2", ".pdf", ".docx",
    ".odt", ".cmd", ".ps1", ".vcxproj", ".sln", ".def", ".rc", ".res", ".idl", ".tcl",
)
#: Names that are licence documents even with an unusual suffix (COPYING.LIB).
STRONG_PREFIXES = ("copying", "license", "licence", "notice", "copyright", "unlicense",
                   "patents", "ofl", "gpl", "lgpl", "agpl", "gnu-", "gnu_", "mpl", "apache",
                   "bsd", "mit", "cc0", "cc-by", "artistic", "epl", "cddl")
SOURCE_SUFFIXES = (
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".java", ".py", ".js", ".ts",
    ".go", ".rs", ".cs", ".php", ".rb", ".pl", ".pm", ".sh", ".bat", ".cmake", ".m4", ".mk",
    ".am", ".o", ".obj", ".class", ".png", ".jpg", ".gif", ".svg", ".ico", ".json", ".yml",
    ".yaml", ".xml", ".css", ".tex", ".pyc", ".po", ".pot", ".gmo",
)
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._+@~=,-]")


class ArchiveError(Exception):
    """The archive cannot be read."""


def archive_kind(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(TAR_SUFFIXES):
        return "tar"
    if lower.endswith(ZIP_SUFFIXES):
        return "zip"
    if lower.endswith((".ttf", ".otf")):
        return "font"
    return "unsupported"


def normalise_member(name: str) -> Optional[PurePosixPath]:
    """Return a safe relative POSIX path, or ``None`` for a hostile/odd name."""
    if not name or "\x00" in name:
        return None
    name = name.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return PurePosixPath(*parts)


def sanitise_for_disk(path: PurePosixPath) -> PurePosixPath:
    """Map a member path to a boring on-disk path (no surprises, bounded)."""
    parts = []
    for part in path.parts:
        clean = _UNSAFE_CHARS.sub("_", part).lstrip(".-") or "_"
        parts.append(clean[:100])
    return PurePosixPath(*parts[-12:])


def strip_root(paths: Sequence[PurePosixPath]) -> int:
    """Number of leading components shared by every member (0 or 1).

    Most source tarballs wrap everything in ``name-version/``; depth is
    measured below that directory.
    """
    roots = {path.parts[0] for path in paths if path.parts}
    if len(roots) == 1 and all(len(path.parts) > 1 for path in paths):
        return 1
    return 0


def _matches(name: str, patterns: Iterable[str]) -> bool:
    lower = name.lower()
    return any(fnmatch.fnmatchcase(lower, pattern) for pattern in patterns)


def classify(path: PurePosixPath, root_depth: int) -> Optional[str]:
    """Return ``"licence"``, ``"readme"`` or ``None`` for an archive member."""
    rel = path.parts[root_depth:]
    if not rel:
        return None
    base = rel[-1]
    lower = base.lower()
    in_licence_dir = len(rel) >= 2 and rel[-2].lower() in LICENCE_DIRS
    if in_licence_dir and not lower.endswith((".png", ".jpg", ".gif", ".svg")):
        return "licence"
    if _matches(base, LICENCE_PATTERNS):
        suffix = PurePosixPath(lower).suffix
        # "COPYING.LIB", "LICENSE.3rdparty" ... are licence texts whatever the suffix;
        # only real source/asset suffixes disqualify a strong name.
        excluded = SOURCE_SUFFIXES if lower.startswith(STRONG_PREFIXES) else CODE_SUFFIXES
        if suffix in excluded and not in_licence_dir:
            return None
        return "licence"
    if len(rel) <= 1 and _matches(base, README_PATTERNS):
        return "readme"
    if len(rel) == 2 and _matches("/".join(rel), README_PATTERNS):
        return "readme"
    return None


def _iter_tar(path: Path) -> Iterator[Tuple[str, int, Callable[..., bytes]]]:
    try:
        with tarfile.open(path, mode="r:*") as archive:
            for member in archive:
                if not member.isreg():
                    continue  # links, devices and directories are never touched

                def reader(limit: int = MAX_FILE_BYTES,
                           member: tarfile.TarInfo = member) -> bytes:
                    handle = archive.extractfile(member)
                    if handle is None:
                        return b""
                    with handle:
                        return handle.read(limit + 1)

                yield member.name, member.size, reader
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ArchiveError(f"{path.name}: {exc}") from exc


def _iter_zip(path: Path) -> Iterator[Tuple[str, int, Callable[..., bytes]]]:
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                # Unix symlink entries (mode 0o120000) are skipped.
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    continue

                def reader(limit: int = MAX_FILE_BYTES,
                           info: zipfile.ZipInfo = info) -> bytes:
                    with archive.open(info) as handle:
                        return handle.read(limit + 1)

                yield info.filename, info.file_size, reader
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as exc:
        raise ArchiveError(f"{path.name}: {exc}") from exc


def _read_all(reader: Callable[..., bytes], limit: int) -> bytes:
    """Read a member with an explicit, bounded limit (fonts exceed the default)."""
    data = reader(limit)
    if len(data) > limit:
        raise ArchiveError("member larger than the configured limit")
    return data


def font_name_records(data: bytes) -> List[dict]:
    """Decode the OpenType ``name`` table (OpenType spec, public).

    Returns records for name IDs 0 (copyright), 1 (family), 3, 4, 5
    (version), 7 (trademark), 8 (manufacturer), 13 (licence description)
    and 14 (licence URL).
    """
    wanted = {0, 1, 3, 4, 5, 7, 8, 13, 14}
    if len(data) < 12:
        raise ArchiveError("font too short")
    num_tables = struct.unpack(">H", data[4:6])[0]
    table = None
    for index in range(num_tables):
        entry = data[12 + 16 * index: 28 + 16 * index]
        if len(entry) < 16:
            raise ArchiveError("truncated table directory")
        tag, _checksum, offset, length = struct.unpack(">4sIII", entry)
        if tag == b"name":
            table = data[offset: offset + length]
            break
    if table is None or len(table) < 6:
        raise ArchiveError("font has no name table")
    _fmt, count, string_offset = struct.unpack(">HHH", table[:6])
    records = []
    for index in range(count):
        raw = table[6 + 12 * index: 18 + 12 * index]
        if len(raw) < 12:
            break
        platform, encoding, language, name_id, length, offset = struct.unpack(">6H", raw)
        if name_id not in wanted:
            continue
        blob = table[string_offset + offset: string_offset + offset + length]
        codec = "utf-16-be" if platform in (0, 3) else "mac_roman"
        text = blob.decode(codec, errors="replace")
        records.append({"platform": platform, "encoding": encoding, "language": language,
                        "name_id": name_id, "text": text})
    return records


def process_archive(item: External, tarballs: Path, dest: Path) -> dict:
    """Build the inventory for one external and copy its licence files."""
    archive = tarballs / item.filename
    out_dir = dest / item.key
    files_dir = out_dir / "files"
    inventory: dict = {"key": item.key, "variable": item.variable, "filename": item.filename,
                       "url": item.url, "archive_sha256_expected": item.sha256}
    if not archive.is_file():
        inventory.update(status="missing", error=f"not found: {archive}")
        return inventory
    actual = sha256_file(archive)
    inventory["archive_sha256"] = actual
    if actual != item.sha256:
        inventory.update(status="checksum-mismatch")
        return inventory

    kind = archive_kind(item.filename)
    inventory["archive_kind"] = kind
    out_dir.mkdir(parents=True, exist_ok=True)
    # Never mix evidence of two archive versions: drop what an earlier run left.
    if dest.resolve() in files_dir.resolve().parents and files_dir.is_dir():
        shutil.rmtree(files_dir)
    for stale in ("_fonts.json", "_font_name_table.json"):
        (out_dir / stale).unlink(missing_ok=True)

    if kind == "font":
        records = font_name_records(archive.read_bytes())
        (out_dir / "_font_name_table.json").write_text(
            json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        inventory.update(status="ok", font_name_records=len(records), candidates=[],
                         copied=0, member_count=1)
        return inventory
    if kind == "unsupported":
        inventory.update(status="unsupported", error="unknown archive type")
        return inventory

    iterator = _iter_tar(archive) if kind == "tar" else _iter_zip(archive)
    hostile = 0
    candidates: List[dict] = []
    # Tar members must be read while the archive is open and in order, so
    # classification happens in a first pass over names only when possible.
    # To keep one pass, depth is decided after the fact for the root guess:
    # collect names first (cheap), then re-open to read the chosen members.
    names: List[PurePosixPath] = []
    sizes: Dict[str, int] = {}
    for name, size, _reader in iterator:
        path = normalise_member(name)
        if path is None:
            hostile += 1
            continue
        names.append(path)
        sizes[str(path)] = size
    root_depth = strip_root(names)
    chosen: Dict[str, str] = {}
    for path in names:
        role = classify(path, root_depth)
        if role:
            chosen[str(path)] = role

    def copy_depth(path: PurePosixPath) -> int:
        return len(path.parts) - root_depth

    to_copy = {name for name, role in chosen.items()
               if copy_depth(PurePosixPath(name)) <= MAX_COPY_DEPTH
               and sizes[name] <= MAX_FILE_BYTES}
    # Deterministic cap: shallowest paths first, then alphabetical.
    ordered = sorted(to_copy, key=lambda name: (len(PurePosixPath(name).parts), name))
    to_copy = set(ordered[:MAX_COPIED_PER_ARCHIVE])

    copied_hashes: Dict[str, Tuple[str, str]] = {}
    iterator = _iter_tar(archive) if kind == "tar" else _iter_zip(archive)
    for name, _size, reader in iterator:
        path = normalise_member(name)
        if path is None or str(path) not in to_copy or str(path) in copied_hashes:
            continue
        data = reader()
        if len(data) > MAX_FILE_BYTES:
            continue
        target = files_dir / sanitise_for_disk(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        copied_hashes[str(path)] = (hashlib.sha256(data).hexdigest(),
                                    str(target.relative_to(out_dir)))

    # Fonts packed inside the archive carry their licence in the OpenType
    # name table (IDs 13/14); dump those records for a bounded sample.
    font_members = sorted(
        (str(path) for path in names
         if path.suffix.lower() in FONT_SUFFIXES and sizes[str(path)] <= MAX_FONT_BYTES),
        key=lambda name: (len(PurePosixPath(name).parts), name))[:MAX_FONTS_PER_ARCHIVE]
    font_dump: List[dict] = []
    if font_members:
        wanted_fonts = set(font_members)
        iterator = _iter_tar(archive) if kind == "tar" else _iter_zip(archive)
        for name, _size, reader in iterator:
            path = normalise_member(name)
            if path is None or str(path) not in wanted_fonts:
                continue
            wanted_fonts.discard(str(path))
            data = _read_all(reader, MAX_FONT_BYTES)
            entry = {"member": str(path), "sha256": hashlib.sha256(data).hexdigest()}
            try:
                records = font_name_records(data)
                entry["name_records"] = [r for r in records if r["name_id"] in (0, 1, 5, 13, 14)
                                         and (r["platform"], r["language"]) in ((3, 1033), (1, 0))]
            except ArchiveError as exc:
                entry["error"] = str(exc)
            font_dump.append(entry)
        (out_dir / "_fonts.json").write_text(
            json.dumps(font_dump, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    inventory["font_members_total"] = sum(
        1 for path in names if path.suffix.lower() in FONT_SUFFIXES)
    inventory["font_members_dumped"] = len(font_dump)

    for name in sorted(chosen):
        entry = {"member": name, "role": chosen[name], "size": sizes[name],
                 "depth": copy_depth(PurePosixPath(name)), "copied": name in copied_hashes}
        if name in copied_hashes:
            entry["sha256"], entry["local"] = copied_hashes[name]
        candidates.append(entry)

    top_level = sorted({path.parts[root_depth] for path in names if len(path.parts) > root_depth})
    inventory.update(
        status="ok",
        member_count=len(names),
        hostile_names_skipped=hostile,
        root_dir=names[0].parts[0] if root_depth and names else "",
        top_level=top_level[:200],
        candidates=candidates,
        copied=len(copied_hashes),
        licence_candidates=sum(1 for c in candidates if c["role"] == "licence"),
        licence_candidates_not_copied=sum(
            1 for c in candidates if c["role"] == "licence" and not c["copied"]),
    )
    return inventory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--download-lst", required=True, type=Path)
    parser.add_argument("--tarballs", required=True, type=Path)
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--only", nargs="*", default=[], metavar="KEY")
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.download_lst.is_file():
        print(f"error: not a file: {args.download_lst}", file=sys.stderr)
        return EXIT_USAGE
    if not args.tarballs.is_dir():
        print(f"error: not a directory: {args.tarballs}", file=sys.stderr)
        return EXIT_USAGE
    try:
        items = load(args.download_lst)
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
    log = JsonlLogger(default_log_dir(REPO_ROOT) / f"extract-licences-{run_id}.jsonl",
                      phase="phase0", run_id=run_id)
    log.log("start", count=len(items), dest=str(args.dest))
    args.dest.mkdir(parents=True, exist_ok=True)

    rows = []
    started = time.monotonic()
    for item in items:
        t0 = time.monotonic()
        try:
            inventory = process_archive(item, args.tarballs, args.dest)
        except ArchiveError as exc:
            inventory = {"key": item.key, "variable": item.variable,
                         "filename": item.filename, "status": "unreadable", "error": str(exc)}
        out_dir = args.dest / item.key
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "_inventory.json").write_text(
            json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        ok = inventory["status"] == "ok"
        log.log("extract", result="ok" if ok else "fail", level="INFO" if ok else "ERROR",
                duration_ms=int((time.monotonic() - t0) * 1000), key=item.key,
                filename=item.filename, status=inventory["status"],
                copied=inventory.get("copied", 0),
                licence_candidates=inventory.get("licence_candidates", 0),
                error=inventory.get("error", ""))
        rows.append({"key": item.key, "filename": item.filename, "status": inventory["status"],
                     "copied": inventory.get("copied", 0),
                     "licence_candidates": inventory.get("licence_candidates", 0),
                     "licence_candidates_not_copied":
                         inventory.get("licence_candidates_not_copied", 0)})

    counts: dict = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    summary = {"run_id": run_id, "total": len(rows), "by_status": counts,
               "without_licence_candidate": sorted(
                   row["key"] for row in rows
                   if row["status"] == "ok" and row["licence_candidates"] == 0),
               "duration_ms": int((time.monotonic() - started) * 1000), "items": rows}
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    if counts.get("checksum-mismatch"):
        code = EXIT_CHECKSUM
    elif any(status != "ok" for status in counts):
        code = EXIT_ARCHIVE
    else:
        code = EXIT_OK
    log.log("finish", result="ok" if code == EXIT_OK else "fail",
            level="INFO" if code == EXIT_OK else "ERROR",
            duration_ms=summary["duration_ms"], exit_code=code, by_status=counts)
    print(json.dumps({"run_id": run_id, "total": len(rows), "by_status": counts,
                      "without_licence_candidate": summary["without_licence_candidate"],
                      "exit_code": code, "log": str(log.path)}))
    return code


if __name__ == "__main__":
    sys.exit(run())
