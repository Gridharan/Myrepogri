# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""JSON-lines run logging shared by every tool in this repository.

Every record carries the fields required by the engineering standards:
``ts``, ``level``, ``run_id``, ``phase``, ``step``, ``duration_ms`` and
``result``.  Extra keyword fields are appended after those.

Log files live in ``logs/`` (git-ignored).  The directory can be moved
with the ``SUITE_LOG_DIR`` environment variable (see docs/CONFIG.md).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional, TextIO

LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")
RESULTS = ("ok", "fail", "skip", "info")

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REQUIRED = ("ts", "level", "run_id", "phase", "step", "duration_ms", "result")


def new_run_id() -> str:
    """Return a sortable, collision-resistant run identifier."""
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def default_log_dir(repo_root: Path) -> Path:
    """Resolve the log directory: ``SUITE_LOG_DIR`` or ``<repo>/logs``."""
    override = os.environ.get("SUITE_LOG_DIR", "").strip()
    return Path(override) if override else repo_root / "logs"


class JsonlLogger:
    """Append-only JSON-lines logger.

    The logger is safe to share between threads.  It never raises on a
    non-serialisable extra value; such values are logged via ``repr``.
    """

    def __init__(
        self,
        path: Path,
        phase: str,
        run_id: Optional[str] = None,
        echo: Optional[TextIO] = None,
    ) -> None:
        if not phase or not isinstance(phase, str):
            raise ValueError("phase must be a non-empty string")
        run_id = run_id or new_run_id()
        if not _RUN_ID_RE.match(run_id):
            raise ValueError(f"invalid run_id: {run_id!r}")
        self.path = Path(path)
        self.phase = phase
        self.run_id = run_id
        self._echo = echo
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.counts = {level: 0 for level in LEVELS}

    def log(
        self,
        step: str,
        result: str = "info",
        level: str = "INFO",
        duration_ms: int = 0,
        **extra: Any,
    ) -> dict:
        """Write one record and return it."""
        if level not in LEVELS:
            raise ValueError(f"invalid level: {level!r}")
        if result not in RESULTS:
            raise ValueError(f"invalid result: {result!r}")
        if not step or not isinstance(step, str):
            raise ValueError("step must be a non-empty string")
        record = {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds"),
            "level": level,
            "run_id": self.run_id,
            "phase": self.phase,
            "step": step,
            "duration_ms": int(duration_ms),
            "result": result,
        }
        for key, value in extra.items():
            if key in record:
                raise ValueError(f"extra field {key!r} collides with a required field")
            record[key] = value
        line = json.dumps(record, ensure_ascii=False, default=repr, sort_keys=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self.counts[level] += 1
            if self._echo is not None:
                self._echo.write(line + "\n")
                self._echo.flush()
        return record

    @contextmanager
    def timed(self, step: str, **extra: Any) -> Iterator[dict]:
        """Log ``step`` with its duration; ``result`` is ``fail`` on exception.

        The yielded dict can be filled with extra fields by the caller.
        Setting ``ctx["result"]`` overrides the result on normal exit.
        """
        ctx: dict = {}
        start = time.monotonic()
        try:
            yield ctx
        except BaseException as exc:
            duration = int((time.monotonic() - start) * 1000)
            fields = {**extra, **{k: v for k, v in ctx.items() if k != "result"}}
            fields["error"] = f"{type(exc).__name__}: {exc}"
            self.log(step, result="fail", level="ERROR", duration_ms=duration, **fields)
            raise
        duration = int((time.monotonic() - start) * 1000)
        result = ctx.pop("result", "ok")
        level = "ERROR" if result == "fail" else "INFO"
        self.log(step, result=result, level=level, duration_ms=duration, **{**extra, **ctx})


def read_records(path: Path) -> list:
    """Parse a JSON-lines log; raises ``ValueError`` on a malformed record."""
    records = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: not JSON: {exc}") from exc
            missing = [key for key in _REQUIRED if key not in record]
            if missing:
                raise ValueError(f"{path}:{number}: missing fields {missing}")
            records.append(record)
    return records
