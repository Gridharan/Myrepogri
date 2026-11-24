# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Reader/validator for ``corpus/MANIFEST.csv``.

The manifest is the provenance record of the fidelity corpus: a file may
be used by the harness only if it has a row here, its bytes match the
recorded SHA-256, and its ``source`` is one of the three kinds we have
the right to use.

Columns (all required, in this order):

``id``            stable identifier, ``[a-z0-9-]+``
``path``          for ``self-authored``/``derived``: path relative to the
                  repository root; for ``upstream-test-file``: path
                  relative to the root of the pinned upstream tree
``source``        ``self-authored`` | ``upstream-test-file`` | ``derived``
``origin``        generator script, upstream tag, or source id + filter
``sha256``        SHA-256 of the file
``bytes``         file size
``format``        lower-case extension without dot
``app``           ``writer`` | ``impress``
``features``      ``;``-separated feature tags (may be empty)
``licence``       SPDX id, or ``NOASSERTION`` with a ledger reference
``password``      password needed to open the file (usually empty)
``notes``         free text
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from tools.common.netfetch import SHA256_RE, sha256_file

COLUMNS = ("id", "path", "source", "origin", "sha256", "bytes", "format", "app",
           "features", "licence", "password", "notes")
SOURCES = ("self-authored", "upstream-test-file", "derived")
APPS = ("writer", "impress")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_FEATURE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ManifestError(ValueError):
    """The manifest is malformed, or a file does not match its row."""


@dataclass(frozen=True)
class Entry:
    id: str
    path: str
    source: str
    origin: str
    sha256: str
    bytes: int
    format: str
    app: str
    features: tuple
    licence: str
    password: str
    notes: str

    def resolve(self, repo_root: Path, upstream_tree: Optional[Path]) -> Path:
        """Absolute location of the file on this machine."""
        if self.source == "upstream-test-file":
            if upstream_tree is None:
                raise ManifestError(
                    f"{self.id}: upstream tree location is required for upstream test files")
            base = Path(upstream_tree)
        else:
            base = Path(repo_root)
        target = (base / self.path).resolve()
        if base.resolve() not in target.parents:
            raise ManifestError(f"{self.id}: path escapes its base directory: {self.path}")
        return target


def _parse_row(number: int, row: Dict[str, str]) -> Entry:
    def fail(message: str) -> ManifestError:
        return ManifestError(f"MANIFEST.csv line {number}: {message}")

    values = {key: (row.get(key) or "").strip() for key in COLUMNS}
    if not _ID_RE.match(values["id"]):
        raise fail(f"bad id {values['id']!r}")
    path = values["path"]
    if not path or path.startswith(("/", "\\")) or ".." in Path(path).parts or "\\" in path:
        raise fail(f"bad path {path!r}")
    if values["source"] not in SOURCES:
        raise fail(f"source must be one of {SOURCES}")
    if not values["origin"]:
        raise fail("origin is empty")
    sha = values["sha256"].lower()
    if not SHA256_RE.match(sha):
        raise fail("sha256 is not a SHA-256 hex digest")
    try:
        size = int(values["bytes"])
    except ValueError as exc:
        raise fail("bytes is not an integer") from exc
    if size < 0:
        raise fail("bytes is negative")
    fmt = values["format"]
    if not re.match(r"^[a-z0-9]{1,8}$", fmt):
        raise fail(f"bad format {fmt!r}")
    if not path.lower().endswith("." + fmt):
        raise fail(f"format {fmt!r} does not match the file extension of {path!r}")
    if values["app"] not in APPS:
        raise fail(f"app must be one of {APPS}")
    features = tuple(item for item in values["features"].split(";") if item)
    for feature in features:
        if not _FEATURE_RE.match(feature):
            raise fail(f"bad feature tag {feature!r}")
    if len(set(features)) != len(features):
        raise fail("duplicate feature tag")
    if not values["licence"]:
        raise fail("licence is empty")
    return Entry(values["id"], path, values["source"], values["origin"], sha, size, fmt,
                 values["app"], features, values["licence"], values["password"],
                 values["notes"])


def load_manifest(path: Path) -> List[Entry]:
    """Parse and validate the manifest (structure only, no file access)."""
    path = Path(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ManifestError(
                f"MANIFEST.csv header must be exactly: {','.join(COLUMNS)}")
        entries = [_parse_row(number, row) for number, row in enumerate(reader, 2)]
    ids = [entry.id for entry in entries]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise ManifestError(f"duplicate id(s): {', '.join(duplicates)}")
    keys = [(entry.source == "upstream-test-file", entry.path) for entry in entries]
    if len(set(keys)) != len(keys):
        raise ManifestError("the same file is listed more than once")
    return entries


def verify_entry(entry: Entry, repo_root: Path, upstream_tree: Optional[Path]) -> Path:
    """Return the resolved file after checking existence, size and SHA-256."""
    target = entry.resolve(repo_root, upstream_tree)
    if not target.is_file():
        raise ManifestError(f"{entry.id}: file not found: {target}")
    size = target.stat().st_size
    if size != entry.bytes:
        raise ManifestError(f"{entry.id}: size {size} differs from manifest {entry.bytes}")
    actual = sha256_file(target)
    if actual != entry.sha256:
        raise ManifestError(f"{entry.id}: sha256 {actual} differs from manifest")
    return target


def write_manifest(path: Path, rows: List[Dict[str, str]]) -> None:
    """Write rows (dicts keyed by COLUMNS) in a stable order."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in sorted(rows, key=lambda item: item["id"]):
            writer.writerow({key: row.get(key, "") for key in COLUMNS})
