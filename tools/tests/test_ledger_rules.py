# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Unit tests for licence recognition, policy verdicts, ledger build/check, pin."""

import csv
import hashlib
import io
import json
import subprocess
import tarfile

import pytest

from tools.ledger import build_ledger, check_ledger, classify, policy
from tools.ledger.download_lst import External
from tools.pin import verify_pin

# Title lines and key sentences as they appear in the public licence texts.
GPL3 = ("                    GNU GENERAL PUBLIC LICENSE\n                       Version 3, 29 June "
        "2007\n\n ... 13. Use with the GNU Affero General Public License. ...\n"
        "If this is what you want to do, use the GNU Lesser General\nPublic License instead of "
        "this License.\n")
LGPL3 = "                   GNU LESSER GENERAL PUBLIC LICENSE\n                       Version 3, 29 June 2007\n"
LGPL21 = "                  GNU LESSER GENERAL PUBLIC LICENSE\n                       Version 2.1, February 1999\n"
GPL2 = ("                    GNU GENERAL PUBLIC LICENSE\n                       Version 2, June 1991\n"
        " ... use the GNU Lesser General Public License instead of this License.\n")
MIT = ("Permission is hereby granted, free of charge, to any person obtaining a copy\n"
       "of this software ...\nThe above copyright notice and this permission notice shall be "
       'included\nTHE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS\n')
BSD3 = ("Redistribution and use in source and binary forms, with or without\nmodification ...\n"
        "2. Redistributions in binary form must reproduce the above copyright\n"
        "3. Neither name of copyright holders nor the names of its contributors\n"
        "may be used to endorse or promote products derived from this software\n")
BSD2 = ("Redistribution and use in source and binary forms, with or without\nmodification ...\n"
        "2. Redistributions in binary form must reproduce the above copyright notice\n")
MPL2 = ("Mozilla Public License Version 2.0\n==================================\n"
        '1.1. "Contributor"\n ... 1.12. "Secondary License" means either the GNU General Public '
        "License, Version 2.0, the GNU Lesser General Public License, Version 2.1, the GNU Affero "
        "General Public License, Version 3.0 ... version 1.1 or earlier of the License\n")


def ids(text, notices=False):
    return sorted(d.spdx for d in classify.detect(text, notices=notices))


@pytest.mark.parametrize("text,expected", [
    (GPL3, ["GPL-3.0"]),          # regression: was reported as LGPL-3.0
    (LGPL3, ["LGPL-3.0"]),
    (LGPL21, ["LGPL-2.1"]),
    (GPL2, ["GPL-2.0"]),
    (MIT, ["MIT"]),
    (BSD3, ["BSD-3-Clause"]),
    (BSD2, ["BSD-2-Clause"]),
    (MPL2, ["MPL-2.0"]),          # regression: was also reported as MPL-1.1
    (MIT + "Except as contained in this notice, the name of X shall not be used\n", ["X11"]),
    (BSD3 + "3. All advertising materials mentioning features or use of this software\n",
     ["BSD-4-Clause"]),
    ("This is free and unencumbered software released into the public domain.\n", ["Unlicense"]),
    ("Boost Software License - Version 1.0 - August 17th, 2003\n", ["BSL-1.0"]),
    ("SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007\n", ["OFL-1.1"]),
    ("Creative Commons Legal Code\n\nCC0 1.0 Universal\n", ["CC0-1.0"]),
    ("Just a readme with no licence wording at all.\n", []),
    (GPL3 + "\n\n" + LGPL3, ["GPL-3.0", "LGPL-3.0"]),
])
def test_detect_full_texts(text, expected):
    assert ids(text) == expected


def test_detect_returns_the_matching_line_as_evidence():
    (found,) = classify.detect("Copyright someone\n\n" + LGPL21)
    assert found.quote == "GNU LESSER GENERAL PUBLIC LICENSE"


def test_notices_only_when_asked():
    header = ("/* This Source Code Form is subject to the terms of the Mozilla Public\n"
              " * License, v. 2.0. If a copy of the MPL was not distributed ... */\n")
    assert ids(header) == []
    assert ids(header, notices=True) == ["MPL-2.0"]
    gnu = ("modify it under the terms of the GNU Lesser General Public License as published by "
           "the Free Software Foundation; either version 2.1 of the License, or (at your option) "
           "any later version.")
    assert ids(gnu, notices=True) == ["LGPL-2.1"]
    assert classify.states_or_later(gnu) and not classify.states_or_later(LGPL21)
    assert classify.gnu_suffix("LGPL-2.1", True) == "LGPL-2.1-or-later"
    assert classify.gnu_suffix("GPL-2.0", False) == "GPL-2.0-only"
    assert classify.gnu_suffix("MIT", True) == "MIT"


def test_gnu_notices_do_not_hide_each_other():
    # regression: a file-wide rule dropped the GPL notice whenever LGPL was mentioned too
    mixed = ("The library is under the GNU Lesser General Public License, version 2.1.\n"
             "The command-line tools are under the GNU General Public License as published by\n"
             "the Free Software Foundation; either version 2 of the License, or (at your\n"
             "option) any later version.\n")
    assert ids(mixed, notices=True) == ["GPL-2.0", "LGPL-2.1"]
    assert ids("under the GNU Lesser General Public License version 3", notices=True) == ["LGPL-3.0"]
    assert ids("GNU Library General Public License, version 2", notices=True) == ["LGPL-2.0"]
    assert ids("GNU Affero General Public License, version 3", notices=True) == ["AGPL-3.0"]
    assert ids("Files: *\nLicense: GPL-2\n\nFiles: lib/*\nLicense: LGPL-2.1+\n",
               notices=True) == ["GPL-2.0", "LGPL-2.1"]
    assert ids("GNU General Public License version 3", notices=True) == ["GPL-3.0"]
    assert ids("This mentions the General Public License without a version.", notices=True) == []


@pytest.mark.parametrize("text,expected", [
    # regression: spellings the first version missed
    ("License: GPL-2.0", ["GPL-2.0"]), ("License: AGPL-3.0", ["AGPL-3.0"]),
    ("under the terms of version 2 of the GNU General Public License as published", ["GPL-2.0"]),
    ("Licensed under the GNU General Public License v3.0.", ["GPL-3.0"]),
    ("GPLv3 or later", ["GPL-3.0"]), ("released under LGPLv2.1", ["LGPL-2.1"]),
    ("version 2.1 of the GNU Lesser General Public License", ["LGPL-2.1"]),
    ("distributed under the terms of GNU General Public License version 2 (see file GNU-GPL)",
     ["GPL-2.0"]),
    ("a) the GNU General Public License as published by the Free Software Foundation; either "
     "version 1, or (at your option) any later version", ["GPL-1.0"]),
    ("words like gplots, algpl1 and xgpl2 are not licences", []),
])
def test_gnu_notice_spellings(text, expected):
    assert ids(text, notices=True) == expected


@pytest.mark.parametrize("addition", [
    "The Software shall be used for Good, not Evil.",
    "The Software may be used for non-commercial purposes only.",
    "Commons Clause: the License does not grant to you the right to Sell the Software.",
    "This product includes software developed by the Example Project.",
])
def test_added_restrictions_are_reported(addition):
    # regression: a permissive text with an extra restriction was reported as plain MIT
    found = ids(MIT + addition + "\n")
    assert classify.RESTRICTED in found
    verdict, reason = POLICY.verdict(found)
    assert verdict == "needs-review" and classify.RESTRICTED in reason
    assert classify.RESTRICTED not in ids(MIT)


def test_spdx_expression_identifiers():
    assert classify.spdx_ids("GPL-3.0-or-later WITH Classpath-exception-2.0 OR (MIT AND Zlib)") \
        == ["GPL-3.0-or-later", "MIT", "Zlib"]
    assert classify.spdx_ids("") == []


def test_spdx_tags_and_choice_wording():
    text = "// SPDX-License-Identifier: MIT OR Apache-2.0 */\n// SPDX-License-Identifier: Zlib\n"
    assert classify.spdx_tags(text) == ["MIT OR Apache-2.0", "Zlib"]
    assert classify.states_choice("This library is dual licensed under MPL and LGPL.\n")
    assert classify.states_choice("plain text") is None


# ------------------------------------------------------------------ policy

POLICY = policy.Policy(frozenset({"MIT", "MPL-2.0", "LGPL-2.1-or-later"}), ("GPL-", "AGPL-"),
                       {"MIT": "keep notice"})


@pytest.mark.parametrize("licences,verdict,fragment", [
    (["MIT"], "allow", "pre-approved"),
    (["MIT", "MPL-2.0"], "allow", "pre-approved"),
    ([], "needs-review", "no licence text recognised"),
    (["GPL-3.0-only"], "needs-review", "ask first: GPL-3.0-only"),
    (["MIT", "GPL-2.0-or-later"], "needs-review", "choice or cumulative"),
    (["BSL-1.0"], "needs-review", "not pre-approved: BSL-1.0"),
])
def test_policy_verdicts(licences, verdict, fragment):
    got, reason = POLICY.verdict(licences)
    assert got == verdict and fragment in reason
    assert got != "reject"  # a tool never rejects on its own


def test_policy_obligations_and_loading(tmp_path):
    assert "UNKNOWN" in POLICY.obligations_for(["BSL-1.0"])
    assert POLICY.obligations_for(["MIT"]) == "MIT: keep notice"
    good = tmp_path / "p.json"
    good.write_text(json.dumps({"allow": ["MIT"], "ask_first_prefixes": ["GPL-"],
                                "obligations": {}}))
    assert policy.load_policy(good).is_allowed("MIT")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"allow": ["GPL-2.0-only"], "ask_first_prefixes": ["GPL-"],
                               "obligations": {}}))
    with pytest.raises(policy.PolicyError, match="both allowed and ask-first"):
        policy.load_policy(bad)
    bad.write_text("{}")
    with pytest.raises(policy.PolicyError):
        policy.load_policy(bad)


def test_repository_policy_matches_the_brief():
    loaded = policy.load_policy(build_ledger.REPO_ROOT / "compliance" / "licence-policy.json")
    for spdx in ("MPL-2.0", "Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib",
                 "OFL-1.1", "CC0-1.0", "LGPL-2.1-or-later", "LGPL-3.0-only"):
        assert loaded.is_allowed(spdx), spdx
    for spdx in ("GPL-2.0-only", "GPL-3.0-or-later", "AGPL-3.0-only"):
        assert loaded.is_ask_first(spdx) and not loaded.is_allowed(spdx)
    for spdx in ("BSL-1.0", "MPL-1.1", "BSD-4-Clause", "PSF-2.0"):
        assert not loaded.is_allowed(spdx)


# ------------------------------------------------------------ build ledger

@pytest.mark.parametrize("filename,name,version", [
    ("zlib-1.4.tar.xz", "zlib", "1.4"),
    ("boost_1_91_0.tar.xz", "boost", "1_91_0"),
    ("48d647fbd8ef8889e5a7f422c1bfda94-clucene-core-2.3.3.4.tar.gz", "clucene-core", "2.3.3.4"),
    ("phc-winner-argon2-20190702.tar.gz", "phc-winner-argon2", "20190702"),
    ("breakpad-b324760c7f53667af128a6b77b790323da04fcb9.tar.xz", "breakpad",
     "b324760c7f53667af128a6b77b790323da04fcb9"),
    ("NotoSans-v2.015.zip", "NotoSans", "v2.015"),
    ("python.3.12.8.nupkg", "python", "3.12.8"),
])
def test_split_name_version(filename, name, version):
    assert build_ledger.split_name_version(filename) == (name, version)


def test_fetch_tokens():
    text = ("\t\t$(call fetch_Optional,ZLIB,ZLIB_TARBALL) \\\n"
            "\t\t$(call fetch_Optional,CAIRO,PIXMAN_TARBALL) \\\n"
            "\t\t$(if $(filter WNT,$(OS)),TWAIN_DSM_TARBALL) \\\n"
            "\t\t$(call fetch_Optional,ODFVALIDATOR,ODFVALIDATOR_JAR) \\\n")
    assert build_ledger.fetch_tokens(text) == {
        "ZLIB": "ZLIB", "PIXMAN": "CAIRO", "ODFVALIDATOR": "ODFVALIDATOR",
        "TWAIN_DSM": "(unconditional when OS=WNT)"}


def _archive(tmp_path, key, members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, text in members:
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    data = buffer.getvalue()
    (tmp_path / "tarballs").mkdir(exist_ok=True)
    filename = f"{key.lower()}-1.0.tar.gz"
    (tmp_path / "tarballs" / filename).write_bytes(data)
    item = External(key, f"{key}_TARBALL", "TARBALL", filename,
                    hashlib.sha256(data).hexdigest(), f"https://example.invalid/{filename}")
    from tools.ledger import extract_licences
    inventory = extract_licences.process_archive(item, tmp_path / "tarballs", tmp_path / "lic")
    (tmp_path / "lic" / key).mkdir(parents=True, exist_ok=True)
    (tmp_path / "lic" / key / "_inventory.json").write_text(json.dumps(inventory))
    return item


def _row(tmp_path, key, members, pol=None):
    item = _archive(tmp_path, key, members)
    scan = build_ledger.scan_external(item, tmp_path / "lic", tmp_path / "tarballs")
    return build_ledger.external_row(item, scan, pol or POLICY, {key: key}, {})


def test_row_allow_needs_a_licence_file(tmp_path):
    row = _row(tmp_path, "GOOD", [("good-1.0/LICENSE", MIT), ("good-1.0/src/a.c", "int a;\n")])
    assert (row["spdx"], row["verdict"], row["spdx_basis"]) == ("MIT", "allow", "licence file")
    assert row["id"] == "ext-good" and "LICENSE@" in row["licence_files"]
    assert "BUILD_TYPE gate: GOOD" in row["usage"]


def test_row_from_headers_only_is_never_allowed(tmp_path):
    row = _row(tmp_path, "HDR", [("hdr-1.0/src/a.c", "/*\n" + MIT + "*/\nint a;\n")])
    assert row["spdx"] == "MIT" and row["verdict"] == "needs-review"
    assert "source-file headers only" in row["spdx_basis"]


def test_row_with_other_licence_in_headers_is_flagged(tmp_path):
    header = ("/* This program is free software; you can redistribute it under the terms of the "
              "GNU General Public License as published by the FSF; either version 2 of the "
              "License, or (at your option) any later version. */\n")
    row = _row(tmp_path, "MIX", [("mix-1.0/LICENSE", MIT), ("mix-1.0/tool.c", header)])
    assert row["verdict"] == "needs-review" and "GPL-2.0-or-later" in row["review_notes"]


def test_row_gpl_text_is_ask_first_and_nothing_found_is_noassertion(tmp_path):
    row = _row(tmp_path, "GPL", [("gpl-1.0/COPYING", GPL3)])
    assert row["spdx"] == "GPL-3.0-only" and row["verdict"] == "needs-review"
    assert "ask first" in row["review_notes"]
    empty = _row(tmp_path, "NONE", [("none-1.0/data.bin", "xx")])
    assert empty["spdx"] == "NOASSERTION" and empty["verdict"] == "needs-review"


def test_unrecognised_licence_file_blocks_allow(tmp_path):
    # regression: an archive whose own COPYING was not recognised got "allow" from a
    # bundled sub-directory's MIT file
    row = _row(tmp_path, "OLD", [("old-1.0/COPYING", "Licensed under the so-called Old Example terms.\n"),
                                 ("old-1.0/src/part/LICENSE", MIT)])
    assert row["spdx"] == "MIT" and row["verdict"] == "needs-review"
    assert "not recognised: old-1.0/COPYING" in row["review_notes"]
    # companions such as AUTHORS are not licence texts and do not block
    fine = _row(tmp_path, "FINE", [("fine-1.0/LICENSE", MIT), ("fine-1.0/AUTHORS", "A. Person\n")])
    assert fine["verdict"] == "allow"


def test_licence_file_that_points_elsewhere_and_spdx_tags(tmp_path):
    pointer = _row(tmp_path, "PTR", [("ptr-1.0/LICENSE", "This package is distributed under the "
                                      "terms of GNU General Public License version 2 (see file "
                                      "GNU-GPL)\n")])
    assert pointer["spdx"] == "GPL-2.0-only" and "ask first" in pointer["review_notes"]
    tagged = _row(tmp_path, "TAG", [("tag-1.0/LICENSE", MIT),
                                    ("tag-1.0/src/a.c", "// SPDX-License-Identifier: GPL-3.0-or-later\n")])
    assert tagged["verdict"] == "needs-review" and "GPL-3.0-or-later" in tagged["review_notes"]
    ok = _row(tmp_path, "TAGOK", [("tagok-1.0/LICENSE", MIT),
                                  ("tagok-1.0/src/a.c", "// SPDX-License-Identifier: MIT\n")])
    assert ok["verdict"] == "allow"


def test_stale_or_foreign_evidence_is_never_used(tmp_path):
    # regression: evidence extracted from one archive version was applied to another
    item = _archive(tmp_path, "LIB", [("lib-1.0/LICENSE", MIT)])
    other = External(item.key, item.variable, item.kind, "lib-2.0.tar.gz", "9" * 64, item.url)
    scan = build_ledger.scan_external(other, tmp_path / "lic", tmp_path / "tarballs")
    row = build_ledger.external_row(other, scan, POLICY, {}, {})
    assert scan["stale"] and row["spdx"] == "NOASSERTION" and row["verdict"] == "needs-review"
    assert "missing or does not belong" in row["review_notes"]


def test_usage_notes_are_reverified_against_the_tree(tmp_path):
    tree = tmp_path / "tree"
    (tree / "external").mkdir(parents=True)
    (tree / "external" / "Module.mk").write_text("line one\n\tgb_Helper_optional,ZLIB,zlib\n")
    good = {"path": "external/Module.mk", "line": 2, "quote": "gb_Helper_optional,ZLIB,zlib"}
    usage = tmp_path / "usage.json"
    usage.write_text(json.dumps({"entries": {
        "ZLIB": {"category": "runtime-shipped", "windows_default": "on", "linkage": "static",
                 "evidence": [good, {**good, "quote": "line one"}]},
        "FAKE": {"category": "runtime-shipped", "evidence": [good, {**good, "quote": "invented"}]},
        "ESCAPE": {"category": "x", "evidence": [{"path": "../usage.json", "line": 1,
                                                  "quote": "entries"}] * 2}}}))
    verified = build_ledger.verified_usage(usage, tree)
    assert set(verified) == {"ZLIB"} and "2 of 2 quotes" in verified["ZLIB"]["summary"]
    assert build_ledger.verified_usage(tmp_path / "absent.json", tree) == {}


def test_primary_licence_names():
    for name in ("x/LICENSE", "x/COPYING.LIB", "x/GNU-GPL", "x/LGPL-2.1", "x/licenses/zlib.txt",
                 "x/OFL.txt", "x/doc/hsqldb_license.html"):
        assert build_ledger.is_primary_licence_name(name), name
    for name in ("x/AUTHORS", "x/NOTICE", "x/CREDITS", "x/FONTLOG.txt", "x/README.md"):
        assert not build_ledger.is_primary_licence_name(name), name


def test_write_ledger_rejects_duplicates_and_static_validation(tmp_path):
    row = {column: "x" for column in build_ledger.COLUMNS}
    row["verdict"] = "allow"
    with pytest.raises(ValueError, match="duplicate"):
        build_ledger.write_ledger(tmp_path / "l.csv", [dict(row), dict(row)])
    static = tmp_path / "static.csv"
    with static.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=build_ledger.COLUMNS)
        writer.writeheader()
        writer.writerow({**row, "verdict": "maybe"})
    with pytest.raises(ValueError, match="verdict"):
        build_ledger.read_static(static)
    assert build_ledger.read_static(tmp_path / "absent.csv") == []


# ------------------------------------------------------------ check ledger

def test_check_ledger_findings():
    base = {column: "x" for column in build_ledger.COLUMNS}
    rows = [{**base, "id": "a", "verdict": "allow"},
            {**base, "id": "b", "verdict": "needs-review"},
            {**base, "id": "c", "verdict": "allow", "spdx": ""},
            {**base, "id": "a", "verdict": "allow"},
            {**base, "id": "d", "verdict": "bogus"}]
    result = check_ledger.check(rows, required_ids=["a", "zzz"])
    assert result["clean"] is False and result["not_allowed"] == ["b"]
    text = " | ".join(result["problems"])
    for fragment in ("empty spdx", "duplicate id a", "verdict 'bogus'", "required item zzz"):
        assert fragment in text
    assert check_ledger.check([{**base, "id": "a", "verdict": "allow"}])["clean"] is True
    # regression: the gate passed on input that proves nothing
    assert check_ledger.check([])["problems"] == ["the ledger has no rows"]
    for spdx in ("NOASSERTION", "UNKNOWN", ""):
        bad = check_ledger.check([{**base, "id": "a", "verdict": "allow", "spdx": spdx}])
        assert not bad["clean"]
    agpl = check_ledger.check([{**base, "id": "a", "verdict": "allow", "spdx": "AGPL-3.0-only"}],
                              policy=POLICY)
    assert "not pre-approved by the policy: AGPL-3.0-only" in agpl["problems"][0]
    assert check_ledger.check([{**base, "id": "a", "verdict": "allow", "spdx": "MIT; MPL-2.0"}],
                              policy=POLICY)["clean"]
    sums = check_ledger.check([{**base, "id": "a", "verdict": "allow", "spdx": "MIT",
                                "sha256": "1" * 64}], ["a"], POLICY, {"a": "2" * 64})
    assert "sha256 differs from download.lst" in sums["problems"][0]


def test_check_ledger_cli_exit_codes(tmp_path, capsys):
    base = {column: "x" for column in build_ledger.COLUMNS}
    ledger = tmp_path / "ledger.csv"
    build_ledger.write_ledger(ledger, [{**base, "id": "a", "verdict": "needs-review"}])
    assert check_ledger.run(["--ledger", str(ledger)]) == 8
    assert check_ledger.run(["--ledger", str(ledger), "--report-only"]) == 0
    build_ledger.write_ledger(ledger, [{**base, "id": "a", "verdict": "allow", "spdx": "MIT"}])
    assert check_ledger.run(["--ledger", str(ledger)]) == 0
    build_ledger.write_ledger(ledger, [{**base, "id": "a", "verdict": "allow",
                                        "spdx": "GPL-3.0-only"}])
    assert check_ledger.run(["--ledger", str(ledger)]) == 8   # allow outside the policy
    assert check_ledger.run(["--ledger", str(tmp_path / "none.csv")]) == 2
    ledger.write_text("wrong,header\n1,2\n")
    assert check_ledger.run(["--ledger", str(ledger)]) == 2
    capsys.readouterr()


# --------------------------------------------------------------------- pin

COMMIT = "861effc5289d539f15c4c18d1ba8579ffd78728b"


def test_parse_ls_remote_prefers_peeled_commit():
    output = (f"{'1' * 40}\trefs/tags/v1\n{COMMIT}\trefs/tags/v1^{{}}\n"
              f"{'2' * 40}\trefs/tags/v1-buildfix1\n")
    assert verify_pin.parse_ls_remote(output, "v1") == COMMIT
    assert verify_pin.parse_ls_remote(f"{'1' * 40}\trefs/tags/v1\n", "v1") == "1" * 40
    assert verify_pin.parse_ls_remote("", "v1") is None


def test_ls_remote_retries_then_reports_failure():
    calls, sleeps = [], []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 128, "", "fatal: unable to access")

    result = verify_pin.ls_remote("https://example.invalid/x", "v1", retries=2, runner=runner,
                                  sleep=sleeps.append)
    assert result["commit"] is None and result["attempts"] == 3 and len(calls) == 3
    assert sleeps == [2.0, 4.0] and "unable to access" in result["error"]


def test_load_pin_validation(tmp_path):
    pin = {"tag": "v1", "commit": COMMIT, "official_repository": "https://a.example/x",
           "mirror_repository": "https://b.example/x"}
    path = tmp_path / "pin.json"
    path.write_text(json.dumps(pin))
    assert verify_pin.load_pin(path)["commit"] == COMMIT
    for broken in ({**pin, "commit": "abc"}, {**pin, "tag": "bad tag"},
                   {k: v for k, v in pin.items() if k != "mirror_repository"}):
        path.write_text(json.dumps(broken))
        with pytest.raises(verify_pin.PinError):
            verify_pin.load_pin(path)
    path.write_text(json.dumps({**pin, "official_repository": "http://insecure.example/x"}))
    with pytest.raises(ValueError):
        verify_pin.load_pin(path)


def test_newest_stable_listing():
    page = b'<a href="25.8.7/">x</a> <a href="26.2.7/">x</a> <a href="26.8.3/">x</a> <a href="26.8.2/">x</a>'
    assert verify_pin.newest_stable(page) == "26.8.3"
    assert verify_pin.newest_stable(b'<a href="26.10.0/">x</a><a href="26.8.3/">x</a>') == "26.10.0"
    assert verify_pin.newest_stable(b"no versions here") is None


def test_verify_pin_offline_checks(tmp_path, capsys):
    pin = {"tag": "v1", "commit": COMMIT, "official_repository": "https://a.example/x",
           "mirror_repository": "https://b.example/x", "release": {"sha256": "0" * 64}}
    pin_path = tmp_path / "pin.json"
    pin_path.write_text(json.dumps(pin))
    engine = tmp_path / "engine" / "program"
    engine.mkdir(parents=True)
    (engine / "versionrc").write_text(f"[Version]\nbuildid={COMMIT}\n")
    out = tmp_path / "evidence.json"
    args = ["--pin", str(pin_path), "--offline", "--out", str(out),
            "--engine-home", str(tmp_path / "engine")]
    assert verify_pin.run(args) == 0
    assert json.loads(out.read_text())["checks"][0]["check"] == "release-buildid"
    (engine / "versionrc").write_text("[Version]\nbuildid=" + "f" * 40 + "\n")
    assert verify_pin.run(args) == 9
    archive = tmp_path / "release.tar.gz"
    archive.write_bytes(b"not the pinned bytes")
    assert verify_pin.run(["--pin", str(pin_path), "--offline", "--out", str(out),
                           "--release-archive", str(archive)]) == 9
    assert verify_pin.run(["--pin", str(pin_path), "--offline", "--out", str(out)]) == 9
    capsys.readouterr()
