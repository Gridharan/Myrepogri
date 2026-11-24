# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Numbers quoted in the documents must match the reports they cite.

The first draft of the Phase 0 documents drifted from the data after the
reports were regenerated.  These tests fail when that happens again.
"""

import csv
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REPORT = json.loads((REPO / "reports" / "fidelity.json").read_text(encoding="utf-8"))
SUMMARY = REPORT["summary"]
MATRIX = (REPO / "docs" / "parity-matrix.md").read_text(encoding="utf-8")
GATE = (REPO / "docs" / "phase0-gate-report.md").read_text(encoding="utf-8")
LEDGER = list(csv.DictReader((REPO / "compliance" / "licence-ledger.csv").open(
    encoding="utf-8", newline="")))


def test_parity_matrix_cites_the_current_run_and_overall_numbers():
    assert REPORT["run_id"] in MATRIX
    assert f"criteria version {REPORT['settings']['criteria_version']}" in MATRIX
    overall = f"{SUMMARY['pass']} pass, {SUMMARY['partial']} partial, {SUMMARY['fail']} fail"
    assert overall in MATRIX and overall.replace(" pass, ", " pass, ") in GATE.replace("and ", "")
    assert f"({SUMMARY['pass_rate'] * 100:.1f} %)" in MATRIX


def test_parity_matrix_feature_counts_match_the_report():
    cited = re.findall(r"`([a-z][a-z-]*)` (\d+)/(\d+)/(\d+)", MATRIX)
    assert len(cited) >= 25
    for tag, passed, partial, failed in cited:
        got = SUMMARY["by_feature"][tag]
        assert (got["pass"], got["partial"], got["fail"]) == (int(passed), int(partial),
                                                               int(failed)), tag


def test_parity_matrix_format_counts_match_the_report():
    line = re.search(r"Writer formats\n?.*?odp \d+/\d+\)", MATRIX, flags=re.S).group(0)
    cited = dict((fmt, (int(a), int(b))) for fmt, a, b in
                 re.findall(r"\b(docx|docm|doc|dotx|rtf|odt|txt|pptx|ppt|ppsx|potx|pptm|odp) "
                            r"(\d+)/(\d+)", line))
    assert set(cited) == set(SUMMARY["by_format"])
    for fmt, (passed, partial) in cited.items():
        got = SUMMARY["by_format"][fmt]
        assert (got["pass"], got["partial"]) == (passed, partial), fmt
    for app, label in (("writer", "Writer formats"), ("impress", "Presentation formats")):
        got = SUMMARY["by_app"][app]
        assert re.search(rf"{label}\s+{got['pass']} / {got['partial']} / {got['fail']}", MATRIX)


def test_own_files_subset_matches_the_report():
    own = [row for row in REPORT["files"] if row["source"] != "upstream-test-file"]
    counts = {status: sum(1 for row in own if row["status"] == status)
              for status in ("pass", "partial", "fail")}
    text = f"{counts['pass']} pass,\n{counts['partial']} partial, {counts['fail']} fail"
    assert len(own) == 18 and text in MATRIX


def test_gate_report_ledger_numbers_match_the_ledger():
    total = len(LEDGER)
    allow = sum(1 for row in LEDGER if row["verdict"] == "allow")
    review = sum(1 for row in LEDGER if row["verdict"] == "needs-review")
    assert f"{total} rows: {allow} allow, {review} needs-review, 0 reject" in GATE
    assert f"has {total} rows, of which {review}" in GATE.replace("\n", " ")
    groups = {"ext": "Upstream externals", "core": "Upstream core", "tool": "Tools used",
              "corpus": "Corpus inputs", "planned": "Planned tool chain"}
    for prefix, label in groups.items():
        rows = [row for row in LEDGER if row["id"].split("-")[0] == prefix]
        ok = sum(1 for row in rows if row["verdict"] == "allow")
        line = next(line for line in GATE.splitlines() if line.startswith(f"| {label}"))
        assert line.rstrip().endswith(f"| {len(rows)} | {ok} | {len(rows) - ok} |"), label
    risk = (REPO / "docs" / "risk-register.md").read_text(encoding="utf-8")
    assert f"**{review} of {total} ledger rows are `needs-review`.**" in risk


def test_evidence_logs_named_in_the_gate_report_exist():
    logs = REPO / "compliance" / "evidence" / "logs"
    for name in re.findall(r"`([a-z-]+-\d{8}T\d{6}Z-[0-9a-f]{8}\.jsonl)`", GATE):
        assert (logs / name).is_file(), name
    for pattern in ("pytest-*.txt", "check-ledger-*.txt", "build-ledger-*.jsonl"):
        assert list(logs.glob(pattern)), pattern
    assert REPORT["run_id"] in GATE
