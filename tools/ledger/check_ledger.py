#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Gate check for ``compliance/licence-ledger.csv``.

Fails when a row is malformed, when a required external has no row, or
when any row's verdict is not ``allow`` (the CI rule of the brief).
``--report-only`` prints the same findings but exits 0, for use before
the owner has reviewed the open rows.

Exit codes: 0 ledger clean (or ``--report-only``); 2 bad input;
8 ledger not clean.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from tools.ledger.build_ledger import COLUMNS
from tools.ledger.download_lst import DownloadLstError, load
from tools.ledger.policy import VERDICTS, Policy, PolicyError, load_policy

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NOT_CLEAN = 8

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ("id", "name", "version", "source_url", "spdx", "usage", "obligations", "verdict")


UNSET = ("", "UNKNOWN", "NOASSERTION")


def check(rows: List[Dict[str, str]], required_ids: Sequence[str] = (),
          policy: Optional[Policy] = None,
          required_sha256: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    """Return findings for a parsed ledger.

    With ``policy``, an ``allow`` row must name only pre-approved licences
    (an owner decision on anything else has to be recorded as a policy
    change, not typed into a verdict cell).  With ``required_sha256``, the
    row of each listed item must carry exactly that archive checksum.
    """
    problems: List[str] = []
    if not rows:
        problems.append("the ledger has no rows")
    seen = set()
    by_verdict: Dict[str, int] = {verdict: 0 for verdict in VERDICTS}
    not_allowed: List[str] = []
    for number, row in enumerate(rows, 2):
        identifier = row.get("id", "")
        for column in REQUIRED:
            if not (row.get(column) or "").strip():
                problems.append(f"line {number} ({identifier}): empty {column}")
        if identifier in seen:
            problems.append(f"line {number}: duplicate id {identifier}")
        seen.add(identifier)
        verdict = row.get("verdict", "")
        if verdict not in VERDICTS:
            problems.append(f"line {number} ({identifier}): verdict {verdict!r} is not one of "
                            f"{', '.join(VERDICTS)}")
            continue
        by_verdict[verdict] += 1
        if verdict != "allow":
            not_allowed.append(identifier)
        else:
            licences = [item.strip() for item in (row.get("spdx") or "").split(";")
                        if item.strip()]
            if not licences or any(item.split(" ")[0] in UNSET for item in licences):
                problems.append(f"line {number} ({identifier}): allow without a licence id")
            elif policy is not None:
                outside = [item for item in licences if not policy.is_allowed(item)]
                if outside:
                    problems.append(f"line {number} ({identifier}): allow, but not "
                                    f"pre-approved by the policy: {', '.join(outside)}")
        expected = (required_sha256 or {}).get(identifier)
        if expected and (row.get("sha256") or "").strip().lower() != expected:
            problems.append(f"line {number} ({identifier}): sha256 differs from download.lst")
    missing = sorted(set(required_ids) - seen)
    problems.extend(f"no ledger row for required item {identifier}" for identifier in missing)
    return {"rows": len(rows), "by_verdict": by_verdict, "not_allowed": sorted(not_allowed),
            "problems": problems, "clean": not problems and not not_allowed}


def read_ledger(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"header must be exactly: {','.join(COLUMNS)}")
        return [dict(row) for row in reader]


def run(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", type=Path,
                        default=REPO_ROOT / "compliance" / "licence-ledger.csv")
    parser.add_argument("--download-lst", type=Path, default=None,
                        help="upstream download.lst: every entry must have a ledger row "
                             "with the same SHA-256")
    parser.add_argument("--policy", type=Path,
                        default=REPO_ROOT / "compliance" / "licence-policy.json")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.ledger.is_file():
        print(f"error: ledger not found: {args.ledger}", file=sys.stderr)
        return EXIT_USAGE
    required: List[str] = []
    checksums: Dict[str, str] = {}
    try:
        rows = read_ledger(args.ledger)
        policy = load_policy(args.policy)
        if args.download_lst is not None:
            for item in load(args.download_lst):
                identifier = "ext-" + item.key.lower().replace("_", "-")
                required.append(identifier)
                checksums[identifier] = item.sha256
    except (ValueError, OSError, DownloadLstError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    result = check(rows, required, policy, checksums)
    print(json.dumps({"rows": result["rows"], "by_verdict": result["by_verdict"],
                      "not_allowed": len(result["not_allowed"]),  # type: ignore[arg-type]
                      "problems": result["problems"], "clean": result["clean"]}))
    if result["clean"] or args.report_only:
        return EXIT_OK
    return EXIT_NOT_CLEAN


if __name__ == "__main__":
    sys.exit(run())
