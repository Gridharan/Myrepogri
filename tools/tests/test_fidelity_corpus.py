# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Unit tests for the corpus tools and the fidelity harness (no engine needed).

One integration test at the end runs a real document through an engine;
it is skipped unless ``SUITE_ENGINE_HOME`` points at an installation.
"""

import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools.corpus import build_manifest, gen_seed, manifest, select_upstream
from tools.fidelity import compare, pkgdiff, report, run_fidelity

REPO = Path(__file__).resolve().parents[2]
W = pkgdiff.NS["w"]


def _zip(path, files):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def _docx(path, body, extra=None):
    files = {"[Content_Types].xml": "<Types/>",
             "word/document.xml": f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'}
    files.update(extra or {})
    return _zip(path, files)


# ---------------------------------------------------------------- gen_seed

def test_generator_is_deterministic_and_matches_committed_files():
    first, second = gen_seed.generate(), gen_seed.generate()
    assert first == second and set(first) == set(gen_seed.CATALOGUE)
    for name, data in first.items():
        assert (REPO / "corpus" / "self" / name).read_bytes() == data, name


def test_generated_packages_contain_the_features_they_claim(tmp_path):
    files = gen_seed.generate()
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    review = pkgdiff.inspect_package(tmp_path / "seed-review.docx")
    assert review["content_counts"] == {"comments": 2, "tracked-changes": 4}
    assert review["element_counts"]["w:ins"] == 3 and review["element_counts"]["w:del"] == 1
    notes = pkgdiff.inspect_package(tmp_path / "seed-notes-headers.docx")
    assert notes["content_counts"] == {"endnotes": 1, "footers-with-text": 1, "footnotes": 2,
                                       "headers-with-text": 2}
    assert notes["element_counts"]["toc-field"] == 1
    deck = pkgdiff.inspect_package(tmp_path / "seed-basic.pptx")
    assert deck["part_kinds"]["slide"] == 5 and deck["part_kinds"]["slide-layout"] == 2
    assert deck["transitions"] == ["p:fade", "p:push", "p:wipe"]
    assert deck["content_counts"] == {"notes-with-text": 2}
    fonts = pkgdiff.inspect_package(tmp_path / "seed-fonts.docx")["fonts"]
    assert set(gen_seed.FONT_PROBE) <= set(fonts)
    odt = pkgdiff.inspect_package(tmp_path / "seed-basic.odt")
    assert odt["family"] == "odf" and odt["element_counts"]["table:table"] == 1
    with zipfile.ZipFile(tmp_path / "seed-basic.odp") as archive:  # ODF: mimetype first, stored
        first = archive.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    assert files["seed-utf8-bom.txt"].startswith(b"\xef\xbb\xbf")
    assert files["seed-basic.rtf"].startswith(b"{\\rtf1")
    assert gen_seed.png_image()[:8] == b"\x89PNG\r\n\x1a\n"


def test_generator_ships_no_third_party_marks_in_metadata():
    for name, data in gen_seed.generate().items():
        if not name.endswith((".docx", ".dotx", ".pptx", ".ppsx", ".potx")):
            continue
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            app = archive.read("docProps/app.xml").decode("utf-8")
        assert gen_seed.GENERATOR in app and "Microsoft" not in app


def test_generator_check_mode(tmp_path, capsys):
    assert gen_seed.main(["--out", str(tmp_path)]) == 0
    assert gen_seed.main(["--out", str(tmp_path), "--check"]) == 0
    (tmp_path / "seed-ascii.txt").write_bytes(b"changed")
    assert gen_seed.main(["--out", str(tmp_path), "--check"]) == 7
    capsys.readouterr()


# ----------------------------------------------------------------- pkgdiff

def test_inspect_counts_real_notes_only_and_rejects_non_packages(tmp_path):
    notes = (f'<w:footnotes xmlns:w="{W}"><w:footnote w:type="separator" w:id="-1"/>'
             f'<w:footnote w:type="continuationSeparator" w:id="0"/></w:footnotes>')
    package = _docx(tmp_path / "a.docx", "<w:p/><w:tbl/>", {"word/footnotes.xml": notes})
    inventory = pkgdiff.inspect_package(package)
    assert inventory["part_kinds"]["word-footnotes"] == 1
    assert "footnotes" not in inventory["content_counts"]  # separators are not content
    assert inventory["element_counts"] == {"w:p": 1, "w:tbl": 1}
    with pytest.raises(pkgdiff.PackageError):
        pkgdiff.inspect_package(_zip(tmp_path / "plain.zip", {"readme.txt": "x"}))
    (tmp_path / "not.zip").write_bytes(b"hello")
    with pytest.raises(pkgdiff.PackageError):
        pkgdiff.inspect_package(tmp_path / "not.zip")
    assert pkgdiff.is_zip_package(package) and not pkgdiff.is_zip_package(tmp_path / "not.zip")


def test_parts_with_dtd_or_bad_xml_are_skipped_not_parsed(tmp_path):
    bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
            f'<w:document xmlns:w="{W}"><w:body>&lol;</w:body></w:document>')
    package = _zip(tmp_path / "b.docx", {"[Content_Types].xml": "<Types/>",
                                         "word/document.xml": bomb,
                                         "word/header1.xml": "<not-closed"})
    skipped = pkgdiff.inspect_package(package)["skipped_parts"]
    assert skipped["word/document.xml"] == "dtd-or-entity-declaration"
    assert skipped["word/header1.xml"].startswith("xml-parse-error")


def test_strict_namespace_and_newer_transition_names(tmp_path):
    strict = "http://purl.oclc.org/ooxml/wordprocessingml/main"
    package = _zip(tmp_path / "s.docx", {
        "[Content_Types].xml": "<Types/>",
        "word/document.xml": f'<w:document xmlns:w="{strict}"><w:body><w:tbl/></w:body></w:document>'})
    assert pkgdiff.inspect_package(package)["element_counts"] == {"w:tbl": 1}
    p_ns, mc = pkgdiff.NS["p"], pkgdiff.NS["mc"]
    slide = (f'<p:sld xmlns:p="{p_ns}" xmlns:mc="{mc}" xmlns:x="urn:example:newer">'
             '<mc:AlternateContent><mc:Choice><p:transition><x:vortex/></p:transition></mc:Choice>'
             '<mc:Fallback><p:transition><p:fade/></p:transition></mc:Fallback>'
             '</mc:AlternateContent></p:sld>')
    deck = _zip(tmp_path / "t.pptx", {"[Content_Types].xml": "<Types/>",
                                      "ppt/slides/slide1.xml": slide})
    before = pkgdiff.inspect_package(deck)
    assert before["transitions"] == ["p:fade", "vortex"]
    plain = _zip(tmp_path / "u.pptx", {
        "[Content_Types].xml": "<Types/>",
        "ppt/slides/slide1.xml": f'<p:sld xmlns:p="{p_ns}"><p:transition><p:fade/>'
                                 "</p:transition><p:transition/></p:sld>"})
    diff = pkgdiff.diff_inventories(before, pkgdiff.inspect_package(plain))
    assert diff["transitions_lost"] == ["vortex"]   # the newer effect is gone, fade stays


def test_diff_flags_lost_content_but_not_empty_container_parts(tmp_path):
    comments = (f'<w:comments xmlns:w="{W}"><w:comment w:id="0"/><w:comment w:id="1"/>'
                "</w:comments>")
    empty_notes = f'<w:footnotes xmlns:w="{W}"><w:footnote w:type="separator" w:id="-1"/></w:footnotes>'
    before = pkgdiff.inspect_package(_docx(tmp_path / "before.docx", "<w:p/>", {
        "word/comments.xml": comments, "word/footnotes.xml": empty_notes,
        "word/vbaProject.bin": b"\x00", "word/media/image1.png": b"\x89PNG"}))
    after = pkgdiff.inspect_package(_docx(tmp_path / "after.docx", "<w:p/>", {
        "word/comments.xml": f'<w:comments xmlns:w="{W}"><w:comment w:id="0"/></w:comments>',
        "word/media/image1.png": b"\x89PNG"}))
    diff = pkgdiff.diff_inventories(before, after)
    assert diff["content_lost"] == ["comments"]                 # 2 -> 1 is a loss
    assert diff["critical_part_kinds_lost"] == ["vba-project"]
    assert "word-footnotes" in diff["part_kinds_lost"]          # reported, but not critical
    assert pkgdiff.diff_inventories(before, before)["content_lost"] == []


def test_odf_replacement_images_are_not_embeddings():
    assert pkgdiff.classify_part("ObjectReplacements/Object 1", "odf") == "object-replacement"
    assert pkgdiff.classify_part("Object 1/content.xml", "odf") == "embedding"
    assert pkgdiff.classify_part("word/vbaProject.bin", "ooxml") == "vba-project"
    assert pkgdiff.classify_part("something/else.bin", "ooxml") == "other"


def test_pdf_page_count(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.7\n1 0 obj\n<</Type/Pages/Kids[2 0 R]/Count 3>>\nendobj\n"
                    b"2 0 obj\n<</Type/Page/Parent 1 0 R>>\nendobj\n%%EOF\n")
    assert pkgdiff.pdf_page_count(pdf) == 3
    kids = b" ".join(b"%d 0 R" % number for number in range(3, 503))   # a long page list
    pdf.write_bytes(b"%PDF-1.7\n1 0 obj\n<</Type/Pages\n/Resources 2 0 R\n/Kids[ " + kids
                    + b" ]\n/Count 500>>\nendobj\n%%EOF\n")
    assert pkgdiff.pdf_page_count(pdf) == 500       # regression: was None above ~45 pages
    pdf.write_bytes(b"%PDF-1.7\n(no plain page tree)\n")
    assert pkgdiff.pdf_page_count(pdf) is None
    pdf.write_bytes(b"not a pdf")
    assert pkgdiff.pdf_page_count(pdf) is None
    assert pkgdiff.pdf_page_count(tmp_path / "absent.pdf") is None


# ----------------------------------------------------------------- compare

def _worker(before, after, kind="writer", steps=None, alive=True, units=(2, 2)):
    names = ("engine_start", "open", "measure", "pdf_export", "roundtrip_save", "reopen",
             "remeasure")
    return {"steps": steps or {name: {"ok": True, "duration_ms": 1} for name in names},
            "engine": {"alive_at_end": alive}, "import_filter": "f", "reopen_filter": "f",
            "before": {"kind": kind, "unit_count": units[0], "metrics": before},
            "after": {"kind": kind, "unit_count": units[1], "metrics": after}}


def test_classify_pass_partial_fail():
    same = {"page_count": 2, "tables": 1, "paragraphs": 5}
    assert compare.classify(_worker(same, same), None, 2, True)["status"] == "pass"
    info_only = compare.classify(_worker(same, {**same, "paragraphs": 6}), None, 2, True)
    assert info_only["status"] == "pass" and info_only["info_diffs"] == {"paragraphs": [5, 6]}
    lost = compare.classify(_worker(same, {**same, "tables": 0}), None, 2, True)
    assert lost["status"] == "partial"
    assert lost["reasons"] == ["critical-metric-changed:tables"]
    pages = compare.classify(_worker(same, same, units=(2, 3)), None, 2, True)
    assert pages["reasons"] == ["unit-count-changed"]
    assert compare.classify(_worker(same, same), None, 5, True)["reasons"] == ["pdf-page-mismatch"]
    unknown = compare.classify(_worker(same, same), None, None, True)
    assert unknown["status"] == "partial"           # the page criterion was not checkable
    assert unknown["reasons"] == ["pdf-page-count-unknown"]
    assert compare.classify(_worker(same, same), None, 2, False)["reasons"] == ["pdf-invalid"]


def test_classify_failures():
    assert compare.classify(None, None, None, None, timed_out=True)["reasons"] == ["timeout"]
    assert compare.classify(None, None, None, None, worker_exit=3)["reasons"] == ["worker-exit-3"]
    steps = {"engine_start": {"ok": True}, "open": {"ok": False, "error": "bad"}}
    failed = compare.classify(_worker({}, {}, steps=steps), None, None, None)
    assert failed["status"] == "fail" and failed["reasons"] == ["open-failed"]
    crashed = compare.classify(_worker({"page_count": 1}, {"page_count": 1}, alive=False),
                               None, 1, True)
    assert crashed["status"] == "fail" and crashed["reasons"] == ["engine-crashed"]


def test_classify_uses_package_findings_and_hidden_slides():
    deck = {"slide_count": 5, "hidden_slides": 1, "transitions": [[1, 1, True, 0]]}
    worker = _worker(deck, deck, kind="impress", units=(5, 5))
    assert compare.expected_pdf_pages(worker["before"]) == 4
    diff = {"critical_part_kinds_lost": ["diagram"], "part_kinds_lost": ["diagram", "theme"],
            "content_lost": ["comments"], "transitions_changed": True, "family_changed": False}
    verdict = compare.classify(worker, diff, 4, True)
    assert verdict["status"] == "partial"
    assert verdict["reasons"] == ["part-kind-lost:diagram", "content-lost:comments"]
    morph = {"critical_part_kinds_lost": [], "part_kinds_lost": [], "content_lost": [],
             "transitions_lost": ["morph"], "transitions_changed": True}
    assert compare.classify(worker, morph, 4, True)["reasons"] == ["transition-lost:morph"]
    assert "part-kind-lost:theme" in verdict["info"]


def test_content_shrink_is_a_loss():
    # regression: a document that lost all its words used to "pass"
    before = {"page_count": 1, "word_count": 420, "character_count": 2600, "text_frames": 4}
    after = {"page_count": 1, "word_count": 0, "character_count": 0, "text_frames": 0}
    verdict = compare.classify(_worker(before, after, units=(1, 1)), None, 1, True)
    assert verdict["status"] == "partial"
    assert verdict["reasons"] == ["content-shrank:word_count", "content-shrank:character_count",
                                  "content-shrank:text_frames"]
    small = {**before, "word_count": 410}            # 2.4 % is inside the tolerance
    assert compare.classify(_worker(before, small, units=(1, 1)), None, 1, True)["status"] == "pass"
    deck = {"slide_count": 2, "text_chars": 5000, "shapes": 30, "notes_chars": 900}
    lost = {"slide_count": 2, "text_chars": 0, "shapes": 3, "notes_chars": 3}
    assert compare.classify(_worker(deck, lost, kind="impress"), None, 2, True)["reasons"] == [
        "content-shrank:text_chars", "content-shrank:notes_chars", "content-shrank:shapes"]
    assert compare.shrunk({"word_count": 0}, {"word_count": 0}, "writer") == []
    assert compare.shrunk({"word_count": 5}, {"word_count": 9}, "writer") == []   # growth is fine


def test_package_counters_cover_formulas_and_odf(tmp_path):
    m = pkgdiff.NS["m"]
    with_math = _zip(tmp_path / "m.pptx", {
        "[Content_Types].xml": "<Types/>",
        "ppt/slides/slide1.xml": f'<p:sld xmlns:p="{pkgdiff.NS["p"]}" xmlns:m="{m}"><m:oMath/>'
                                 "</p:sld>"})
    without = _zip(tmp_path / "n.pptx", {"[Content_Types].xml": "<Types/>",
                                         "ppt/slides/slide1.xml": f'<p:sld xmlns:p="{pkgdiff.NS["p"]}"/>'})
    diff = pkgdiff.diff_inventories(pkgdiff.inspect_package(with_math),
                                    pkgdiff.inspect_package(without))
    assert diff["content_lost"] == ["formulas"]      # regression: formula loss went unseen
    text, office = pkgdiff.NS["text"], pkgdiff.NS["office"]
    odt = _zip(tmp_path / "o.odt", {
        "mimetype": "application/vnd.oasis.opendocument.text",
        "content.xml": f'<office:document-content xmlns:office="{office}" xmlns:text="{text}">'
                       '<office:annotation/><office:annotation/>'
                       '<text:note text:note-class="footnote"/>'
                       '<text:note text:note-class="endnote"/><text:changed-region/>'
                       "</office:document-content>"})
    assert pkgdiff.inspect_package(odt)["content_counts"] == {
        "comments": 2, "endnotes": 1, "footnotes": 1, "tracked-changes": 1}


def test_xml_guard_is_independent_of_offset_and_encoding():
    late = b'<?xml version="1.0"?><!--' + b"x" * 5000 + b'--><!DOCTYPE a [<!ENTITY e "b">]><a>&e;</a>'
    assert pkgdiff.scan_xml(late) == {"skipped": "dtd-or-entity-declaration"}
    wide = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE a [<!ENTITY e "b">]><a>&e;</a>'
    assert pkgdiff.scan_xml(wide.encode("utf-16")) == {"skipped": "dtd-or-entity-declaration"}
    odd = pkgdiff.scan_xml(b'<?xml version="1.0" encoding="Shift_JIS"?><a/>')
    assert odd["skipped"].startswith("xml-unreadable")


def test_run_isolated_kills_the_whole_process_group(tmp_path):
    marker = tmp_path / "pid"
    script = f"sleep 300 & echo $! > {marker}; wait"
    with pytest.raises(subprocess.TimeoutExpired):
        run_fidelity.run_isolated(["sh", "-c", script], timeout=1)
    child = int(marker.read_text())
    for _ in range(50):                               # give the kernel a moment to reap
        if not Path(f"/proc/{child}").exists() or "Z" in Path(f"/proc/{child}/stat").read_text():
            break
        import time
        time.sleep(0.1)
    alive = Path(f"/proc/{child}").exists() and " Z " not in Path(f"/proc/{child}/stat").read_text()
    assert not alive                                  # the grandchild did not survive
    done = run_fidelity.run_isolated(["sh", "-c", "echo hi"], timeout=10)
    assert done.returncode == 0 and done.stdout.strip() == "hi"


def test_flatten_and_summarise():
    flat = compare.flatten({"basic": {"modules": 2}, "indexes": {"ContentIndex": 1}, "x": 1})
    assert flat == {"basic.modules": 2, "indexes": {"ContentIndex": 1}, "x": 1}
    rows = [{"status": "pass", "format": "docx", "app": "writer", "features": ["tables"]},
            {"status": "partial", "format": "docx", "app": "writer", "features": ["tables"],
             "reasons": ["r1"]},
            {"status": "fail", "format": "pptx", "app": "impress", "features": [],
             "reasons": ["r1", "r2"]}]
    summary = compare.summarise(rows)
    assert (summary["total"], summary["pass"], summary["pass_rate"]) == (3, 1, 0.3333)
    assert summary["by_format"]["docx"]["pass_rate"] == 0.5
    assert summary["by_feature"]["tables"]["total"] == 2 and summary["reasons"] == {"r1": 2, "r2": 1}
    assert compare.summarise([])["pass_rate"] is None


# ------------------------------------------------------------------ report

def test_report_escapes_untrusted_strings():
    row = {"id": "x", "path": "<script>alert(1)</script>", "format": "docx", "status": "partial",
           "reasons": ['a"b<c'], "critical_diffs": {"k": ["<i>", 1]}, "import_filter": "&f",
           "fonts": ["Evil<font>"], "units_before": 1, "units_after": 1}
    document = {"run_id": "r", "label": "baseline", "generated_at": "t",
                "engine": {"version": "<b>v</b>"},
                "corpus": {"files": 1, "manifest_sha256": "a" * 64},
                "summary": compare.summarise([{**row, "app": "writer", "features": ["<f>"]}]),
                "files": [row]}
    html = report.render(document)
    for hostile in ("<script>", "<b>v</b>", "<i>", "Evil<font>", "<f>"):
        assert hostile not in html
    assert "&lt;script&gt;" in html and "<script" not in html.lower().replace("&lt;script", "")
    assert report.fonts_used([row]) == {"Evil<font>": ["x"]}


# ---------------------------------------------------------------- manifest

HEADER = ",".join(manifest.COLUMNS)


def _manifest(tmp_path, *rows):
    path = tmp_path / "MANIFEST.csv"
    path.write_text(HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_manifest_loads_and_verifies(tmp_path):
    data = b"hello"
    import hashlib
    digest = hashlib.sha256(data).hexdigest()
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "a.txt").write_bytes(data)
    path = _manifest(tmp_path, f"self-a,corpus/a.txt,self-authored,gen,{digest},5,txt,writer,"
                               "plain-text;unicode,MPL-2.0,,note")
    (entry,) = manifest.load_manifest(path)
    assert entry.features == ("plain-text", "unicode")
    assert manifest.verify_entry(entry, tmp_path, None) == (tmp_path / "corpus" / "a.txt").resolve()
    (tmp_path / "corpus" / "a.txt").write_bytes(b"HELLO")
    with pytest.raises(manifest.ManifestError, match="sha256"):
        manifest.verify_entry(entry, tmp_path, None)
    (tmp_path / "corpus" / "a.txt").write_bytes(b"longer")
    with pytest.raises(manifest.ManifestError, match="size"):
        manifest.verify_entry(entry, tmp_path, None)


@pytest.mark.parametrize("row,message", [
    ("BAD ID,a.txt,self-authored,g," + "a" * 64 + ",1,txt,writer,,MPL-2.0,,", "bad id"),
    ("ok-id,../a.txt,self-authored,g," + "a" * 64 + ",1,txt,writer,,MPL-2.0,,", "bad path"),
    ("ok-id,/abs/a.txt,self-authored,g," + "a" * 64 + ",1,txt,writer,,MPL-2.0,,", "bad path"),
    ("ok-id,a.txt,found-online,g," + "a" * 64 + ",1,txt,writer,,MPL-2.0,,", "source must be"),
    ("ok-id,a.txt,self-authored,g,nothex,1,txt,writer,,MPL-2.0,,", "sha256"),
    ("ok-id,a.txt,self-authored,g," + "a" * 64 + ",x,txt,writer,,MPL-2.0,,", "bytes"),
    ("ok-id,a.txt,self-authored,g," + "a" * 64 + ",1,docx,writer,,MPL-2.0,,", "does not match"),
    ("ok-id,a.txt,self-authored,g," + "a" * 64 + ",1,txt,calc,,MPL-2.0,,", "app must be"),
    ("ok-id,a.txt,self-authored,g," + "a" * 64 + ",1,txt,writer,Bad Tag,MPL-2.0,,", "feature"),
    ("ok-id,a.txt,self-authored,g," + "a" * 64 + ",1,txt,writer,,,,", "licence is empty"),
    ("ok-id,a.txt,self-authored,," + "a" * 64 + ",1,txt,writer,,MPL-2.0,,", "origin is empty"),
])
def test_manifest_rejects_bad_rows(tmp_path, row, message):
    with pytest.raises(manifest.ManifestError, match=message):
        manifest.load_manifest(_manifest(tmp_path, row))


def test_manifest_rejects_bad_header_duplicates_and_missing_tree(tmp_path):
    good = "a-1,a.txt,upstream-test-file,tag@c," + "a" * 64 + ",1,txt,writer,,NOASSERTION,,"
    with pytest.raises(manifest.ManifestError, match="duplicate id"):
        manifest.load_manifest(_manifest(tmp_path, good, good.replace("a.txt", "b.txt")))
    with pytest.raises(manifest.ManifestError, match="more than once"):
        manifest.load_manifest(_manifest(tmp_path, good, good.replace("a-1", "a-2")))
    (tmp_path / "MANIFEST.csv").write_text("id,path\nx,y\n", encoding="utf-8")
    with pytest.raises(manifest.ManifestError, match="header"):
        manifest.load_manifest(tmp_path / "MANIFEST.csv")
    (entry,) = manifest.load_manifest(_manifest(tmp_path, good))
    with pytest.raises(manifest.ManifestError, match="upstream tree"):
        entry.resolve(tmp_path, None)


def test_committed_manifest_is_valid_and_self_files_verify():
    entries = manifest.load_manifest(REPO / "corpus" / "MANIFEST.csv")
    sources = {entry.source for entry in entries}
    assert sources == {"self-authored", "derived", "upstream-test-file"}
    for entry in entries:
        if entry.source != "upstream-test-file":
            manifest.verify_entry(entry, REPO, None)
            assert entry.licence == "MPL-2.0"
        else:
            assert entry.licence.startswith("NOASSERTION") and "@" in entry.origin


# --------------------------------------------------------- select_upstream

def test_candidate_filter_and_name_hints():
    assert select_upstream.is_candidate("sw/qa/extras/data/a.docx", 5000)
    for bad in ("sw/qa/core/data/ooxml/fail/a.docx", "sd/qa/unit/data/pptx/crash/a.pptx",
                "sw/qa/extras/data/CVE-2020-1.docx", "sw/qa/extras/data/ofz123.rtf"):
        assert not select_upstream.is_candidate(bad, 5000), bad
    assert not select_upstream.is_candidate("sw/qa/a.docx", 10)
    assert not select_upstream.is_candidate("sw/qa/a.docx", select_upstream.MAX_BYTES + 1)
    assert select_upstream.features_from_name("tdf1_comment_in_table.doc") == {"comments", "tables"}


def test_greedy_choice_covers_features_and_prefers_other_producers():
    def row(path, features, producer="Microsoft Office Word", size=1000):
        return {"path": path, "features": features, "producer": producer, "bytes": size}
    pool = [row("a", ["tables"]), row("b", ["tables", "comments", "toc"]),
            row("c", ["comments"], producer="LibreOffice/7.0"), row("d", ["toc"], size=10),
            row("e", ["vba"]), row("f", [])]
    chosen = [item["path"] for item in select_upstream.choose(pool, quota=3, cover=1)]
    assert chosen == ["b", "e", "a"] or set(chosen) >= {"b", "e"}
    assert len(select_upstream.choose(pool, quota=10, cover=2)) == len(pool)
    assert select_upstream.choose(pool, quota=3, cover=1) == select_upstream.choose(
        list(reversed(pool)), quota=3, cover=1)  # deterministic regardless of input order


def test_selection_cli_validates_input(tmp_path, capsys):
    out = tmp_path / "sel.json"
    assert select_upstream.run(["--upstream-tree", str(tmp_path / "none"), "--out", str(out)]) == 2
    assert select_upstream.run(["--upstream-tree", str(tmp_path), "--out", str(out),
                                "--cover", "9"]) == 2
    assert select_upstream.run(["--upstream-tree", str(tmp_path), "--out", str(out),
                                "--roots", "../x"]) == 2
    (tmp_path / "sw" / "qa").mkdir(parents=True)
    _docx(tmp_path / "sw" / "qa" / "t.docx", "<w:tbl/>" + "<w:p/>" * 400)
    assert select_upstream.run(["--upstream-tree", str(tmp_path), "--out", str(out)]) == 0
    (picked,) = json.loads(out.read_text())["files"]
    assert picked["path"] == "sw/qa/t.docx" and picked["features"] == ["tables"]
    capsys.readouterr()


def test_slug():
    assert build_manifest.slug("Seed Basic.DOCX") == "seed-basic-docx"
    assert build_manifest.slug("sw/qa/a_b--c.docx") == "sw-qa-a-b-c-docx"


# ------------------------------------------------------------ run_fidelity

def test_engine_identity_and_cli_errors(tmp_path, capsys):
    with pytest.raises(run_fidelity.EngineError):
        run_fidelity.engine_identity(tmp_path, tmp_path / "scratch")
    assert run_fidelity.run(["--manifest", str(tmp_path / "none.csv"),
                             "--engine-home", str(tmp_path)]) == 2
    path = _manifest(tmp_path)
    assert run_fidelity.run(["--manifest", str(path), "--engine-home", str(tmp_path),
                             "--jobs", "0"]) == 2
    assert run_fidelity.run(["--manifest", str(path), "--engine-home", str(tmp_path),
                             "--label", "Bad Label"]) == 2
    assert run_fidelity.run(["--manifest", str(path), "--engine-home", str(tmp_path),
                             "--work-dir", str(tmp_path / "w")]) == 3  # no engine there
    capsys.readouterr()


def test_remove_tree_never_leaves_the_work_root(tmp_path):
    root = tmp_path / "work"
    inside = root / "a" / "b"
    inside.mkdir(parents=True)
    outside = tmp_path / "precious"
    outside.mkdir()
    run_fidelity._remove_tree(outside, root)
    run_fidelity._remove_tree(root, root)
    assert outside.is_dir() and root.is_dir()
    run_fidelity._remove_tree(inside, root)
    assert not inside.exists()


def test_evaluate_builds_a_row_from_a_probe_result(tmp_path):
    source = _docx(tmp_path / "in.docx", "<w:p/><w:tbl/>")
    roundtrip = _docx(tmp_path / "rt.docx", "<w:p/>")
    pdf = tmp_path / "out.pdf"
    pdf.write_bytes(b"%PDF-1.7\n1 0 obj\n<</Type/Pages/Count 2>>\nendobj\n")
    metrics = {"page_count": 2, "tables": 1, "fonts": ["Calibri"]}
    worker = _worker(metrics, metrics)
    worker["outputs"] = {"pdf": str(pdf), "roundtrip": str(roundtrip)}
    entry = manifest.Entry("x-1", "in.docx", "self-authored", "gen", "a" * 64, 1, "docx",
                           "writer", ("tables",), "MPL-2.0", "", "")
    row = run_fidelity.evaluate(entry, source, {"worker": worker, "timed_out": False,
                                                "exit_code": 0, "duration_ms": 5})
    assert row["status"] == "pass" and row["pdf_pages"] == 2 and row["fonts"] == ["Calibri"]
    assert row["package_diff"]["element_counts_changed"] == {"w:tbl": [1, 0]}
    timeout = run_fidelity.evaluate(entry, source, {"worker": None, "timed_out": True,
                                                    "exit_code": None, "duration_ms": 9})
    assert timeout["status"] == "fail" and timeout["reasons"] == ["timeout"]


def test_probe_script_validates_its_request_without_an_engine(tmp_path):
    worker = REPO / "tools" / "fidelity" / "uno_worker.py"
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"input": str(tmp_path / "missing.docx"), "workdir": "w",
                                   "result": "r", "soffice": "s"}))
    done = subprocess.run([sys.executable, str(worker), "--request", str(request)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 2 and "input is not a file" in done.stderr
    source = worker.read_text(encoding="utf-8")
    assert "MacroExecutionMode\", 0" in source      # macros are never executed
    assert "UpdateDocMode\", 0" in source           # links are never updated
    assert "from tools" not in source and "import tools" not in source  # runs under the engine


# -------------------------------------------------------------- integration

@pytest.mark.skipif(not os.environ.get("SUITE_ENGINE_HOME"),
                    reason="needs an engine: set SUITE_ENGINE_HOME")
def test_integration_open_export_roundtrip_reopen(tmp_path):
    out = tmp_path / "fidelity.json"
    code = run_fidelity.run([
        "--engine-home", os.environ["SUITE_ENGINE_HOME"], "--work-dir", str(tmp_path / "work"),
        "--out", str(out), "--html", str(tmp_path / "f.html"),
        "--metrics", str(tmp_path / "m.json"), "--label", "itest",
        "--only", "self-seed-review-docx", "self-seed-basic-odp"])
    assert code == 0
    rows = {row["id"]: row for row in json.loads(out.read_text())["files"]}
    review = rows["self-seed-review-docx"]
    assert review["status"] == "pass" and review["metrics_before"]["comments"] == 2
    assert review["metrics_before"]["redlines"] == 4 and review["pdf_pages"] == 1
    deck = rows["self-seed-basic-odp"]
    assert deck["status"] == "pass" and deck["units_before"] == 3
