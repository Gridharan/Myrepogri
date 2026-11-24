#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Verify the upstream pin recorded in ``config/upstream-pin.json``.

Checks, each one independent and recorded with the command that was run:

1. the tag resolves to the pinned commit on the official repository;
2. the read-only GitHub mirror resolves the same tag to the same commit;
3. the pinned release is the newest ``x.y.z`` directory in the official
   stable listing, and the official source directory of that release
   holds the archive named after the pinned tag;
4. (optional) a local checkout's HEAD is the pinned commit;
5. (optional) a downloaded release archive has the SHA-256 the
   publisher's own server reports for it;
6. (optional) an unpacked release reports the pinned commit as build id.

Network steps use ``git ls-remote`` and HTTPS GET with timeouts and
bounded retries.  Writes the evidence as JSON; exit code 0 only when
every executed check passed (2 bad input, 9 a check failed).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from tools.common.jsonlog import JsonlLogger, default_log_dir, new_run_id
from tools.common.netfetch import SHA256_RE, backoff_delays, sha256_file, validate_url

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CHECK_FAILED = 9

REPO_ROOT = Path(__file__).resolve().parents[2]
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_TAG_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_BUILDID_RE = re.compile(r"^buildid=([0-9a-f]{40})\s*$", re.M)


class PinError(ValueError):
    """The pin file is malformed."""


def load_pin(path: Path) -> Dict[str, str]:
    try:
        pin = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PinError(f"{path}: {exc}") from exc
    for key in ("tag", "commit", "official_repository", "mirror_repository"):
        if not isinstance(pin.get(key), str) or not pin[key]:
            raise PinError(f"{path}: missing {key}")
    if not _TAG_RE.match(pin["tag"]):
        raise PinError("tag has unexpected characters")
    if not _COMMIT_RE.match(pin["commit"]):
        raise PinError("commit must be a 40-character hex id")
    for key in ("official_repository", "mirror_repository"):
        validate_url(pin[key])
    return pin


def parse_ls_remote(output: str, tag: str) -> Optional[str]:
    """Commit a tag points at: the peeled (``^{}``) line wins over the tag object."""
    direct = peeled = None
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        if parts[1] == f"refs/tags/{tag}^{{}}":
            peeled = parts[0]
        elif parts[1] == f"refs/tags/{tag}":
            direct = parts[0]
    return peeled or direct


def ls_remote(repository: str, tag: str, timeout: float = 120.0, retries: int = 3,
              runner: Callable = subprocess.run,
              sleep: Callable[[float], None] = time.sleep) -> Dict[str, object]:
    command = ["git", "ls-remote", "--tags", repository, f"refs/tags/{tag}*"]
    delays = backoff_delays(retries)
    last = ""
    for attempt in range(retries + 1):
        try:
            done = runner(command, capture_output=True, text=True, timeout=timeout)
            if done.returncode == 0:
                return {"command": " ".join(command), "commit": parse_ls_remote(done.stdout, tag),
                        "attempts": attempt + 1}
            last = (done.stderr or "").strip()[:300]
        except (OSError, subprocess.TimeoutExpired) as exc:
            last = str(exc)
        if attempt < retries:
            sleep(delays[attempt])
    return {"command": " ".join(command), "commit": None, "error": last, "attempts": retries + 1}


_STABLE_DIR = re.compile(r'href="(\d+)\.(\d+)\.(\d+)/"')
MAX_LISTING_BYTES = 2 * 1024 * 1024


def http_get(url: str, timeout: float = 60.0, retries: int = 3,
             opener: Callable = urllib.request.urlopen,
             sleep: Callable[[float], None] = time.sleep) -> Optional[bytes]:
    """Body of a small page, or ``None`` after bounded retries."""
    validate_url(url)
    delays = backoff_delays(retries)
    for attempt in range(retries + 1):
        try:
            with opener(urllib.request.Request(url, headers={"User-Agent": "build-fetch/1"}),
                        timeout=timeout) as response:
                return response.read(MAX_LISTING_BYTES)
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < retries:
                sleep(delays[attempt])
    return None


def newest_stable(listing: bytes) -> Optional[str]:
    """Highest ``x.y.z/`` directory linked from a release listing page."""
    versions = {tuple(int(part) for part in match)
                for match in _STABLE_DIR.findall(listing.decode("utf-8", "replace"))}
    return ".".join(str(part) for part in max(versions)) if versions else None


def published_sha256(url: str, timeout: float = 60.0, retries: int = 3,
                     opener: Callable = urllib.request.urlopen,
                     sleep: Callable[[float], None] = time.sleep) -> Optional[str]:
    """First hex digest in the body of ``<url>`` (a ``.sha256`` resource)."""
    validate_url(url)
    delays = backoff_delays(retries)
    for attempt in range(retries + 1):
        try:
            with opener(urllib.request.Request(url, headers={"User-Agent": "build-fetch/1"}),
                        timeout=timeout) as response:
                token = response.read(4096).decode("ascii", "replace").split()
            value = token[0].lower() if token else ""
            return value if SHA256_RE.match(value) else None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < retries:
                sleep(delays[attempt])
    return None


def run(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pin", type=Path, default=REPO_ROOT / "config" / "upstream-pin.json")
    parser.add_argument("--checkout", type=Path, default=None)
    parser.add_argument("--release-archive", type=Path, default=None)
    parser.add_argument("--engine-home", type=Path, default=None)
    parser.add_argument("--offline", action="store_true", help="skip the network checks")
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "compliance" / "evidence" / "upstream-pin.json")
    args = parser.parse_args(argv)
    try:
        pin = load_pin(args.pin)
    except (PinError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    run_id = new_run_id()
    log = JsonlLogger(default_log_dir(REPO_ROOT) / f"verify-pin-{run_id}.jsonl",
                      phase="phase0", run_id=run_id)
    checks: List[Dict[str, object]] = []

    def record(name: str, passed: bool, **detail: object) -> None:
        checks.append({"check": name, "passed": passed, **detail})
        log.log(name, result="ok" if passed else "fail", level="INFO" if passed else "ERROR",
                **detail)

    if not args.offline:
        for name, key in (("official-tag", "official_repository"),
                          ("mirror-tag", "mirror_repository")):
            result = ls_remote(pin[key], pin["tag"])
            record(name, result["commit"] == pin["commit"], repository=pin[key], **result)
        if pin.get("stable_listing_url") and pin.get("release_version"):
            body = http_get(pin["stable_listing_url"])
            newest = newest_stable(body) if body else None
            record("newest-stable-release", newest == pin["release_version"],
                   url=pin["stable_listing_url"], newest_listed=newest,
                   pinned_release=pin["release_version"],
                   listing_sha256=hashlib.sha256(body).hexdigest() if body else None)
        if pin.get("source_listing_url"):
            body = http_get(pin["source_listing_url"])
            wanted = pin["tag"].split("-", 1)[-1] + ".tar.xz"
            wanted = "libreoffice-" + wanted
            present = bool(body) and f'href="{wanted}"'.encode("ascii") in body
            record("release-source-archive-name", present, url=pin["source_listing_url"],
                   expected_file=wanted,
                   listing_sha256=hashlib.sha256(body).hexdigest() if body else None)
    if args.checkout is not None:
        command = ["git", "-C", str(args.checkout), "rev-parse", "HEAD"]
        done = subprocess.run(command, capture_output=True, text=True, timeout=60)
        head = done.stdout.strip()
        record("checkout-head", head == pin["commit"], command=" ".join(command), head=head)
    if args.release_archive is not None:
        release = pin.get("release", {})
        actual = sha256_file(args.release_archive) if args.release_archive.is_file() else None
        expected = release.get("sha256")
        published = None
        if not args.offline and release.get("sha256_url"):
            published = published_sha256(release["sha256_url"])
        passed = actual is not None and actual == expected and \
            (args.offline or published == expected)
        record("release-archive-sha256", passed, file=args.release_archive.name, actual=actual,
               pinned=expected, published_by_origin=published,
               published_url=release.get("sha256_url"))
    if args.engine_home is not None:
        versionrc = args.engine_home / "program" / "versionrc"
        text = versionrc.read_text(encoding="utf-8", errors="replace") if versionrc.is_file() else ""
        match = _BUILDID_RE.search(text)
        buildid = match.group(1) if match else None
        record("release-buildid", buildid == pin["commit"], file=str(versionrc), buildid=buildid)

    passed = bool(checks) and all(item["passed"] for item in checks)
    evidence = {"pin": pin, "verified_at": dt.datetime.now(dt.timezone.utc).isoformat(
        timespec="seconds"), "run_id": run_id, "checks": checks, "all_passed": passed}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"all_passed": passed, "checks": {c["check"]: c["passed"] for c in checks},
                      "out": str(args.out), "log": str(log.path)}))
    return EXIT_OK if passed else EXIT_CHECK_FAILED


if __name__ == "__main__":
    sys.exit(run())
