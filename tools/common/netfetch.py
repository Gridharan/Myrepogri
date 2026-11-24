# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Checksum-verified downloads with timeouts and bounded retries.

Rules implemented here (engineering standards):

* every download is verified against a SHA-256 the caller supplies;
* a download is written to ``<name>.part`` and renamed only after the
  checksum matched, so an interrupted run never leaves a bad file behind;
* a file that is already present with the right checksum is not fetched
  again (idempotent, resumable);
* retries with exponential backoff apply to network errors only.  A
  checksum mismatch is never retried: it means the source is wrong.
"""

from __future__ import annotations

import hashlib
import http.client
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 1024 * 1024
_ALLOWED_SCHEMES = ("https", "http")


class FetchError(Exception):
    """A download failed after all retries (network or HTTP error)."""


class ChecksumMismatch(Exception):
    """Downloaded bytes do not match the expected SHA-256."""

    def __init__(self, url: str, expected: str, actual: str) -> None:
        super().__init__(f"sha256 mismatch for {url}: expected {expected}, got {actual}")
        self.url = url
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True)
class FetchResult:
    path: Path
    sha256: str
    size: int
    status: str  # "downloaded" | "cached"
    attempts: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_sha256(value: str) -> str:
    value = (value or "").strip().lower()
    if not SHA256_RE.match(value):
        raise ValueError(f"not a SHA-256 hex digest: {value!r}")
    return value


def validate_url(url: str, allow_http: bool = False) -> str:
    parsed = urllib.parse.urlsplit(url)
    schemes = _ALLOWED_SCHEMES if allow_http else ("https",)
    if parsed.scheme not in schemes or not parsed.netloc:
        raise ValueError(f"unsupported or malformed URL: {url!r}")
    return url


def backoff_delays(retries: int, base: float = 2.0, cap: float = 60.0) -> list:
    """Delays (seconds) slept before retry 1..n: base, 2*base, 4*base ... capped."""
    if retries < 0:
        raise ValueError("retries must be >= 0")
    return [min(cap, base * (2 ** index)) for index in range(retries)]


def fetch_verified(
    url: str,
    dest: Path,
    expected_sha256: str,
    timeout: float = 120.0,
    retries: int = 4,
    backoff_base: float = 2.0,
    allow_http: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    opener: Optional[Callable] = None,
) -> FetchResult:
    """Download ``url`` to ``dest`` and verify it.

    Raises ``FetchError`` when the network keeps failing and
    ``ChecksumMismatch`` when the bytes are wrong.  ``dest`` only ever
    exists with the expected content.
    """
    validate_url(url, allow_http=allow_http)
    expected = validate_sha256(expected_sha256)
    dest = Path(dest)
    if timeout <= 0:
        raise ValueError("timeout must be > 0")

    if dest.is_file():
        actual = sha256_file(dest)
        if actual == expected:
            return FetchResult(dest, actual, dest.stat().st_size, "cached", 0)
        # A wrong file at the final path is never trusted or silently kept.
        dest.unlink()

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    open_url = opener or urllib.request.urlopen
    delays = backoff_delays(retries, base=backoff_base)
    last_error: Optional[BaseException] = None

    for attempt in range(1, retries + 2):
        try:
            digest = hashlib.sha256()
            size = 0
            request = urllib.request.Request(url, headers={"User-Agent": "build-fetch/1"})
            with open_url(request, timeout=timeout) as response, part.open("wb") as out:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise FetchError(f"HTTP {status} for {url}")
                for chunk in iter(lambda: response.read(_CHUNK), b""):
                    out.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            actual = digest.hexdigest()
            if actual != expected:
                part.unlink(missing_ok=True)
                raise ChecksumMismatch(url, expected, actual)
            os.replace(part, dest)
            return FetchResult(dest, actual, size, "downloaded", attempt)
        except ChecksumMismatch:
            raise
        except urllib.error.HTTPError as exc:
            part.unlink(missing_ok=True)
            last_error = exc
            # 4xx (except 408/429) will not get better by retrying.
            if 400 <= exc.code < 500 and exc.code not in (408, 429):
                raise FetchError(f"HTTP {exc.code} for {url}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, FetchError,
                http.client.HTTPException) as exc:
            # HTTPException covers a body cut short (IncompleteRead): retry it too.
            part.unlink(missing_ok=True)
            last_error = exc
        if attempt <= retries:
            sleep(delays[attempt - 1])

    raise FetchError(f"giving up on {url} after {retries + 1} attempts: {last_error}")
