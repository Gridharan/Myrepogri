# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Unit tests for the download.lst parser and the licence-file extractor."""

import hashlib
import io
import json
import struct
import tarfile
import zipfile
from pathlib import PurePosixPath

import pytest

from tools.ledger import download_lst, extract_licences, fetch_externals

SUM_A = "a" * 64
SUM_B = "b" * 64


# ------------------------------------------------------------ download.lst

def test_parse_pairs_kinds_and_urls():
    text = (f"# comment\nZLIB_SHA256SUM := {SUM_A}\nZLIB_TARBALL := zlib-1.4.tar.xz\n\n"
            f"TOOL_SHA256SUM := {SUM_B}\nTOOL_JAR := tool-1.0.jar\n")
    zlib_item, tool = sorted(download_lst.parse_download_lst(text), key=lambda i: i.key,
                             reverse=True)
    assert (zlib_item.key, zlib_item.kind, zlib_item.sha256) == ("ZLIB", "TARBALL", SUM_A)
    assert zlib_item.url == "https://dev-www.libreoffice.org/src/zlib-1.4.tar.xz"
    assert tool.url == "https://dev-www.libreoffice.org/extern/tool-1.0.jar"
    assert tool.fetchable


def test_immediate_variable_expansion():
    text = (f"X_SHA256SUM := {SUM_A}\nX_VERSION_MICRO := 7\n"
            "X_TARBALL := libx-1.2.$(X_VERSION_MICRO).tar.xz\n")
    (item,) = download_lst.parse_download_lst(text)
    assert item.filename == "libx-1.2.7.tar.xz"


@pytest.mark.parametrize("text,message", [
    (f"A_SHA256SUM := {SUM_A}\nA_TARBALL := a.tar\nA_TARBALL := b.tar\n", "more than once"),
    ("A_TARBALL := a.tar.gz\n", "missing or malformed"),
    (f"A_SHA256SUM := nothex\nA_TARBALL := a.tar.gz\n", "missing or malformed"),
    (f"A_SHA256SUM := {SUM_A}\n", "checksum without a file"),
    (f"A_SHA256SUM := {SUM_A}\nA_TARBALL := ../evil.tar\n", "unsafe file name"),
    (f"A_SHA256SUM := {SUM_A}\nA_TARBALL := a b.tar\n", "unsafe file name"),
    (f"A_SHA256SUM := {SUM_A}\nA_TARBALL := x-$(UNDEFINED).tar\n", "before it is assigned"),
    (f"A_SHA256SUM := {SUM_A}\nA_TARBALL := x-$(shell id).tar\n", "unsupported make syntax"),
    ("this is not an assignment\n", "unrecognised syntax"),
    (f"A_SHA256SUM := {SUM_A}\nA_TARBALL := same.tar\nB_SHA256SUM := {SUM_B}\n"
     "B_TARBALL := same.tar\n", "listed twice"),
])
def test_parse_rejects_bad_input(text, message):
    with pytest.raises(download_lst.DownloadLstError, match=message):
        download_lst.parse_download_lst(text)


def test_fetch_externals_usage_errors(tmp_path, capsys):
    missing = tmp_path / "nope.lst"
    assert fetch_externals.run(["--download-lst", str(missing), "--dest", str(tmp_path)]) == 2
    lst = tmp_path / "download.lst"
    lst.write_text(f"A_SHA256SUM := {SUM_A}\nA_TARBALL := a.tar.gz\n", encoding="utf-8")
    base = ["--download-lst", str(lst), "--dest", str(tmp_path / "d")]
    assert fetch_externals.run(base + ["--jobs", "0"]) == 2
    assert fetch_externals.run(base + ["--retries", "99"]) == 2
    assert fetch_externals.run(base + ["--only", "UNKNOWN"]) == 2
    capsys.readouterr()


# ------------------------------------------------------- licence extractor

def _tar(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data, kind in members:
            info = tarfile.TarInfo(name)
            if kind == "link":
                info.type = tarfile.SYMTYPE
                info.linkname = data
                archive.addfile(info)
            else:
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _external(tmp_path, filename, data):
    (tmp_path / "tarballs").mkdir(exist_ok=True)
    (tmp_path / "tarballs" / filename).write_bytes(data)
    return download_lst.External("PKG", "PKG_TARBALL", "TARBALL", filename,
                                 hashlib.sha256(data).hexdigest(), "https://example.invalid/x")


@pytest.mark.parametrize("name,expected", [
    ("pkg/LICENSE", "pkg/LICENSE"), ("./a//b/./c", "a/b/c"), ("a\\b\\COPYING", "a/b/COPYING"),
    ("../etc/passwd", None), ("/abs/path", None), ("a/../../b", None), ("C:\\x", None),
    ("", None), ("bad\x00name", None),
])
def test_normalise_member(name, expected):
    result = extract_licences.normalise_member(name)
    assert (str(result) if result else None) == expected


@pytest.mark.parametrize("path,role", [
    ("pkg/LICENSE", "licence"), ("pkg/COPYING.LIB", "licence"), ("pkg/docs/LICENSE.txt", "licence"),
    ("pkg/NOTICE", "licence"), ("pkg/OFL.txt", "licence"), ("pkg/LICENSES/MIT.txt", "licence"),
    ("pkg/README.md", "readme"), ("pkg/sub/README.md", None), ("pkg/src/license.cpp", None),
    ("pkg/src/main.c", None), ("pkg/legal/terms.html", "licence"),
])
def test_classify(path, role):
    assert extract_licences.classify(PurePosixPath(path), 1) == role


def test_archive_kind():
    kinds = {name: extract_licences.archive_kind(name) for name in
             ("a.tar.gz", "a.tgz", "a.tar.xz", "a.TAR.BZ2", "a.zip", "a.jar", "a.nupkg",
              "a.ttf", "a.exe")}
    assert kinds == {"a.tar.gz": "tar", "a.tgz": "tar", "a.tar.xz": "tar", "a.TAR.BZ2": "tar",
                     "a.zip": "zip", "a.jar": "zip", "a.nupkg": "zip", "a.ttf": "font",
                     "a.exe": "unsupported"}


def test_process_tar_copies_only_licence_files_and_ignores_hostile_members(tmp_path):
    data = _tar([
        ("pkg-1.0/LICENSE", b"MIT License\nPermission is hereby granted\n", "file"),
        ("pkg-1.0/README", b"readme text\n", "file"),
        ("pkg-1.0/src/main.c", b"int main(void) { return 0; }\n", "file"),
        ("pkg-1.0/a/b/c/d/COPYING", b"deep licence\n", "file"),
        ("pkg-1.0/COPYING.link", "/etc/passwd", "link"),
        ("pkg-1.0/../../escape/LICENSE", b"should never be written\n", "file"),
    ])
    item = _external(tmp_path, "pkg-1.0.tar.gz", data)
    dest = tmp_path / "out"
    inventory = extract_licences.process_archive(item, tmp_path / "tarballs", dest)
    assert inventory["status"] == "ok" and inventory["root_dir"] == "pkg-1.0"
    assert inventory["hostile_names_skipped"] == 1
    copied = {c["member"]: c for c in inventory["candidates"] if c["copied"]}
    assert set(copied) == {"pkg-1.0/LICENSE", "pkg-1.0/README"}
    licence = dest / "PKG" / copied["pkg-1.0/LICENSE"]["local"]
    assert licence.read_bytes().startswith(b"MIT License")
    assert copied["pkg-1.0/LICENSE"]["sha256"] == hashlib.sha256(licence.read_bytes()).hexdigest()
    deep = [c for c in inventory["candidates"] if c["member"].endswith("d/COPYING")]
    assert deep and deep[0]["copied"] is False  # listed, but too deep to copy
    written = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert written == {"PKG/files/pkg-1.0/LICENSE", "PKG/files/pkg-1.0/README"}
    assert not (tmp_path / "escape").exists()


def test_process_zip_and_oversized_member(tmp_path, monkeypatch):
    monkeypatch.setattr(extract_licences, "MAX_FILE_BYTES", 64)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("META-INF/LICENSE", "Apache License\nVersion 2.0\n")
        archive.writestr("META-INF/NOTICE", "N" * 500)
        archive.writestr("x/Thing.class", b"\xca\xfe")
    item = _external(tmp_path, "tool.jar", buffer.getvalue())
    inventory = extract_licences.process_archive(item, tmp_path / "tarballs", tmp_path / "out")
    by_member = {c["member"]: c for c in inventory["candidates"]}
    assert by_member["META-INF/LICENSE"]["copied"] is True
    assert by_member["META-INF/NOTICE"]["copied"] is False  # over the size cap


def test_process_reports_missing_and_checksum_mismatch(tmp_path):
    item = _external(tmp_path, "pkg.tar.gz", _tar([("pkg/LICENSE", b"x", "file")]))
    wrong = download_lst.External(item.key, item.variable, item.kind, item.filename,
                                  "0" * 64, item.url)
    assert extract_licences.process_archive(
        wrong, tmp_path / "tarballs", tmp_path / "out")["status"] == "checksum-mismatch"
    gone = download_lst.External(item.key, item.variable, item.kind, "absent.tar.gz",
                                 item.sha256, item.url)
    assert extract_licences.process_archive(
        gone, tmp_path / "tarballs", tmp_path / "out")["status"] == "missing"


def test_corrupt_archive_raises_archive_error(tmp_path):
    item = _external(tmp_path, "pkg.tar.gz", b"this is not a tarball")
    with pytest.raises(extract_licences.ArchiveError):
        extract_licences.process_archive(item, tmp_path / "tarballs", tmp_path / "out")


def _font(records):
    """Minimal sfnt with only a name table (OpenType name table format 0)."""
    strings = b""
    entries = b""
    for name_id, text in records:
        blob = text.encode("utf-16-be")
        entries += struct.pack(">6H", 3, 1, 1033, name_id, len(blob), len(strings))
        strings += blob
    table = struct.pack(">HHH", 0, len(records), 6 + 12 * len(records)) + entries + strings
    header = struct.pack(">IHHHH", 0x00010000, 1, 0, 0, 0)
    directory = struct.pack(">4sIII", b"name", 0, 12 + 16, len(table))
    return header + directory + table


def test_font_name_records_and_font_download(tmp_path):
    data = _font([(0, "Copyright (c) Example"), (13, "SIL Open Font License 1.1"), (2, "Regular")])
    records = extract_licences.font_name_records(data)
    assert {r["name_id"]: r["text"] for r in records} == {
        0: "Copyright (c) Example", 13: "SIL Open Font License 1.1"}
    item = _external(tmp_path, "font.ttf", data)
    inventory = extract_licences.process_archive(item, tmp_path / "tarballs", tmp_path / "out")
    assert inventory["status"] == "ok" and inventory["font_name_records"] == 2
    dumped = json.loads((tmp_path / "out" / "PKG" / "_font_name_table.json").read_text())
    assert dumped[1]["text"] == "SIL Open Font License 1.1"
    with pytest.raises(extract_licences.ArchiveError):
        extract_licences.font_name_records(b"tiny")


def test_fonts_inside_archives_are_dumped(tmp_path):
    font = _font([(13, "Licensed under the Apache License, Version 2.0")])
    item = _external(tmp_path, "fonts.tar.gz", _tar([("f-1/Example.ttf", font, "file")]))
    inventory = extract_licences.process_archive(item, tmp_path / "tarballs", tmp_path / "out")
    assert inventory["font_members_total"] == 1 and inventory["font_members_dumped"] == 1
    dumped = json.loads((tmp_path / "out" / "PKG" / "_fonts.json").read_text())
    assert dumped[0]["name_records"][0]["text"].startswith("Licensed under the Apache")


def test_extract_cli_exit_codes(tmp_path, capsys):
    data = _tar([("pkg-1/LICENSE", b"zlib License\n", "file")])
    (tmp_path / "tarballs").mkdir()
    (tmp_path / "tarballs" / "pkg-1.tar.gz").write_bytes(data)
    lst = tmp_path / "download.lst"
    lst.write_text(f"PKG_SHA256SUM := {hashlib.sha256(data).hexdigest()}\n"
                   "PKG_TARBALL := pkg-1.tar.gz\n", encoding="utf-8")
    args = ["--download-lst", str(lst), "--tarballs", str(tmp_path / "tarballs"),
            "--dest", str(tmp_path / "out"), "--summary", str(tmp_path / "s.json")]
    assert extract_licences.run(args) == 0
    assert json.loads((tmp_path / "s.json").read_text())["by_status"] == {"ok": 1}
    lst.write_text(f"PKG_SHA256SUM := {'0' * 64}\nPKG_TARBALL := pkg-1.tar.gz\n",
                   encoding="utf-8")
    assert extract_licences.run(args) == 5
    assert extract_licences.run(["--download-lst", str(tmp_path / "none"), "--tarballs",
                                 str(tmp_path), "--dest", str(tmp_path / "o")]) == 2
    capsys.readouterr()
