# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Per-run metrics file (``reports/build-metrics.json``).

Each tool owns one named section and replaces it atomically; other
sections are left untouched, so tools can run in any order and be
re-run safely.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from pathlib import Path
from typing import Any, Dict

_SECTION_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
SCHEMA_VERSION = 1


def read_metrics(path: Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "sections": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("sections"), dict):
        raise ValueError(f"{path}: not a metrics file")
    return data


def update_metrics(path: Path, section: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """Replace ``section`` with ``values`` (plus a timestamp) and write the file."""
    if not _SECTION_RE.match(section):
        raise ValueError(f"invalid section name: {section!r}")
    if not isinstance(values, dict):
        raise ValueError("values must be a dict")
    path = Path(path)
    data = read_metrics(path)
    entry = dict(values)
    entry["updated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    data["schema_version"] = SCHEMA_VERSION
    data["sections"][section] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return data
