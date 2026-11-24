# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Command-line flows: fetch orchestration, manifest building, derivation."""

import hashlib
import json
from pathlib import Path

import pytest

from tools.common import netfetch
from tools.corpus import build_manifest, derive, gen_seed, manifest
from tools.ledger import fetch_externals

SUM_A, SUM_B, SUM_C = "a" * 64, "b" * 64, "c" * 64
COMMIT = "861effc5289d539f15c4c18d1ba8579ffd78728b"


# -------------------------------------------------------- fetch_externals

def _download_lst(tmp_path):
    path = tmp_path / "download.lst"
    path.write_text(f"GOOD_SHA256SUM := {SUM_A}\nGOOD_TARBALL := good-1.0.tar.gz\n"
                    f"BAD_SHA256SUM := {SUM_B}\nBAD_TARBALL := bad-1.0.tar.gz\n"
                    f"DOWN_SHA256SUM := {SUM_C}\nDOWN_TARBALL := down-1.0.tar.gz\n",
                    encoding="utf-8")
    return path


def _fake_fetch(url, dest, expected, timeout=0, retries=0, **_kwargs):
    if "bad-" in url:
        raise netfetch.ChecksumMismatch(url, expected, "f" * 64)
    if "down-" in url:
        raise netfetch.FetchError("giving up on " + url)
    return netfetch.FetchResult(Path(dest), expected, 10, "downloaded", 1)


def test_fetch_externals_reports_every_outcome_and_exit_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SUITE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(fetch_externals, "fetch_verified", _fake_fetch)
    lst = _download_lst(tmp_path)
    summary = tmp_path / "summary.json"
    base = ["--download-lst", str(lst), "--dest", str(tmp_path / "dl"), "--summary",
            str(summary), "--jobs", "2"]
    assert fetch_externals.run(base) == 4          # a checksum mismatch outranks the rest
    data = json.loads(summary.read_text())
    assert data["by_status"] == {"checksum-mismatch": 1, "downloaded": 1, "network-error": 1}
    by_key = {item["key"]: item for item in data["items"]}
    assert by_key["BAD"]["actual_sha256"] == "f" * 64
    assert by_key["GOOD"]["url"].endswith("/src/good-1.0.tar.gz")
    assert fetch_externals.run(base + ["--only", "GOOD", "DOWN"]) == 3
    assert fetch_externals.run(base + ["--only", "GOOD"]) == 0
    logs = list((tmp_path / "logs").glob("fetch-externals-*.jsonl"))
    assert len(logs) == 3
    capsys.readouterr()


# --------------------------------------------------------- build_manifest

def _selection(tmp_path, tree):
    (tree / "sw" / "qa").mkdir(parents=True)
    (tree / "sw" / "qa" / "t.docx").write_bytes(b"PK\x03\x04 pretend package")
    path = tmp_path / "selection.json"
    path.write_text(json.dumps({"files": [{
        "path": "sw/qa/t.docx", "format": "docx", "app": "writer", "features": ["tables"],
        "producer": "Some Producer", "evidence": "package-xml"}]}))
    return path


def test_build_manifest_combines_the_three_sources(tmp_path, capsys):
    tree = tmp_path / "tree"
    selection = _selection(tmp_path, tree)
    self_dir = build_manifest.REPO_ROOT / "corpus" / "self"
    out = tmp_path / "MANIFEST.csv"
    code = build_manifest.run([
        "--upstream-tree", str(tree), "--upstream-tag", "v1", "--upstream-commit", COMMIT,
        "--selection", str(selection), "--self-dir", str(self_dir),
        "--derived-dir", str(tmp_path / "no-derived"), "--out", str(out)])
    assert code == 0
    entries = manifest.load_manifest(out)
    assert len(entries) == len(gen_seed.CATALOGUE) + 1
    upstream = [entry for entry in entries if entry.source == "upstream-test-file"][0]
    assert upstream.origin == f"v1@{COMMIT}" and upstream.licence.startswith("NOASSERTION")
    assert upstream.sha256 == hashlib.sha256(b"PK\x03\x04 pretend package").hexdigest()
    assert manifest.verify_entry(upstream, build_manifest.REPO_ROOT, tree).is_file()
    capsys.readouterr()


def test_build_manifest_refuses_stale_or_missing_inputs(tmp_path, capsys):
    tree = tmp_path / "tree"
    selection = _selection(tmp_path, tree)
    base = ["--upstream-tree", str(tree), "--upstream-tag", "v1", "--upstream-commit", COMMIT,
            "--selection", str(selection), "--out", str(tmp_path / "M.csv")]
    # self-authored directory that is not what the generator produces
    stale = tmp_path / "self"
    stale.mkdir()
    for name, data in gen_seed.generate().items():
        (stale / name).write_bytes(data)
    (stale / "seed-ascii.txt").write_bytes(b"edited by hand")
    # the self directory must live inside the repository for relative paths; emulate by
    # calling the row builder directly
    with pytest.raises(manifest.ManifestError, match="differs from the generator"):
        build_manifest.self_rows(stale)
    assert build_manifest.run(base[:-2] + ["--upstream-commit", "abc"]) == 2
    assert build_manifest.run(["--upstream-tree", str(tmp_path / "none")] + base[2:]) == 2
    (tree / "sw" / "qa" / "t.docx").unlink()
    assert build_manifest.run(base) == 4           # listed upstream file is gone
    capsys.readouterr()


def test_derived_rows_check_hashes(tmp_path):
    derived = build_manifest.REPO_ROOT / "corpus" / "derived"
    rows = build_manifest.derived_rows(derived)
    assert len(rows) == len(derive.PLAN)
    assert all(row["source"] == "derived" and row["licence"] == "MPL-2.0" for row in rows)
    assert all("filter '" in row["origin"] for row in rows)
    assert build_manifest.derived_rows(tmp_path) == []   # no index file, no rows


# ----------------------------------------------------------------- derive

def test_derive_plan_uses_filter_names_from_the_pinned_tree_and_own_sources():
    filters = {plan[2] for plan in derive.PLAN}
    assert filters == {"MS Word 97", "MS PowerPoint 97"}
    for source, extension, _filter, app, tags in derive.PLAN:
        assert source in gen_seed.CATALOGUE          # only our own files are converted
        assert gen_seed.CATALOGUE[source][1] == app and extension in ("doc", "ppt")
        assert all(tag for tag in tags.split(";"))


def test_derive_cli_errors(tmp_path, capsys):
    assert derive.run(["--engine-home", str(tmp_path), "--self-dir",
                       str(tmp_path / "missing")]) == 2
    (tmp_path / "self").mkdir()
    assert derive.run(["--engine-home", str(tmp_path / "no-engine"), "--self-dir",
                       str(tmp_path / "self"), "--out", str(tmp_path / "out")]) == 3
    assert not (tmp_path / "out").exists()         # nothing written when the engine is absent
    capsys.readouterr()
