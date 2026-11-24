# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Parser for the upstream ``download.lst`` file.

``download.lst`` (top of the upstream source tree) names every external
tarball the build may fetch, with its SHA-256.  The pairing rule and the
two download bases are taken from the upstream ``Makefile.fetch`` at the
pinned tag (``fetch_Download__subst_var`` and the two ``foreach`` blocks
that call ``fetch_Download_item``):

* ``X_TARBALL`` / ``X_JAR`` / ``X_TTF`` / ``X_DLL`` / ``X_PACK`` pair with
  ``X_SHA256SUM``;
* ``*_TARBALL`` entries come from ``<base>/src``;
* ``*_JAR`` and ``*_TTF`` entries come from ``<base>/extern``.

Nothing here executes upstream code; the file is read as text only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from tools.common.netfetch import SHA256_RE

UPSTREAM_BASE = "https://dev-www.libreoffice.org"
FILE_KINDS = ("TARBALL", "JAR", "TTF", "DLL", "PACK")
# Sub-directory of UPSTREAM_BASE per kind, as used by Makefile.fetch.
KIND_SUBDIR = {"TARBALL": "src", "JAR": "extern", "TTF": "extern"}

_ASSIGN_RE = re.compile(r"^([A-Z0-9_]+)\s*:=\s*(.*?)\s*$")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+~-]*$")


class DownloadLstError(ValueError):
    """``download.lst`` is malformed or violates an assumption we rely on."""


@dataclass(frozen=True)
class External:
    key: str        # e.g. "BOOST" (variable prefix)
    variable: str   # e.g. "BOOST_TARBALL"
    kind: str       # one of FILE_KINDS
    filename: str   # e.g. "boost_1_91_0.tar.xz"
    sha256: str
    url: str        # "" when Makefile.fetch defines no base for this kind

    @property
    def fetchable(self) -> bool:
        return bool(self.url)


_REF_RE = re.compile(r"\$\(([A-Z0-9_]+)\)")


def parse_assignments(text: str) -> Dict[str, str]:
    """Return ``VAR -> value`` for every ``VAR := value`` line.

    A variable assigned twice is an error: silently taking either value
    could pair a file with the wrong checksum.

    ``:=`` is GNU make's immediate assignment, so a ``$(NAME)`` reference
    expands to the value ``NAME`` has *at that line*.  Upstream uses this
    for version components (``X_VERSION_MICRO``).  A reference to a
    variable not yet assigned is an error here (make would expand it to
    the empty string and silently produce a wrong file name).
    """
    values: Dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGN_RE.match(line)
        if not match:
            raise DownloadLstError(f"line {number}: unrecognised syntax: {raw!r}")
        name, value = match.group(1), match.group(2)
        if name in values:
            raise DownloadLstError(f"line {number}: {name} assigned more than once")

        def _expand(ref: "re.Match[str]") -> str:
            target = ref.group(1)
            if target not in values:
                raise DownloadLstError(
                    f"line {number}: {name} refers to $({target}) before it is assigned")
            return values[target]

        value = _REF_RE.sub(_expand, value)
        if "$" in value:
            raise DownloadLstError(f"line {number}: unsupported make syntax in {raw!r}")
        values[name] = value
    return values


def _checksum_var(variable: str) -> str:
    for kind in FILE_KINDS:
        suffix = "_" + kind
        if variable.endswith(suffix):
            return variable[: -len(suffix)] + "_SHA256SUM"
    raise DownloadLstError(f"{variable} is not a file variable")


def parse_download_lst(text: str, base_url: str = UPSTREAM_BASE) -> List[External]:
    """Return every downloadable item, sorted by variable name."""
    values = parse_assignments(text)
    base_url = base_url.rstrip("/")
    items: List[External] = []
    used_checksums = set()
    for variable, filename in values.items():
        kind = next((k for k in FILE_KINDS if variable.endswith("_" + k)), None)
        if kind is None:
            continue
        if not filename:
            raise DownloadLstError(f"{variable} is empty")
        if not _SAFE_NAME_RE.match(filename) or ".." in filename:
            raise DownloadLstError(f"{variable}: unsafe file name {filename!r}")
        checksum_var = _checksum_var(variable)
        checksum = values.get(checksum_var, "").lower()
        if not SHA256_RE.match(checksum):
            raise DownloadLstError(f"{variable}: missing or malformed {checksum_var}")
        used_checksums.add(checksum_var)
        subdir = KIND_SUBDIR.get(kind)
        url = f"{base_url}/{subdir}/{filename}" if subdir else ""
        items.append(
            External(
                key=variable[: -(len(kind) + 1)],
                variable=variable,
                kind=kind,
                filename=filename,
                sha256=checksum,
                url=url,
            )
        )
    orphans = sorted(
        name for name in values if name.endswith("_SHA256SUM") and name not in used_checksums
    )
    if orphans:
        raise DownloadLstError(f"checksum without a file variable: {', '.join(orphans)}")
    filenames = [item.filename for item in items]
    duplicates = sorted({name for name in filenames if filenames.count(name) > 1})
    if duplicates:
        raise DownloadLstError(f"file name listed twice: {', '.join(duplicates)}")
    return sorted(items, key=lambda item: item.variable)


def load(path: Path, base_url: str = UPSTREAM_BASE) -> List[External]:
    return parse_download_lst(Path(path).read_text(encoding="utf-8"), base_url=base_url)
