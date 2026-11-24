#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Build ``compliance/licence-ledger.csv``.

Rows come from two places:

* every external in the upstream ``download.lst`` -- licence identifiers
  are recognised mechanically in the licence files that
  ``tools.ledger.extract_licences`` copied out of each archive, plus a
  bounded sample of source-file headers read straight from the archive;
* ``compliance/ledger-static.csv`` -- hand-maintained rows for things
  that are not in ``download.lst`` (the upstream core itself, tool
  chain, test tools, corpus inputs ...).

The tool only ever writes ``allow`` or ``needs-review`` for scanned
rows (see ``tools.ledger.policy``).  Verdicts in the static file are
written by a person and copied unchanged.

Exit codes: 0 ok; 2 bad input; 3 an inventory is missing.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from tools.common.jsonlog import JsonlLogger, default_log_dir, new_run_id
from tools.common.metrics import update_metrics
from tools.ledger import classify, extract_licences
from tools.ledger.download_lst import DownloadLstError, External, load
from tools.ledger.policy import VERDICTS, Policy, PolicyError, load_policy

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_MISSING = 3

BASIS_FILE = "licence file"
BASIS_FONT = "font name table (the font's own licence statement)"
BASIS_README = "README / package metadata only"
BASIS_HEADERS = "source-file headers only"
#: Only these kinds of evidence may lead to an automatic "allow".
STRONG_BASIS = (BASIS_FILE, BASIS_FONT)

REPO_ROOT = Path(__file__).resolve().parents[2]
COLUMNS = ("id", "name", "version", "source_url", "sha256", "spdx", "spdx_basis",
           "licence_files", "category", "usage", "obligations", "verdict", "review_notes")
SOURCE_SUFFIXES = (".c", ".h", ".cc", ".cpp", ".cxx", ".hxx", ".hpp", ".hh", ".py", ".java",
                   ".js", ".rs", ".pl", ".pm", ".y", ".l", ".m", ".mm", ".cs", ".go", ".idl",
                   ".xsl", ".ipp", ".inl")
HEADER_SAMPLE = 60
HEADER_BYTES = 4096
_HASH_PREFIX = re.compile(r"^[0-9a-f]{32,64}-")
_ARCHIVE_SUFFIX = re.compile(r"\.(tar\.(gz|xz|bz2)|tgz|zip|jar|nupkg|ttf)$", re.I)
_COMMIT = re.compile(r"^(?P<name>.+?)-(?P<version>[0-9a-f]{40}.*)$")
_VERSION = re.compile(r"^(?P<name>.+?)[-_.](?P<version>v?\d.*)$")
_FETCH_OPTIONAL = re.compile(r"fetch_Optional,(\w+),(\w+?)_(TARBALL|JAR|TTF)\)")
_FETCH_WNT = re.compile(r"\$\(if \$\(filter WNT,\$\(OS\)\),(\w+?)_TARBALL\)")


def split_name_version(filename: str) -> Tuple[str, str]:
    """Best-effort ``(name, version)`` from an archive file name."""
    stem = _ARCHIVE_SUFFIX.sub("", _HASH_PREFIX.sub("", filename))
    for pattern in (_COMMIT, _VERSION):
        match = pattern.match(stem)
        if match:
            return match.group("name"), match.group("version")
    head, _, tail = stem.rpartition("-")
    if head and re.match(r"^[0-9a-f]{7,}$", tail):
        return head, tail
    return stem, "UNKNOWN (not in the file name; see the archive)"


def fetch_tokens(makefile_fetch: str) -> Dict[str, str]:
    """``KEY -> BUILD_TYPE token`` as written in upstream ``Makefile.fetch``."""
    tokens = {key: token for token, key, _kind in _FETCH_OPTIONAL.findall(makefile_fetch)}
    for key in _FETCH_WNT.findall(makefile_fetch):
        tokens.setdefault(key, "(unconditional when OS=WNT)")
    return tokens


def sample_headers(archive: Path) -> Dict[str, object]:
    """Read the first bytes of a bounded number of source files in an archive."""
    kind = extract_licences.archive_kind(archive.name)
    result: Dict[str, object] = {"sampled": 0, "or_later": 0, "spdx_tags": [], "choice": "",
                                 "licences": {}, "quotes": {}}
    if kind not in ("tar", "zip"):
        return result
    iterator = (extract_licences._iter_tar(archive) if kind == "tar"
                else extract_licences._iter_zip(archive))
    tags: List[str] = []
    try:
        for name, _size, reader in iterator:
            if not name.lower().endswith(SOURCE_SUFFIXES):
                continue
            text = reader(HEADER_BYTES)[:HEADER_BYTES].decode("utf-8", "replace")
            result["sampled"] = int(result["sampled"]) + 1
            if classify.states_or_later(text):
                result["or_later"] = int(result["or_later"]) + 1
            for tag in classify.spdx_tags(text):
                if tag not in tags:
                    tags.append(tag)
            for detection in classify.detect(text, notices=True):
                tally: Dict[str, int] = result["licences"]  # type: ignore[assignment]
                tally[detection.spdx] = tally.get(detection.spdx, 0) + 1
                result["quotes"].setdefault(  # type: ignore[union-attr]
                    detection.spdx, f"{name}: {detection.quote}")
            if not result["choice"]:
                result["choice"] = classify.states_choice(text) or ""
            if int(result["sampled"]) >= HEADER_SAMPLE:
                break
    except extract_licences.ArchiveError:
        result["error"] = "archive could not be sampled"
    result["spdx_tags"] = tags[:8]
    return result


def scan_external(item: External, licences_dir: Path, tarballs: Path) -> Dict[str, object]:
    """Recognise licences for one external from its extracted files."""
    base = licences_dir / item.key
    inventory_path = base / "_inventory.json"
    if not inventory_path.is_file():
        raise FileNotFoundError(str(inventory_path))
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    found: List[Tuple[str, str, str, str]] = []  # (spdx, member, sha256, quote)
    or_later_statement = False
    choice = ""
    readme_found: List[Tuple[str, str, str, str]] = []
    font_found: List[Tuple[str, str, str, str]] = []
    for candidate in inventory.get("candidates", []):
        if not candidate.get("copied"):
            continue
        text = (base / candidate["local"]).read_text(encoding="utf-8", errors="replace")
        detections = classify.detect(text, notices=candidate["role"] == "readme")
        target = found if candidate["role"] == "licence" else readme_found
        for detection in detections:
            target.append((detection.spdx, candidate["member"], candidate["sha256"],
                           detection.quote))
        if candidate["role"] == "readme" or candidate["depth"] <= 1:
            or_later_statement = or_later_statement or classify.states_or_later(text) and \
                candidate["role"] == "readme"
            choice = choice or (classify.states_choice(text) or "")
    # Fonts: the licence is stated in the OpenType name table.
    for font_file in ("_fonts.json", "_font_name_table.json"):
        path = base / font_file
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        groups = data if font_file == "_fonts.json" else [{"member": item.filename,
                                                            "name_records": data}]
        for group in groups:
            text = "\n".join(record["text"] for record in group.get("name_records", [])
                             if record.get("name_id") in (13, 14))
            for detection in classify.detect(text):
                font_found.append((detection.spdx, f"{group['member']} (name table)",
                                   group.get("sha256", ""), detection.quote))
            lowered = text.lower()
            if "apache license, version 2.0" in lowered:
                font_found.append(("Apache-2.0", f"{group['member']} (name table)",
                                   group.get("sha256", ""), text.splitlines()[0][:200]))
            if "open font license" in lowered and ("1.1" in lowered or "ofl" in lowered):
                font_found.append(("OFL-1.1", f"{group['member']} (name table)",
                                   group.get("sha256", ""), text.splitlines()[0][:200]))
    basis = BASIS_FILE
    if not found and font_found:
        found, basis = font_found, BASIS_FONT
    elif not found and readme_found:
        found, basis = readme_found, BASIS_README
    headers = sample_headers(tarballs / item.filename)
    if not found and headers["licences"]:
        sampled = headers["sampled"]
        found = [(spdx, f"{headers['quotes'][spdx].split(': ', 1)[0]} (source header)", "",  # type: ignore[index]
                  headers["quotes"][spdx].split(": ", 1)[-1])  # type: ignore[index]
                 for spdx in headers["licences"]]  # type: ignore[union-attr]
        basis = f"{BASIS_HEADERS} (bounded sample of {sampled} files)"
    return {"inventory": inventory, "found": found, "basis": basis, "headers": headers,
            "or_later_statement": or_later_statement, "choice": choice}


def external_row(item: External, scan: Dict[str, object], policy: Policy,
                 tokens: Dict[str, str], usage: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    found: List[Tuple[str, str, str, str]] = scan["found"]  # type: ignore[assignment]
    headers: Dict[str, object] = scan["headers"]  # type: ignore[assignment]
    or_later = bool(scan["or_later_statement"]) or int(headers.get("or_later", 0)) > 0
    licences: List[str] = []
    for spdx, _member, _sha, _quote in found:
        full = classify.gnu_suffix(spdx, or_later)
        if full not in licences:
            licences.append(full)
    verdict, reason = policy.verdict(licences)
    header_extra = sorted(
        full for full in (classify.gnu_suffix(spdx, or_later)
                          for spdx in headers.get("licences", {}))  # type: ignore[union-attr]
        if full not in licences and not policy.is_allowed(full))
    if verdict == "allow" and scan["basis"] not in STRONG_BASIS:
        verdict = "needs-review"
        reason = (f"licence known from {scan['basis']}; no licence file in the archive "
                  "confirms it")
    elif verdict == "allow" and header_extra:
        verdict = "needs-review"
        reason = ("licence file is pre-approved, but sampled source headers also carry: "
                  + ", ".join(header_extra))
    name, version = split_name_version(item.filename)
    inventory: Dict[str, object] = scan["inventory"]  # type: ignore[assignment]

    files: List[str] = []
    quotes: List[str] = []
    for spdx, member, sha, quote in found:
        entry = f"{member}@{sha[:12]}" if sha else member
        if entry not in files:
            files.append(entry)
        if quote and len(quotes) < 3:
            quotes.append(f'{spdx}: "{quote}"')
    notes: List[str] = [reason]
    if len(licences) > 1:
        notes.append("several licence texts found; AND/OR combination not determined")
    if any(spdx in classify.GNU_IDS for spdx, *_ in found):
        notes.append(f"or-later wording in {headers.get('or_later', 0)} of "
                     f"{headers.get('sampled', 0)} sampled source headers"
                     + ("; stated in README" if scan["or_later_statement"] else ""))
    header_ids = {classify.gnu_suffix(spdx, or_later): count
                  for spdx, count in headers.get("licences", {}).items()}  # type: ignore[union-attr]
    extra = sorted(spdx for spdx in header_ids if spdx not in licences)
    if extra:
        notes.append("also seen in sampled source headers (not in the verdict): "
                     + ", ".join(f"{spdx} x{header_ids[spdx]}" for spdx in extra))
    if "X11" in licences:
        notes.append("MIT-style text with an 'Except as contained in this notice' name-use "
                     "clause; closest SPDX id is X11, confirm the exact identifier")
    if headers.get("spdx_tags"):
        notes.append("SPDX tags in sampled headers: " + ", ".join(headers["spdx_tags"]))  # type: ignore[arg-type]
    if scan["choice"]:
        notes.append(f'choice wording: "{scan["choice"]}"')
    skipped = int(inventory.get("licence_candidates_not_copied", 0) or 0)
    if skipped:
        notes.append(f"{skipped} deeper licence-named file(s) not read (bundled sub-components?)")
    if quotes:
        notes.append("evidence " + " / ".join(quotes))

    info = usage.get(item.key, {})
    token = tokens.get(item.key, "")
    if item.key.startswith("FONT_") or item.kind == "TTF":
        category = info.get("category", "font-asset")
    elif item.kind == "JAR":
        category = "test-only"
    else:
        category = info.get("category", "undetermined")
    usage_text = (f"upstream build input; BUILD_TYPE gate: {token or 'UNKNOWN'}"
                  + (f"; {info['summary']}" if info.get("summary") else
                     "; whether it is built and shipped for our Windows configuration is "
                     "confirmed from config_host.mk in Phase 1"))
    return {
        "id": "ext-" + item.key.lower().replace("_", "-"),
        "name": f"{name} ({item.variable})", "version": version, "source_url": item.url,
        "sha256": item.sha256,
        "spdx": "; ".join(licences) if licences else "NOASSERTION",
        "spdx_basis": str(scan["basis"]) if licences else "nothing recognised",
        "licence_files": " | ".join(files[:5]) + (f" (+{len(files) - 5} more)"
                                                   if len(files) > 5 else ""),
        "category": category, "usage": usage_text,
        "obligations": policy.obligations_for(licences) if licences else "UNKNOWN",
        "verdict": verdict, "review_notes": "; ".join(note for note in notes if note),
    }


def read_static(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{path}: header must be exactly {','.join(COLUMNS)}")
        rows = [dict(row) for row in reader]
    for number, row in enumerate(rows, 2):
        if row["verdict"] not in VERDICTS:
            raise ValueError(f"{path}:{number}: verdict must be one of {VERDICTS}")
        if not row["id"] or not row["name"]:
            raise ValueError(f"{path}:{number}: id and name are required")
    return rows


def write_ledger(path: Path, rows: List[Dict[str, str]]) -> None:
    ids = [row["id"] for row in rows]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise ValueError(f"duplicate ledger id(s): {', '.join(duplicates)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in sorted(rows, key=lambda item: item["id"]):
            writer.writerow({key: row.get(key, "") for key in COLUMNS})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--upstream-tree", required=True, type=Path)
    parser.add_argument("--licences", required=True, type=Path,
                        help="output directory of tools.ledger.extract_licences")
    parser.add_argument("--tarballs", required=True, type=Path)
    parser.add_argument("--policy", type=Path,
                        default=REPO_ROOT / "compliance" / "licence-policy.json")
    parser.add_argument("--static", type=Path,
                        default=REPO_ROOT / "compliance" / "ledger-static.csv")
    parser.add_argument("--usage", type=Path,
                        default=REPO_ROOT / "compliance" / "evidence" / "external-usage.json")
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "compliance" / "licence-ledger.csv")
    parser.add_argument("--metrics", type=Path,
                        default=REPO_ROOT / "reports" / "build-metrics.json")
    return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    download_lst = args.upstream_tree / "download.lst"
    makefile_fetch = args.upstream_tree / "Makefile.fetch"
    for path in (download_lst, makefile_fetch):
        if not path.is_file():
            print(f"error: not found: {path}", file=sys.stderr)
            return EXIT_USAGE
    for directory in (args.licences, args.tarballs):
        if not directory.is_dir():
            print(f"error: not a directory: {directory}", file=sys.stderr)
            return EXIT_USAGE
    try:
        policy = load_policy(args.policy)
        items = load(download_lst)
        static_rows = read_static(args.static)
        usage = json.loads(args.usage.read_text(encoding="utf-8")) if args.usage.is_file() else {}
    except (PolicyError, DownloadLstError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    run_id = new_run_id()
    log = JsonlLogger(default_log_dir(REPO_ROOT) / f"build-ledger-{run_id}.jsonl",
                      phase="phase0", run_id=run_id)
    tokens = fetch_tokens(makefile_fetch.read_text(encoding="utf-8"))
    rows: List[Dict[str, str]] = []
    with log.timed("scan_externals", count=len(items)) as ctx:
        for item in items:
            try:
                scan = scan_external(item, args.licences, args.tarballs)
            except FileNotFoundError as exc:
                print(f"error: inventory missing: {exc}; run tools.ledger.extract_licences",
                      file=sys.stderr)
                return EXIT_MISSING
            rows.append(external_row(item, scan, policy, tokens, usage))
        ctx["rows"] = len(rows)
    rows.extend(static_rows)
    try:
        write_ledger(args.out, rows)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    by_verdict: Dict[str, int] = {verdict: 0 for verdict in VERDICTS}
    for row in rows:
        by_verdict[row["verdict"]] += 1
    update_metrics(args.metrics, "ledger", {"rows": len(rows), "by_verdict": by_verdict,
                                            "scanned_externals": len(items),
                                            "static_rows": len(static_rows)})
    log.log("finish", result="ok", rows=len(rows), by_verdict=by_verdict)
    print(json.dumps({"rows": len(rows), "by_verdict": by_verdict, "out": str(args.out),
                      "log": str(log.path)}))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(run())
