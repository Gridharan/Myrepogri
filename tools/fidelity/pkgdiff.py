# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Structural inventory and diff of OOXML / ODF packages.

Used by the fidelity harness to compare a document with its round-tripped
copy *at file level*: which package parts exist, how many structural
elements the main parts contain, and which fonts are referenced.

Format knowledge comes from public specifications only:

* ECMA-376 / ISO/IEC 29500 (Open Packaging Conventions, WordprocessingML,
  PresentationML, DrawingML) for part names, content types and element
  names;
* OASIS OpenDocument v1.3 for ``content.xml`` / ``styles.xml`` element
  names.

Corpus files are untrusted input: archives are only read, never
extracted; part count, part size and total size are capped; parts that
declare a DTD or entities are not parsed.
"""

from __future__ import annotations

import re
import xml.parsers.expat
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree

MAX_PARTS = 20000
MAX_PART_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "v": "urn:schemas-microsoft-com:vml",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "presentation": "urn:oasis:names:tc:opendocument:xmlns:presentation:1.0",
    "anim": "urn:oasis:names:tc:opendocument:xmlns:animation:1.0",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
}
# ISO/IEC 29500 Strict uses different namespace URIs for the same vocabularies.
STRICT_NS = {
    "http://purl.oclc.org/ooxml/wordprocessingml/main": NS["w"],
    "http://purl.oclc.org/ooxml/presentationml/main": NS["p"],
    "http://purl.oclc.org/ooxml/drawingml/main": NS["a"],
    "http://purl.oclc.org/ooxml/officeDocument/math": NS["m"],
    "http://purl.oclc.org/ooxml/drawingml/chart": NS["c"],
    "http://purl.oclc.org/ooxml/drawingml/diagram": NS["dgm"],
    "http://purl.oclc.org/ooxml/drawingml/picture": NS["pic"],
}
_PREFIX_BY_URI = {uri: prefix for prefix, uri in NS.items()}

# (kind, regular expression on the part name) -- first match wins.
OOXML_PART_KINDS: Tuple[Tuple[str, str], ...] = (
    ("vba-project", r"^(word|ppt|xl)/vbaProject\.bin$"),
    ("vba-data", r"^(word|ppt|xl)/vbaData\.xml$"),
    ("signature", r"^_xmlsignatures/"),
    ("custom-xml", r"^customXml/item\d*\.xml$"),
    ("diagram", r"^(word|ppt)/diagrams/"),
    ("chart", r"^(word|ppt)/charts/chart\d*\.xml$"),
    ("embedding", r"^(word|ppt)/embeddings/"),
    ("media", r"^(word|ppt)/media/"),
    ("embedded-font", r"^(word|ppt)/fonts/"),
    ("word-header", r"^word/header\d*\.xml$"),
    ("word-footer", r"^word/footer\d*\.xml$"),
    ("word-footnotes", r"^word/footnotes\.xml$"),
    ("word-endnotes", r"^word/endnotes\.xml$"),
    ("word-comments", r"^word/comments\w*\.xml$"),
    ("word-numbering", r"^word/numbering\.xml$"),
    ("word-glossary", r"^word/glossary/"),
    ("word-document", r"^word/document\d*\.xml$"),
    ("slide", r"^ppt/slides/slide\d+\.xml$"),
    ("slide-master", r"^ppt/slideMasters/slideMaster\d+\.xml$"),
    ("slide-layout", r"^ppt/slideLayouts/slideLayout\d+\.xml$"),
    ("notes-slide", r"^ppt/notesSlides/notesSlide\d+\.xml$"),
    ("notes-master", r"^ppt/notesMasters/notesMaster\d+\.xml$"),
    ("handout-master", r"^ppt/handoutMasters/handoutMaster\d+\.xml$"),
    ("slide-comments", r"^ppt/comments/"),
    ("comment-authors", r"^ppt/(commentAuthors|authors)\.xml$"),
    ("theme", r"^(word|ppt)/theme/theme\d*\.xml$"),
    ("doc-props", r"^docProps/"),
)
ODF_PART_KINDS: Tuple[Tuple[str, str], ...] = (
    ("odf-basic", r"^Basic/"),
    ("odf-scripts", r"^Scripts/"),
    ("signature", r"^META-INF/\w*signatures\w*\.xml$"),
    ("media", r"^(Pictures|media|Media)/"),
    ("object-replacement", r"^ObjectReplacements/"),
    ("embedding", r"^Object \d+/"),
    ("embedded-font", r"^Fonts/"),
    ("odf-content", r"^content\.xml$"),
    ("odf-styles", r"^styles\.xml$"),
    ("odf-settings", r"^settings\.xml$"),
    ("odf-meta", r"^meta\.xml$"),
)
# Part kinds whose complete disappearance on round trip is a fidelity loss.
# Container parts (comments, notes, headers ...) are NOT listed: producers write
# them even when empty, so they are judged by CONTENT_COUNTS below instead.
CRITICAL_PART_KINDS = frozenset((
    "vba-project", "diagram", "chart", "embedding", "media", "embedded-font",
    "slide", "slide-master", "odf-basic",
))
#: content counter -> rule; "decrease": any drop is a loss, "vanish": only >0 -> 0
CONTENT_RULES = {
    "comments": "decrease", "footnotes": "decrease", "endnotes": "decrease",
    "formulas": "decrease", "tracked-changes": "vanish",
    "headers-with-text": "vanish", "footers-with-text": "vanish",
    "notes-with-text": "vanish",
}

# Elements counted per vocabulary: "prefix:localname".
WATCH = frozenset((
    "w:p", "w:tbl", "w:tr", "w:tc", "w:drawing", "w:pict", "w:object", "w:footnoteReference",
    "w:endnoteReference", "w:commentReference", "w:ins", "w:del", "w:moveFrom", "w:moveTo",
    "w:rPrChange", "w:pPrChange", "w:sdt", "w:fldSimple", "w:fldChar", "w:hyperlink",
    "w:bookmarkStart", "w:sectPr", "w:numPr", "w:txbxContent", "m:oMath", "mc:AlternateContent",
    "p:sld", "p:sp", "p:pic", "p:graphicFrame", "p:cxnSp", "p:grpSp", "p:transition",
    "p:timing", "p:par", "p:seq", "p:anim", "p:animEffect", "p:animMotion", "p:animScale",
    "p:animRot", "p:animClr", "p:set", "p:cmd", "p:audio", "p:video", "p:oleObj",
    "a:tbl", "a:hlinkClick", "a:videoFile", "a:audioFile", "c:chart", "dgm:relIds", "pic:pic",
    "v:shape", "v:textbox",
    "text:p", "text:h", "text:list", "text:note", "text:changed-region", "text:insertion",
    "text:deletion", "text:format-change", "text:table-of-content", "text:section",
    "text:bookmark-start", "text:a", "table:table", "table:table-row", "table:table-cell",
    "draw:frame", "draw:image", "draw:object", "draw:object-ole", "draw:plugin", "draw:page",
    "draw:custom-shape", "draw:g", "draw:connector", "draw:text-box", "office:annotation",
    "style:master-page", "presentation:notes", "anim:par", "anim:seq", "anim:animate",
    "anim:set", "anim:transitionFilter", "anim:animateMotion", "anim:animateTransform",
    "anim:animateColor", "anim:audio", "anim:command",
))
_FONT_ATTRS = (
    ("w:rFonts", ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs")),
    ("w:font", ("w:name",)),
    ("a:latin", ("typeface",)),
    ("a:ea", ("typeface",)),
    ("a:cs", ("typeface",)),
    ("a:sym", ("typeface",)),
    ("a:buFont", ("typeface",)),
    ("style:font-face", ("svg:font-family",)),
)
_XML_PARTS = re.compile(
    r"^(word/(document\d*|header\d*|footer\d*|footnotes|endnotes|comments\w*|fontTable|styles)"
    r"\.xml|ppt/(slides/slide\d+|slideMasters/slideMaster\d+|slideLayouts/slideLayout\d+|"
    r"notesSlides/notesSlide\d+|comments/\w+|presentation)\.xml|"
    r"(word|ppt)/theme/theme\d*\.xml|"
    r"content\.xml|styles\.xml)$")


class PackageError(Exception):
    """The file is not a readable package, or exceeds the safety limits."""


class _DeclarationRefused(Exception):
    """Raised from the expat handlers to stop parsing a part with a DTD."""


def _refuse_declaration(*_args: object) -> None:
    raise _DeclarationRefused()


def _qname(tag: str) -> str:
    """``{uri}local`` -> ``prefix:local`` for known namespaces, else ``?:local``."""
    if not tag.startswith("{"):
        return tag
    uri, _, local = tag[1:].partition("}")
    uri = STRICT_NS.get(uri, uri)
    return f"{_PREFIX_BY_URI.get(uri, '?')}:{local}"


def _attr(element: ElementTree.Element, name: str) -> Optional[str]:
    if ":" in name:
        prefix, local = name.split(":", 1)
        value = element.get(f"{{{NS[prefix]}}}{local}")
        if value is not None:
            return value
        for strict, canonical in STRICT_NS.items():
            if canonical == NS[prefix]:
                value = element.get(f"{{{strict}}}{local}")
                if value is not None:
                    return value
        return None
    return element.get(name)


def classify_part(name: str, family: str) -> str:
    table = OOXML_PART_KINDS if family == "ooxml" else ODF_PART_KINDS
    for kind, pattern in table:
        if re.search(pattern, name):
            return kind
    return "other"


def _is_theme_placeholder(name: str) -> bool:
    """DrawingML theme references such as ``+mn-lt`` are not font names."""
    return name.startswith("+") or name == ""


def scan_xml(data: bytes) -> Dict[str, object]:
    """Count watched elements and collect fonts/transitions from one XML part."""
    counts: Dict[str, int] = {}
    fonts = set()
    transitions: List[str] = []
    toc_fields = 0
    font_attr_map = dict(_FONT_ATTRS)
    # A part that declares a DTD or entities is not parsed at all.  A first pass
    # with bare expat aborts at the declaration wherever it sits and whatever the
    # encoding; only a clean part reaches the tree builder.
    probe = xml.parsers.expat.ParserCreate()
    probe.StartDoctypeDeclHandler = _refuse_declaration
    probe.EntityDeclHandler = _refuse_declaration
    try:
        probe.Parse(data, True)
        root = ElementTree.fromstring(data)
    except _DeclarationRefused:
        return {"skipped": "dtd-or-entity-declaration"}
    except (xml.parsers.expat.ExpatError, ElementTree.ParseError) as exc:
        return {"skipped": f"xml-parse-error: {exc}"}
    except (ValueError, LookupError) as exc:   # e.g. an encoding expat cannot read
        return {"skipped": f"xml-unreadable: {exc}"}
    text_chars = 0
    content: Dict[str, int] = {}
    stack: List[Tuple[ElementTree.Element, bool, bool]] = [(root, False, False)]
    while stack:
        element, in_transition, in_field = stack.pop()
        name = _qname(element.tag)
        if name in WATCH:
            counts[name] = counts.get(name, 0) + 1
        if name in ("w:footnote", "w:endnote"):
            # separator notes are layout helpers, not user content
            if (_attr(element, "w:type") or "normal") == "normal":
                key = "footnotes" if name == "w:footnote" else "endnotes"
                content[key] = content.get(key, 0) + 1
        elif name in ("w:comment", "office:annotation") or element.tag.endswith("}cm"):
            content["comments"] = content.get("comments", 0) + 1
        elif name == "text:note":
            key = "endnotes" if _attr(element, "text:note-class") == "endnote" else "footnotes"
            content[key] = content.get(key, 0) + 1
        elif name == "m:oMath":
            content["formulas"] = content.get("formulas", 0) + 1
        elif name in ("w:ins", "w:del", "w:moveFrom", "w:moveTo", "text:changed-region"):
            content["tracked-changes"] = content.get("tracked-changes", 0) + 1
        elif name in ("w:t", "a:t") and not in_field:
            text_chars += len((element.text or "").strip())
        if name in font_attr_map:
            for attr in font_attr_map[name]:
                value = _attr(element, attr)
                if value and not _is_theme_placeholder(value):
                    fonts.add(value.split(",")[0].strip().strip("'\""))
        if name == "w:instrText" or name == "w:fldSimple":
            text = (element.text or "") if name == "w:instrText" else (_attr(element, "w:instr") or "")
            if text.strip().upper().startswith("TOC"):
                toc_fields += 1
        if in_transition:
            # direct child of p:transition names the effect (fade, push, p14:vortex ...)
            transitions.append(name if name.startswith(("p:", "a:")) else element.tag.rpartition("}")[2])
        is_transition = name == "p:transition"
        if is_transition and not len(element):
            transitions.append("(none)")
        child_in_field = in_field or name == "a:fld"
        for child in element:
            stack.append((child, is_transition, child_in_field))
    result: Dict[str, object] = {"counts": counts, "fonts": sorted(fonts),
                                 "content": content, "text_chars": text_chars}
    if transitions:
        result["transitions"] = sorted(transitions)
    if toc_fields:
        counts["toc-field"] = toc_fields
    return result


def inspect_package(path: Path) -> Dict[str, object]:
    """Return the structural inventory of an OOXML or ODF package."""
    path = Path(path)
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise PackageError(f"not a zip package: {exc}") from exc
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > MAX_PARTS:
            raise PackageError(f"too many parts: {len(infos)}")
        total = sum(info.file_size for info in infos)
        if total > MAX_TOTAL_BYTES:
            raise PackageError(f"package too large when unpacked: {total} bytes")
        names = [info.filename for info in infos]
        if "[Content_Types].xml" in names:
            family = "ooxml"
        elif "META-INF/manifest.xml" in names or "mimetype" in names:
            family = "odf"
        else:
            raise PackageError("neither OOXML nor ODF package markers found")

        part_kinds: Dict[str, int] = {}
        counts: Dict[str, int] = {}
        content: Dict[str, int] = {}
        fonts = set()
        transitions: List[str] = []
        skipped: Dict[str, str] = {}
        for info in infos:
            kind = classify_part(info.filename, family)
            part_kinds[kind] = part_kinds.get(kind, 0) + 1
            if not _XML_PARTS.match(info.filename):
                continue
            if info.file_size > MAX_PART_BYTES:
                skipped[info.filename] = "part-too-large"
                continue
            try:
                with archive.open(info) as handle:
                    data = handle.read(MAX_PART_BYTES + 1)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
                skipped[info.filename] = f"unreadable: {exc}"
                continue
            scanned = scan_xml(data)
            if "skipped" in scanned:
                skipped[info.filename] = str(scanned["skipped"])
                continue
            for key, value in scanned["content"].items():  # type: ignore[union-attr]
                content[key] = content.get(key, 0) + value
            with_text = {"word-header": "headers-with-text", "word-footer": "footers-with-text",
                         "notes-slide": "notes-with-text"}.get(kind)
            if with_text and scanned["text_chars"]:
                content[with_text] = content.get(with_text, 0) + 1
            is_body = kind in ("word-document", "slide", "odf-content", "word-header",
                               "word-footer", "word-footnotes", "word-endnotes",
                               "notes-slide")
            if is_body:
                for name, value in scanned["counts"].items():  # type: ignore[union-attr]
                    counts[name] = counts.get(name, 0) + value
                transitions.extend(scanned.get("transitions", []))  # type: ignore[arg-type]
            elif kind == "odf-styles":
                for name in ("style:master-page",):
                    value = scanned["counts"].get(name, 0)  # type: ignore[union-attr]
                    if value:
                        counts[name] = counts.get(name, 0) + value
            fonts.update(scanned["fonts"])  # type: ignore[arg-type]
    return {
        "family": family,
        "parts": len(names),
        "part_kinds": dict(sorted(part_kinds.items())),
        "element_counts": dict(sorted(counts.items())),
        "content_counts": dict(sorted(content.items())),
        "fonts": sorted(fonts),
        "transitions": sorted(transitions),
        "skipped_parts": skipped,
    }


def _delta(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, List[int]]:
    keys = sorted(set(before) | set(after))
    return {key: [before.get(key, 0), after.get(key, 0)]
            for key in keys if before.get(key, 0) != after.get(key, 0)}


def diff_inventories(before: Dict[str, object], after: Dict[str, object]) -> Dict[str, object]:
    """Compare two ``inspect_package`` results."""
    kinds = _delta(before["part_kinds"], after["part_kinds"])  # type: ignore[arg-type]
    lost = sorted(kind for kind, (old, new) in kinds.items() if old > 0 and new == 0)
    content = _delta(before.get("content_counts", {}),  # type: ignore[arg-type]
                     after.get("content_counts", {}))  # type: ignore[arg-type]
    content_lost = sorted(
        key for key, (old, new) in content.items()
        if (CONTENT_RULES.get(key) == "decrease" and new < old)
        or (CONTENT_RULES.get(key) == "vanish" and old > 0 and new == 0))
    return {
        "content_counts_changed": content,
        "content_lost": content_lost,
        "family_changed": before["family"] != after["family"],
        "part_kinds_changed": kinds,
        "part_kinds_lost": lost,
        "critical_part_kinds_lost": [kind for kind in lost if kind in CRITICAL_PART_KINDS],
        "element_counts_changed": _delta(
            before["element_counts"], after["element_counts"]),  # type: ignore[arg-type]
        "fonts_removed": sorted(set(before["fonts"]) - set(after["fonts"])),  # type: ignore[arg-type]
        "fonts_added": sorted(set(after["fonts"]) - set(before["fonts"])),  # type: ignore[arg-type]
        "transitions_before": before["transitions"],
        "transitions_after": after["transitions"],
        "transitions_changed": before["transitions"] != after["transitions"],
        # effect names present before and absent after ("(none)" = element without effect)
        "transitions_lost": sorted(set(before["transitions"]) - set(after["transitions"])  # type: ignore[arg-type]
                                   - {"(none)"}),
    }


def is_zip_package(path: Path) -> bool:
    try:
        with Path(path).open("rb") as handle:
            return handle.read(4) == b"PK\x03\x04"
    except OSError:
        return False


def pdf_page_count(path: Path, limit: int = 256 * 1024 * 1024) -> Optional[int]:
    """Best-effort page count of a PDF written with a plain page tree.

    Reads the largest ``/Count`` of any ``/Type /Pages`` dictionary.
    Returns ``None`` when the file is not a PDF or the page tree is not
    stored in plain objects (for example inside object streams).
    """
    path = Path(path)
    try:
        if path.stat().st_size > limit:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if not data.startswith(b"%PDF-"):
        return None
    best: Optional[int] = None
    for match in re.finditer(rb"/Type\s*/Pages\b", data):
        # the whole object: from the "obj" before the marker to the "endobj" after it
        # (a page tree lists every page in /Kids, so the object can be long)
        start = data.rfind(b" obj", 0, match.start())
        end = data.find(b"endobj", match.end())
        if end < 0:
            continue
        counts = re.findall(rb"/Count\s+(\d+)", data[max(start, 0):end])
        for raw in counts:
            value = int(raw)
            best = value if best is None else max(best, value)
    return best


def iter_fonts(inventories: Iterable[Dict[str, object]]) -> List[str]:
    fonts = set()
    for inventory in inventories:
        fonts.update(inventory.get("fonts", []))  # type: ignore[arg-type]
    return sorted(fonts)
