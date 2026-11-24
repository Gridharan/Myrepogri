#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Generate the self-authored part of the seed corpus.

Every byte written by this script is original work of this project.  The
file formats are produced directly from their public specifications:

* ECMA-376 5th edition / ISO/IEC 29500 (Open Packaging Conventions,
  WordprocessingML, PresentationML, DrawingML);
* OASIS OpenDocument Format v1.3 (text and presentation documents);
* Rich Text Format Specification 1.9.1 (public Microsoft specification);
* PNG Specification, W3C Recommendation (the embedded test image).

No third-party document, template, theme, font or artwork is used: the
colour schemes, layouts and texts below are made up here.  Font *names*
appear only as references; no font data is embedded.

Output is deterministic (fixed timestamps, fixed ordering), so the
SHA-256 values recorded in ``corpus/MANIFEST.csv`` are reproducible.

Usage (from the repository root)::

    python3 -m tools.corpus.gen_seed --out corpus/self [--check]

Exit codes: 0 ok; 2 bad input; 7 ``--check`` found a file that differs
from what the generator produces.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from xml.etree import ElementTree

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DIFFERS = 7

FIXED_TIME = (2026, 1, 1, 0, 0, 0)
GENERATOR = "seed-corpus-generator"
XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
REL_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
CT = "application/vnd.openxmlformats-officedocument."

Files = List[Tuple[str, bytes]]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def png_image(width: int = 64, height: int = 48) -> bytes:
    """A small RGB gradient, encoded as PNG (W3C PNG specification)."""
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter type 0 (None)
        for x in range(width):
            rows += bytes((40 + (x * 215) // (width - 1), 90 + (y * 120) // (height - 1), 160))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


def build_zip(files: Files, stored_first: bool = False) -> bytes:
    """Write a deterministic ZIP; with ``stored_first`` the first entry is
    stored uncompressed (the ODF ``mimetype`` rule)."""
    import io
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index, (name, data) in enumerate(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.external_attr = 0o644 << 16
            info.create_system = 3
            stored = stored_first and index == 0
            info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=None if stored else 9)
    return buffer.getvalue()


def assert_well_formed(files: Files) -> None:
    for name, data in files:
        if name.endswith((".xml", ".rels")):
            try:
                ElementTree.fromstring(data)
            except ElementTree.ParseError as exc:
                raise AssertionError(f"{name}: generated XML is not well-formed: {exc}") from exc


def rels(items: Sequence[Tuple[str, str, str]], external: Sequence[str] = ()) -> bytes:
    """``items`` = (id, type-suffix-or-URI, target)."""
    out = [XML_DECL, f'<Relationships xmlns="{REL_PKG}">']
    for rid, kind, target in items:
        full = kind if kind.startswith("http") else REL + kind
        mode = ' TargetMode="External"' if rid in external else ""
        out.append(f'<Relationship Id="{rid}" Type="{full}" Target="{target}"{mode}/>')
    out.append("</Relationships>")
    return "".join(out).encode("utf-8")


def content_types(defaults: Dict[str, str], overrides: Dict[str, str]) -> bytes:
    out = [XML_DECL, f'<Types xmlns="{CT_NS}">']
    for ext, kind in defaults.items():
        out.append(f'<Default Extension="{ext}" ContentType="{kind}"/>')
    for part, kind in overrides.items():
        out.append(f'<Override PartName="{part}" ContentType="{kind}"/>')
    out.append("</Types>")
    return "".join(out).encode("utf-8")


def core_props(title: str) -> bytes:
    return (XML_DECL + (
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
        'core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{title}</dc:title><dc:creator>Seed Author</dc:creator>"
        '<dcterms:created xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:modified>'
        "</cp:coreProperties>")).encode("utf-8")


def app_props() -> bytes:
    return (XML_DECL + (
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
        f'extended-properties"><Application>{GENERATOR}</Application></Properties>'
    )).encode("utf-8")


PKG_RELS = rels([
    ("rId1", "officeDocument", "{main}"),
    ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/"
             "core-properties", "docProps/core.xml"),
    ("rId3", "extended-properties", "docProps/app.xml"),
])


def pkg_rels(main: str) -> bytes:
    return PKG_RELS.replace(b"{main}", main.encode("ascii"))


# --------------------------------------------------------------------------
# WordprocessingML
# --------------------------------------------------------------------------

def w_run(text: str, props: str = "") -> str:
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def w_para(content: str, style: str = "", extra_ppr: str = "") -> str:
    ppr = ""
    if style or extra_ppr:
        style_xml = f'<w:pStyle w:val="{style}"/>' if style else ""
        ppr = f"<w:pPr>{style_xml}{extra_ppr}</w:pPr>"
    return f"<w:p>{ppr}{content}</w:p>"


def w_font_run(text: str, font: str) -> str:
    return w_run(text, f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}"/>')


def w_styles(default_font: str = "Liberation Serif") -> bytes:
    def pstyle(sid: str, name: str, based: str = "Normal", ppr: str = "", rpr: str = "",
               default: bool = False) -> str:
        flag = ' w:default="1"' if default else ""
        base = f'<w:basedOn w:val="{based}"/>' if based and not default else ""
        ppr_xml = f"<w:pPr>{ppr}</w:pPr>" if ppr else ""
        rpr_xml = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
        return (f'<w:style w:type="paragraph"{flag} w:styleId="{sid}"><w:name w:val="{name}"/>'
                f"{base}<w:qFormat/>{ppr_xml}{rpr_xml}</w:style>")

    def cstyle(sid: str, name: str, rpr: str = "", default: bool = False) -> str:
        flag = ' w:default="1"' if default else ""
        rpr_xml = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
        return (f'<w:style w:type="character"{flag} w:styleId="{sid}">'
                f'<w:name w:val="{name}"/>{rpr_xml}</w:style>')

    borders = "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
                      for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    body = (
        f'<w:styles xmlns:w="{W_NS}"><w:docDefaults><w:rPrDefault><w:rPr>'
        f'<w:rFonts w:ascii="{default_font}" w:hAnsi="{default_font}" w:cs="{default_font}"/>'
        '<w:sz w:val="24"/><w:lang w:val="en-US"/></w:rPr></w:rPrDefault>'
        '<w:pPrDefault><w:pPr><w:spacing w:after="120"/></w:pPr></w:pPrDefault></w:docDefaults>'
        + pstyle("Normal", "Normal", default=True)
        + pstyle("Title", "Title", ppr='<w:jc w:val="center"/>', rpr='<w:b/><w:sz w:val="48"/>')
        + pstyle("Heading1", "heading 1",
                 ppr='<w:keepNext/><w:spacing w:before="240" w:after="120"/>'
                     '<w:outlineLvl w:val="0"/>',
                 rpr='<w:b/><w:sz w:val="36"/>')
        + pstyle("Heading2", "heading 2",
                 ppr='<w:keepNext/><w:spacing w:before="200" w:after="100"/>'
                     '<w:outlineLvl w:val="1"/>',
                 rpr='<w:b/><w:i/><w:sz w:val="28"/>')
        + pstyle("Quote", "Quote", ppr='<w:ind w:left="720" w:right="720"/>', rpr="<w:i/>")
        + pstyle("ListParagraph", "List Paragraph", ppr='<w:ind w:left="720"/>')
        + pstyle("Header", "header", ppr='<w:jc w:val="center"/>')
        + pstyle("Footer", "footer", ppr='<w:jc w:val="center"/>')
        + pstyle("FootnoteText", "footnote text", rpr='<w:sz w:val="20"/>')
        + pstyle("EndnoteText", "endnote text", rpr='<w:sz w:val="20"/>')
        + cstyle("DefaultParagraphFont", "Default Paragraph Font", default=True)
        + cstyle("Strong", "Strong", "<w:b/>")
        + cstyle("SeedAccent", "Seed Accent", '<w:color w:val="1F5C99"/><w:u w:val="single"/>')
        + cstyle("FootnoteReference", "footnote reference", '<w:vertAlign w:val="superscript"/>')
        + cstyle("EndnoteReference", "endnote reference", '<w:vertAlign w:val="superscript"/>')
        + cstyle("Hyperlink", "Hyperlink", '<w:color w:val="0000FF"/><w:u w:val="single"/>')
        + '<w:style w:type="table" w:default="1" w:styleId="TableNormal">'
          '<w:name w:val="Normal Table"/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/>'
          '<w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/>'
          '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar>'
          '</w:tblPr></w:style>'
        + '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/>'
          f'<w:basedOn w:val="TableNormal"/><w:tblPr><w:tblBorders>{borders}</w:tblBorders>'
          '</w:tblPr></w:style>'
        + "</w:styles>")
    return (XML_DECL + body).encode("utf-8")


def w_numbering() -> bytes:
    def level(fmt: str, text: str) -> str:
        return (f'<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/>'
                f'<w:lvlText w:val="{text}"/><w:lvlJc w:val="left"/>'
                '<w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl>')
    body = (f'<w:numbering xmlns:w="{W_NS}">'
            f'<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/>'
            f'{level("bullet", "•")}</w:abstractNum>'
            f'<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="singleLevel"/>'
            f'{level("decimal", "%1.")}</w:abstractNum>'
            '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
            '<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num></w:numbering>')
    return (XML_DECL + body).encode("utf-8")


def w_list_item(text: str, num_id: int) -> str:
    return w_para(w_run(text), "ListParagraph",
                  f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>')


def w_table() -> str:
    """3 columns x 3 rows; first row spans two columns, one vertical merge."""
    def cell(text: str, extra: str = "", width: int = 3000) -> str:
        return (f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{extra}</w:tcPr>'
                f"{w_para(w_run(text))}</w:tc>")
    grid = "".join('<w:gridCol w:w="3000"/>' for _ in range(3))
    rows = (
        "<w:tr>" + cell("Merged heading", '<w:gridSpan w:val="2"/>', 6000) + cell("C1") + "</w:tr>"
        "<w:tr>" + cell("A2", '<w:vMerge w:val="restart"/>') + cell("B2") + cell("C2") + "</w:tr>"
        "<w:tr>" + cell("", "<w:vMerge/>") + cell("B3") + cell("C3") + "</w:tr>")
    return ('<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="9000" w:type="dxa"/>'
            f"</w:tblPr><w:tblGrid>{grid}</w:tblGrid>{rows}</w:tbl>")


def w_picture(rid: str, shape_id: int, anchored: bool = False) -> str:
    graphic = (
        f'<a:graphic xmlns:a="{A_NS}"><a:graphicData uri="{PIC_NS}">'
        f'<pic:pic xmlns:pic="{PIC_NS}"><pic:nvPicPr><pic:cNvPr id="{shape_id}" '
        f'name="seed-image-{shape_id}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch>'
        '</pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/>'
        '<a:ext cx="1828800" cy="1371600"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/>'
        "</a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>")
    doc_pr = f'<wp:docPr id="{shape_id}" name="Seed picture {shape_id}"/>'
    extent = '<wp:extent cx="1828800" cy="1371600"/>'
    if not anchored:
        inner = (f'<wp:inline distT="0" distB="0" distL="0" distR="0">{extent}{doc_pr}'
                 f"<wp:cNvGraphicFramePr/>{graphic}</wp:inline>")
    else:
        inner = (
            '<wp:anchor distT="0" distB="0" distL="114300" distR="114300" simplePos="0" '
            'relativeHeight="251658240" behindDoc="0" locked="0" layoutInCell="1" '
            'allowOverlap="1"><wp:simplePos x="0" y="0"/>'
            '<wp:positionH relativeFrom="column"><wp:posOffset>3200400</wp:posOffset>'
            '</wp:positionH><wp:positionV relativeFrom="paragraph"><wp:posOffset>0'
            f'</wp:posOffset></wp:positionV>{extent}'
            '<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapSquare wrapText="bothSides"/>'
            f"{doc_pr}<wp:cNvGraphicFramePr/>{graphic}</wp:anchor>")
    return f"<w:r><w:drawing>{inner}</w:drawing></w:r>"


SECT_A4 = ('<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" '
           'w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/>')
SECT_A4_LANDSCAPE = ('<w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>'
                     '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
                     'w:header="708" w:footer="708" w:gutter="0"/>')


def w_document(body: str, final_sect: str) -> bytes:
    xml = (f'<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}" xmlns:wp="{WP_NS}">'
           f"<w:body>{body}<w:sectPr>{final_sect}</w:sectPr></w:body></w:document>")
    return (XML_DECL + xml).encode("utf-8")


def w_notes(kind: str, texts: Sequence[str]) -> bytes:
    """footnotes.xml / endnotes.xml with the two separator notes first."""
    tag, ref, style = ((("footnote", "footnoteRef", "FootnoteText")) if kind == "footnotes"
                       else ("endnote", "endnoteRef", "EndnoteText"))
    ref_style = "FootnoteReference" if kind == "footnotes" else "EndnoteReference"
    notes = [
        f'<w:{tag} w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:{tag}>',
        f'<w:{tag} w:type="continuationSeparator" w:id="0"><w:p><w:r>'
        f"<w:continuationSeparator/></w:r></w:p></w:{tag}>",
    ]
    for index, text in enumerate(texts, 1):
        notes.append(
            f'<w:{tag} w:id="{index}">'
            + w_para(f'<w:r><w:rPr><w:rStyle w:val="{ref_style}"/></w:rPr><w:{ref}/></w:r>'
                     + w_run(" " + text), style)
            + f"</w:{tag}>")
    return (XML_DECL + f'<w:{kind} xmlns:w="{W_NS}">{"".join(notes)}</w:{kind}>').encode("utf-8")


def w_header_footer(kind: str, content: str) -> bytes:
    tag = "hdr" if kind == "header" else "ftr"
    style = "Header" if kind == "header" else "Footer"
    xml = f'<w:{tag} xmlns:w="{W_NS}" xmlns:r="{R_NS}">{w_para(content, style)}</w:{tag}>'
    return (XML_DECL + xml).encode("utf-8")


def w_settings() -> bytes:
    xml = (f'<w:settings xmlns:w="{W_NS}"><w:defaultTabStop w:val="720"/>'
           '<w:footnotePr><w:footnote w:id="-1"/><w:footnote w:id="0"/></w:footnotePr>'
           '<w:endnotePr><w:endnote w:id="-1"/><w:endnote w:id="0"/></w:endnotePr>'
           '<w:compat><w:compatSetting w:name="compatibilityMode" '
           'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat>'
           "</w:settings>")
    return (XML_DECL + xml).encode("utf-8")


W_CT = {
    "document": CT + "wordprocessingml.document.main+xml",
    "template": CT + "wordprocessingml.template.main+xml",
    "styles": CT + "wordprocessingml.styles+xml",
    "numbering": CT + "wordprocessingml.numbering+xml",
    "settings": CT + "wordprocessingml.settings+xml",
    "footnotes": CT + "wordprocessingml.footnotes+xml",
    "endnotes": CT + "wordprocessingml.endnotes+xml",
    "comments": CT + "wordprocessingml.comments+xml",
    "header": CT + "wordprocessingml.header+xml",
    "footer": CT + "wordprocessingml.footer+xml",
}


def word_package(title: str, document: bytes, parts: Dict[str, bytes],
                 doc_rels: List[Tuple[str, str, str]], external: Sequence[str] = (),
                 template: bool = False, default_font: str = "Liberation Serif") -> bytes:
    """Assemble a WordprocessingML package; ``parts`` are extra word/* parts."""
    overrides = {
        "/word/document.xml": W_CT["template" if template else "document"],
        "/word/styles.xml": W_CT["styles"],
        "/word/settings.xml": W_CT["settings"],
        "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
        "/docProps/app.xml": CT + "extended-properties+xml",
    }
    for name in parts:
        stem = name.split("/")[-1]
        for key in ("numbering", "footnotes", "endnotes", "comments", "header", "footer"):
            if stem.startswith(key):
                overrides["/" + name] = W_CT[key]
    all_rels = [("rIdStyles", "styles", "styles.xml"),
                ("rIdSettings", "settings", "settings.xml")] + doc_rels
    files: Files = [
        ("[Content_Types].xml", content_types(
            {"rels": "application/vnd.openxmlformats-package.relationships+xml",
             "xml": "application/xml", "png": "image/png"}, overrides)),
        ("_rels/.rels", pkg_rels("word/document.xml")),
        ("docProps/core.xml", core_props(title)),
        ("docProps/app.xml", app_props()),
        ("word/document.xml", document),
        ("word/_rels/document.xml.rels", rels(all_rels, external)),
        ("word/styles.xml", w_styles(default_font)),
        ("word/settings.xml", w_settings()),
    ]
    files += sorted(parts.items())
    assert_well_formed(files)
    return build_zip(files)


def docx_basic(template: bool = False) -> bytes:
    hyperlink = ('<w:hyperlink r:id="rIdLink1"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/>'
                 '</w:rPr><w:t>an external link</w:t></w:r></w:hyperlink>')
    bookmark = ('<w:bookmarkStart w:id="1" w:name="seed_bookmark"/>'
                + w_run("bookmarked text") + '<w:bookmarkEnd w:id="1"/>')
    body = (
        w_para(w_run("Seed document: basic structure"), "Title")
        + w_para(w_run("Paragraph and character formatting"), "Heading1")
        + w_para(w_run("Plain text, ") + w_run("bold", "<w:b/>") + w_run(", ")
                 + w_run("italic", "<w:i/>") + w_run(", ")
                 + w_run("underlined", '<w:u w:val="single"/>') + w_run(", ")
                 + w_run("a character style", '<w:rStyle w:val="SeedAccent"/>')
                 + w_run(", coloured ", '<w:color w:val="B22222"/>')
                 + w_run("and highlighted.", '<w:highlight w:val="yellow"/>'))
        + w_para(w_run("A quotation paragraph that uses its own paragraph style."), "Quote")
        + w_para(w_run("Centred text."), "", '<w:jc w:val="center"/>')
        + w_para(w_run("Justified text with first-line indent. " * 4), "",
                 '<w:ind w:firstLine="360"/><w:jc w:val="both"/>')
        + w_para(w_run("Lists"), "Heading2")
        + w_list_item("First bullet", 1) + w_list_item("Second bullet", 1)
        + w_list_item("Third bullet", 1)
        + w_list_item("Step one", 2) + w_list_item("Step two", 2)
        + w_para(w_run("Table"), "Heading2")
        + w_table()
        + w_para(w_run("Links"), "Heading2")
        + w_para(w_run("This paragraph has ") + hyperlink + w_run(" and ") + bookmark
                 + w_run("."))
        + w_para('<w:r><w:br w:type="page"/></w:r>' + w_run("Text after a manual page break."))
        # section break: everything above is portrait, the rest landscape in two columns
        + w_para("", "", f"<w:sectPr>{SECT_A4}</w:sectPr>")
        + w_para(w_run("Landscape section"), "Heading1")
        + w_para(w_run("This section is landscape and uses two columns. " * 6))
    )
    final = SECT_A4_LANDSCAPE + '<w:cols w:num="2" w:space="708"/>'
    return word_package(
        "Seed basic", w_document(body, final),
        {"word/numbering.xml": w_numbering()},
        [("rIdNumbering", "numbering", "numbering.xml"),
         ("rIdLink1", "hyperlink", "https://example.org/")],
        external=("rIdLink1",), template=template)


def docx_notes_headers() -> bytes:
    def field(instr: str, shown: str) -> str:
        escaped = instr.replace("&", "&amp;").replace('"', "&quot;")
        return (f'<w:fldSimple w:instr=" {escaped} "><w:r><w:t>{shown}</w:t></w:r>'
                "</w:fldSimple>")

    toc = (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-2" \\h \\z \\u </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + w_run("Update this table of contents to show entries.")
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')

    def note_ref(kind: str, number: int) -> str:
        style = "FootnoteReference" if kind == "footnote" else "EndnoteReference"
        return (f'<w:r><w:rPr><w:rStyle w:val="{style}"/></w:rPr>'
                f'<w:{kind}Reference w:id="{number}"/></w:r>')

    filler = "Body text that fills the page so that the document needs more than one page. "
    body = (
        w_para(w_run("Seed document: notes, headers and a table of contents"), "Title")
        + w_para(toc)
        + w_para(w_run("First chapter"), "Heading1")
        + w_para(w_run("A sentence with a footnote") + note_ref("footnote", 1)
                 + w_run(" and a second footnote") + note_ref("footnote", 2) + w_run("."))
        + w_para(w_run("Details"), "Heading2")
        + w_para(w_run("A sentence with an endnote") + note_ref("endnote", 1) + w_run("."))
        + "".join(w_para(w_run(filler * 6)) for _ in range(8))
        + w_para(w_run("Second chapter"), "Heading1")
        + w_para(w_run("Document date field: ") + field('DATE \\@ "yyyy-MM-dd"', "2026-01-01"))
        + "".join(w_para(w_run(filler * 6)) for _ in range(8))
    )
    final = ('<w:headerReference w:type="default" r:id="rIdHeader1"/>'
             '<w:headerReference w:type="first" r:id="rIdHeader2"/>'
             '<w:footerReference w:type="default" r:id="rIdFooter1"/>'
             + SECT_A4 + "<w:titlePg/>")
    footer = w_run("Page ") + field("PAGE", "1") + w_run(" of ") + field("NUMPAGES", "1")
    parts = {
        "word/footnotes.xml": w_notes("footnotes", ["First footnote text.",
                                                    "Second footnote text."]),
        "word/endnotes.xml": w_notes("endnotes", ["The only endnote."]),
        "word/header1.xml": w_header_footer("header", w_run("Seed running header")),
        "word/header2.xml": w_header_footer("header", w_run("Seed first-page header")),
        "word/footer1.xml": w_header_footer("footer", footer),
    }
    doc_rels = [("rIdFootnotes", "footnotes", "footnotes.xml"),
                ("rIdEndnotes", "endnotes", "endnotes.xml"),
                ("rIdHeader1", "header", "header1.xml"),
                ("rIdHeader2", "header", "header2.xml"),
                ("rIdFooter1", "footer", "footer1.xml")]
    return word_package("Seed notes and headers", w_document(body, final), parts, doc_rels)


def docx_review() -> bytes:
    meta = 'w:author="Seed Reviewer" w:date="2026-01-02T09:00:00Z"'

    def comment_span(cid: int, inner: str) -> str:
        return (f'<w:commentRangeStart w:id="{cid}"/>{inner}<w:commentRangeEnd w:id="{cid}"/>'
                f'<w:r><w:commentReference w:id="{cid}"/></w:r>')

    body = (
        w_para(w_run("Seed document: tracked changes and comments"), "Title")
        + w_para(w_run("This sentence has ")
                 + f'<w:ins w:id="101" {meta}>{w_run("an inserted phrase ")}</w:ins>'
                 + w_run("and ")
                 + f'<w:del w:id="102" {meta}><w:r><w:delText xml:space="preserve">'
                   "a deleted phrase </w:delText></w:r></w:del>"
                 + w_run("in the middle."))
        + w_para(w_run("A whole inserted paragraph follows."))
        + f'<w:p><w:pPr><w:rPr><w:ins w:id="103" {meta}/></w:rPr></w:pPr>'
          f'<w:ins w:id="104" {meta}>{w_run("This paragraph was inserted by the reviewer.")}'
          "</w:ins></w:p>"
        + w_para(w_run("Formatting change: ")
                 + f'<w:r><w:rPr><w:b/><w:rPrChange w:id="105" {meta}><w:rPr/></w:rPrChange>'
                   '</w:rPr><w:t xml:space="preserve">this run became bold</w:t></w:r>'
                 + w_run("."))
        + w_para(w_run("The reviewer commented on ")
                 + comment_span(0, w_run("this phrase")) + w_run(" and on ")
                 + comment_span(1, w_run("that phrase")) + w_run("."))
    )
    comments = (
        f'<w:comments xmlns:w="{W_NS}">'
        '<w:comment w:id="0" w:author="Seed Reviewer" w:date="2026-01-02T09:05:00Z" '
        f'w:initials="SR">{w_para(w_run("Please check this wording."))}</w:comment>'
        '<w:comment w:id="1" w:author="Second Reader" w:date="2026-01-03T10:00:00Z" '
        f'w:initials="2R">{w_para(w_run("I agree with the first comment."))}</w:comment>'
        "</w:comments>")
    return word_package(
        "Seed review", w_document(body, SECT_A4),
        {"word/comments.xml": (XML_DECL + comments).encode("utf-8")},
        [("rIdComments", "comments", "comments.xml")])


def docx_images() -> bytes:
    body = (
        w_para(w_run("Seed document: pictures"), "Title")
        + w_para(w_run("An inline picture: ") + w_picture("rIdImage1", 1))
        + w_para(w_picture("rIdImage1", 2, anchored=True)
                 + w_run("A floating picture is anchored to this paragraph and the text "
                         "wraps around it. " * 5))
    )
    return word_package(
        "Seed images", w_document(body, SECT_A4), {"word/media/image1.png": png_image()},
        [("rIdImage1", "image", "media/image1.png")])


#: Font names referenced by ``docx_fonts``: proprietary families first, then
#: families that upstream bundles.  Only names are written, never font data.
FONT_PROBE = ("Calibri", "Cambria", "Aptos", "Segoe UI", "Arial", "Times New Roman",
              "Courier New", "Consolas", "Verdana", "Tahoma", "Liberation Sans",
              "Liberation Serif", "Carlito", "Caladea")


def docx_fonts() -> bytes:
    sample = "The quick brown fox jumps over the lazy dog 0123456789. "
    body = w_para(w_run("Seed document: font references"), "Title")
    for font in FONT_PROBE:
        body += w_para(w_font_run(f"{font}: " + sample * 3, font))
    return word_package("Seed fonts", w_document(body, SECT_A4), {}, [],
                        default_font="Calibri")


# --------------------------------------------------------------------------
# PresentationML
# --------------------------------------------------------------------------

P_ROOT_NS = f'xmlns:a="{A_NS}" xmlns:r="{R_NS}" xmlns:p="{P_NS}"'
GROUP_HEAD = ('<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
              '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
              '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>')
SLIDE_W, SLIDE_H = 12192000, 6858000


def p_placeholder(shape_id: int, name: str, ph: str, paragraphs: Sequence[str],
                  geometry: Optional[Tuple[int, int, int, int]] = None) -> str:
    xfrm = ""
    if geometry:
        x, y, cx, cy = geometry
        xfrm = f'<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
    paras = "".join(paragraphs) or "<a:p><a:endParaRPr lang=\"en-US\"/></a:p>"
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="{name}"/>'
            '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
            f"<p:nvPr><p:ph {ph}/></p:nvPr></p:nvSpPr><p:spPr>{xfrm}</p:spPr>"
            f"<p:txBody><a:bodyPr/><a:lstStyle/>{paras}</p:txBody></p:sp>")


def a_para(text: str, level: int = 0, props: str = "") -> str:
    ppr = f'<a:pPr lvl="{level}"/>' if level else ""
    return f'<a:p>{ppr}<a:r><a:rPr lang="en-US"{props}/><a:t>{text}</a:t></a:r></a:p>'


def p_theme(name: str) -> bytes:
    def colour(tag: str, value: str) -> str:
        return f'<a:{tag}><a:srgbClr val="{value}"/></a:{tag}>'
    scheme = "".join(colour(tag, value) for tag, value in (
        ("dk1", "1A1A1A"), ("lt1", "FFFFFF"), ("dk2", "23395B"), ("lt2", "EEF2F6"),
        ("accent1", "2F6F9F"), ("accent2", "C4572E"), ("accent3", "6A8F3B"),
        ("accent4", "8B5FA8"), ("accent5", "D49B1F"), ("accent6", "3C9A9A"),
        ("hlink", "1F5C99"), ("folHlink", "6B4E8A")))
    fonts = "".join(
        f'<a:{tag}><a:latin typeface="{face}"/><a:ea typeface=""/><a:cs typeface=""/></a:{tag}>'
        for tag, face in (("majorFont", "Liberation Sans"), ("minorFont", "Liberation Sans")))
    solid = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    line = ('<a:ln w="9525" cap="flat" cmpd="sng" algn="ctr"><a:solidFill>'
            '<a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>')
    effect = "<a:effectStyle><a:effectLst/></a:effectStyle>"
    xml = (f'<a:theme xmlns:a="{A_NS}" name="{name}"><a:themeElements>'
           f'<a:clrScheme name="Seed colours">{scheme}</a:clrScheme>'
           f'<a:fontScheme name="Seed fonts">{fonts}</a:fontScheme>'
           f'<a:fmtScheme name="Seed formats"><a:fillStyleLst>{solid * 3}</a:fillStyleLst>'
           f"<a:lnStyleLst>{line * 3}</a:lnStyleLst>"
           f"<a:effectStyleLst>{effect * 3}</a:effectStyleLst>"
           f"<a:bgFillStyleLst>{solid * 3}</a:bgFillStyleLst></a:fmtScheme>"
           "</a:themeElements></a:theme>")
    return (XML_DECL + xml).encode("utf-8")


CLR_MAP = ('<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
           'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
           'accent6="accent6" hlink="hlink" folHlink="folHlink"/>')
TITLE_BOX = (838200, 365125, 10515600, 1325563)
BODY_BOX = (838200, 1825625, 10515600, 4351338)


def p_master() -> bytes:
    def level_style(tag: str, size: int, bold: str = "") -> str:
        return (f'<a:{tag} marL="0" indent="0" algn="l"><a:defRPr sz="{size}"{bold}>'
                '<a:solidFill><a:schemeClr val="tx1"/></a:solidFill>'
                '<a:latin typeface="+mn-lt"/></a:defRPr></a:' + tag + ">")
    tree = (GROUP_HEAD
            + p_placeholder(2, "Title Placeholder 1", 'type="title"',
                            [a_para("Master title style")], TITLE_BOX)
            + p_placeholder(3, "Text Placeholder 2", 'type="body" idx="1"',
                            [a_para("Master text styles"), a_para("Second level", 1)],
                            BODY_BOX))
    xml = (f"<p:sldMaster {P_ROOT_NS}><p:cSld><p:bg><p:bgRef idx=\"1001\">"
           '<a:schemeClr val="bg1"/></p:bgRef></p:bg>'
           f"<p:spTree>{tree}</p:spTree></p:cSld>{CLR_MAP}"
           '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/>'
           '<p:sldLayoutId id="2147483650" r:id="rId2"/></p:sldLayoutIdLst>'
           "<p:txStyles><p:titleStyle>" + level_style("lvl1pPr", 4400, ' b="1"')
           + "</p:titleStyle><p:bodyStyle>" + level_style("lvl1pPr", 2800)
           + level_style("lvl2pPr", 2400) + "</p:bodyStyle><p:otherStyle>"
           + level_style("lvl1pPr", 1800) + "</p:otherStyle></p:txStyles></p:sldMaster>")
    return (XML_DECL + xml).encode("utf-8")


def p_layout(kind: str, name: str) -> bytes:
    if kind == "title":
        tree = (p_placeholder(2, "Title 1", 'type="ctrTitle"', [a_para("Layout title")],
                              (1524000, 1122363, 9144000, 2387600))
                + p_placeholder(3, "Subtitle 2", 'type="subTitle" idx="1"',
                                [a_para("Layout subtitle")],
                                (1524000, 3602038, 9144000, 1655762)))
    else:
        tree = (p_placeholder(2, "Title 1", 'type="title"', [a_para("Layout title")])
                + p_placeholder(3, "Content Placeholder 2", 'idx="1"',
                                [a_para("Layout text")]))
    xml = (f'<p:sldLayout {P_ROOT_NS} type="{kind}" preserve="1"><p:cSld name="{name}">'
           f"<p:spTree>{GROUP_HEAD}{tree}</p:spTree></p:cSld>"
           "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>")
    return (XML_DECL + xml).encode("utf-8")


def p_table(shape_id: int) -> str:
    def cell(text: str) -> str:
        return (f"<a:tc><a:txBody><a:bodyPr/><a:lstStyle/>{a_para(text)}</a:txBody>"
                "<a:tcPr/></a:tc>")
    rows = "".join(
        '<a:tr h="370840">' + "".join(cell(f"{col}{row}") for col in "ABC") + "</a:tr>"
        for row in (1, 2, 3))
    grid = '<a:gridCol w="2032000"/>' * 3
    return (f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{shape_id}" name="Seed table"/>'
            '<p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr>'
            '<p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="838200" y="1825625"/>'
            '<a:ext cx="6096000" cy="1112520"/></p:xfrm><a:graphic><a:graphicData '
            f'uri="{A_NS[:-4]}table"><a:tbl><a:tblPr firstRow="1" bandRow="1"/>'
            f"<a:tblGrid>{grid}</a:tblGrid>{rows}</a:tbl></a:graphicData></a:graphic>"
            "</p:graphicFrame>")


def p_picture(shape_id: int, rid: str) -> str:
    return (f'<p:pic><p:nvPicPr><p:cNvPr id="{shape_id}" name="Seed picture"/>'
            '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
            f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch>'
            '</p:blipFill><p:spPr><a:xfrm><a:off x="7620000" y="1825625"/>'
            '<a:ext cx="3657600" cy="2743200"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/>'
            "</a:prstGeom></p:spPr></p:pic>")


def p_shape(shape_id: int, name: str, preset: str, box: Tuple[int, int, int, int],
            text: str) -> str:
    x, y, cx, cy = box
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="{name}"/><p:cNvSpPr/><p:nvPr/>'
            f'</p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/>'
            f'</a:xfrm><a:prstGeom prst="{preset}"><a:avLst/></a:prstGeom>'
            '<a:solidFill><a:schemeClr val="accent1"/></a:solidFill></p:spPr>'
            f'<p:txBody><a:bodyPr anchor="ctr"/><a:lstStyle/>{a_para(text)}</p:txBody></p:sp>')


def p_appear_timing(target_ids: Sequence[int]) -> str:
    """Main sequence with one on-click "appear" entrance effect per target
    (ECMA-376 Part 1, 19.5: p:timing / p:tnLst / p:par / p:seq / p:set)."""
    counter = [2]

    def next_id() -> int:
        counter[0] += 1
        return counter[0]

    effects = []
    for group, target in enumerate(target_ids):
        outer, middle, effect, behaviour = next_id(), next_id(), next_id(), next_id()
        effects.append(
            f'<p:par><p:cTn id="{outer}" fill="hold"><p:stCondLst>'
            '<p:cond delay="indefinite"/></p:stCondLst><p:childTnLst>'
            f'<p:par><p:cTn id="{middle}" fill="hold"><p:stCondLst><p:cond delay="0"/>'
            "</p:stCondLst><p:childTnLst>"
            f'<p:par><p:cTn id="{effect}" presetID="1" presetClass="entr" presetSubtype="0" '
            f'fill="hold" grpId="{group}" nodeType="clickEffect"><p:stCondLst>'
            '<p:cond delay="0"/></p:stCondLst><p:childTnLst>'
            f'<p:set><p:cBhvr><p:cTn id="{behaviour}" dur="1" fill="hold"><p:stCondLst>'
            '<p:cond delay="0"/></p:stCondLst></p:cTn>'
            f'<p:tgtEl><p:spTgt spid="{target}"/></p:tgtEl>'
            "<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst>"
            '</p:cBhvr><p:to><p:strVal val="visible"/></p:to></p:set>'
            "</p:childTnLst></p:cTn></p:par>"
            "</p:childTnLst></p:cTn></p:par>"
            "</p:childTnLst></p:cTn></p:par>")
    build = "".join(f'<p:bldP spid="{target}" grpId="{group}" animBg="1"/>'
                    for group, target in enumerate(target_ids))
    return (
        '<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" '
        'nodeType="tmRoot"><p:childTnLst><p:seq concurrent="1" nextAc="seek">'
        '<p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
        + "".join(effects)
        + '</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl>'
          '<p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst><p:nextCondLst>'
          '<p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond>'
          "</p:nextCondLst></p:seq></p:childTnLst></p:cTn></p:par></p:tnLst>"
        f"<p:bldLst>{build}</p:bldLst></p:timing>")


def p_slide(tree: str, transition: str = "", timing: str = "", hidden: bool = False) -> bytes:
    show = ' show="0"' if hidden else ""
    xml = (f"<p:sld {P_ROOT_NS}{show}><p:cSld><p:spTree>{GROUP_HEAD}{tree}</p:spTree></p:cSld>"
           f"<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>{transition}{timing}</p:sld>")
    return (XML_DECL + xml).encode("utf-8")


def p_notes_master() -> bytes:
    tree = (GROUP_HEAD
            + '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/>'
              '<p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr>'
              '<p:nvPr><p:ph type="sldImg" idx="2"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm>'
              '<a:off x="685800" y="1143000"/><a:ext cx="5486400" cy="3086100"/></a:xfrm>'
              '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:sp>'
            + p_placeholder(3, "Notes Placeholder 2", 'type="body" sz="quarter" idx="3"',
                            [a_para("Notes text style")],
                            (685800, 4400550, 5486400, 3600450)))
    xml = (f"<p:notesMaster {P_ROOT_NS}><p:cSld><p:spTree>{tree}</p:spTree></p:cSld>"
           f"{CLR_MAP}</p:notesMaster>")
    return (XML_DECL + xml).encode("utf-8")


def p_notes(text: str) -> bytes:
    tree = (GROUP_HEAD
            + '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/>'
              '<p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr>'
              '<p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr><p:spPr/></p:sp>'
            + p_placeholder(3, "Notes Placeholder 2", 'type="body" idx="1"', [a_para(text)]))
    xml = (f"<p:notes {P_ROOT_NS}><p:cSld><p:spTree>{tree}</p:spTree></p:cSld>"
           "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>")
    return (XML_DECL + xml).encode("utf-8")


P_MAIN_CT = {
    "pptx": CT + "presentationml.presentation.main+xml",
    "ppsx": CT + "presentationml.slideshow.main+xml",
    "potx": CT + "presentationml.template.main+xml",
}


def pptx_basic(kind: str = "pptx") -> bytes:
    slides = [
        p_slide(
            p_placeholder(2, "Title 1", 'type="ctrTitle"', [a_para("Seed presentation")])
            + p_placeholder(3, "Subtitle 2", 'type="subTitle" idx="1"',
                            [a_para("Self-authored fidelity sample")])),
        p_slide(
            p_placeholder(2, "Title 1", 'type="title"', [a_para("Bullets and notes")])
            + p_placeholder(3, "Content Placeholder 2", 'idx="1"',
                            [a_para("First point"), a_para("Second point"),
                             a_para("Nested point", 1), a_para("Third point")]),
            transition='<p:transition spd="med"><p:fade/></p:transition>',
            timing=p_appear_timing([3])),
        p_slide(
            p_placeholder(2, "Title 1", 'type="title"', [a_para("Table and picture")])
            + p_table(4) + p_picture(5, "rId2"),
            transition='<p:transition spd="slow"><p:push dir="l"/></p:transition>'),
        p_slide(
            p_placeholder(2, "Title 1", 'type="title"', [a_para("Shapes and animation")])
            + p_shape(4, "Rounded box", "roundRect", (838200, 1825625, 3048000, 1524000), "One")
            + p_shape(5, "Ellipse", "ellipse", (4572000, 1825625, 3048000, 1524000), "Two")
            + p_shape(6, "Arrow", "rightArrow", (8305800, 1825625, 3048000, 1524000), "Three"),
            transition='<p:transition spd="fast" advClick="1" advTm="5000">'
                       '<p:wipe dir="r"/></p:transition>',
            timing=p_appear_timing([4, 5, 6])),
        p_slide(
            p_placeholder(2, "Title 1", 'type="title"', [a_para("Hidden slide")])
            + p_placeholder(3, "Content Placeholder 2", 'idx="1"',
                            [a_para("This slide is marked hidden.")]),
            hidden=True),
    ]
    layout_of = [1, 2, 2, 2, 2]
    notes_text = {2: "Speaker notes for the bullets slide.",
                  4: "Speaker notes for the animation slide."}

    overrides = {
        "/ppt/presentation.xml": P_MAIN_CT[kind],
        "/ppt/slideMasters/slideMaster1.xml": CT + "presentationml.slideMaster+xml",
        "/ppt/slideLayouts/slideLayout1.xml": CT + "presentationml.slideLayout+xml",
        "/ppt/slideLayouts/slideLayout2.xml": CT + "presentationml.slideLayout+xml",
        "/ppt/notesMasters/notesMaster1.xml": CT + "presentationml.notesMaster+xml",
        "/ppt/theme/theme1.xml": CT + "theme+xml",
        "/ppt/theme/theme2.xml": CT + "theme+xml",
        "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
        "/docProps/app.xml": CT + "extended-properties+xml",
    }
    files: Files = []
    pres_rels = [("rId1", "slideMaster", "slideMasters/slideMaster1.xml"),
                 ("rId2", "notesMaster", "notesMasters/notesMaster1.xml"),
                 ("rId3", "theme", "theme/theme1.xml")]
    slide_ids = []
    for number, data in enumerate(slides, 1):
        name = f"ppt/slides/slide{number}.xml"
        overrides["/" + name] = CT + "presentationml.slide+xml"
        files.append((name, data))
        slide_rels = [("rId1", "slideLayout",
                       f"../slideLayouts/slideLayout{layout_of[number - 1]}.xml")]
        if number == 3:
            slide_rels.append(("rId2", "image", "../media/image1.png"))
        if number in notes_text:
            slide_rels.append(("rId9", "notesSlide", f"../notesSlides/notesSlide{number}.xml"))
            notes_name = f"ppt/notesSlides/notesSlide{number}.xml"
            overrides["/" + notes_name] = CT + "presentationml.notesSlide+xml"
            files.append((notes_name, p_notes(notes_text[number])))
            files.append((f"ppt/notesSlides/_rels/notesSlide{number}.xml.rels", rels([
                ("rId1", "notesMaster", "../notesMasters/notesMaster1.xml"),
                ("rId2", "slide", f"../slides/slide{number}.xml")])))
        files.append((f"ppt/slides/_rels/slide{number}.xml.rels", rels(slide_rels)))
        rid = f"rId{10 + number}"
        pres_rels.append((rid, "slide", f"slides/slide{number}.xml"))
        slide_ids.append(f'<p:sldId id="{255 + number}" r:id="{rid}"/>')

    presentation = (
        f"<p:presentation {P_ROOT_NS}><p:sldMasterIdLst>"
        '<p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        '<p:notesMasterIdLst><p:notesMasterId r:id="rId2"/></p:notesMasterIdLst>'
        f'<p:sldIdLst>{"".join(slide_ids)}</p:sldIdLst>'
        f'<p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}"/><p:notesSz cx="6858000" cy="9144000"/>'
        "</p:presentation>")
    files = [
        ("[Content_Types].xml", content_types(
            {"rels": "application/vnd.openxmlformats-package.relationships+xml",
             "xml": "application/xml", "png": "image/png"}, overrides)),
        ("_rels/.rels", pkg_rels("ppt/presentation.xml")),
        ("docProps/core.xml", core_props("Seed presentation")),
        ("docProps/app.xml", app_props()),
        ("ppt/presentation.xml", (XML_DECL + presentation).encode("utf-8")),
        ("ppt/_rels/presentation.xml.rels", rels(pres_rels)),
        ("ppt/slideMasters/slideMaster1.xml", p_master()),
        ("ppt/slideMasters/_rels/slideMaster1.xml.rels", rels([
            ("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml"),
            ("rId2", "slideLayout", "../slideLayouts/slideLayout2.xml"),
            ("rId3", "theme", "../theme/theme1.xml")])),
        ("ppt/slideLayouts/slideLayout1.xml", p_layout("title", "Seed Title Slide")),
        ("ppt/slideLayouts/_rels/slideLayout1.xml.rels", rels([
            ("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")])),
        ("ppt/slideLayouts/slideLayout2.xml", p_layout("obj", "Seed Title and Content")),
        ("ppt/slideLayouts/_rels/slideLayout2.xml.rels", rels([
            ("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")])),
        ("ppt/notesMasters/notesMaster1.xml", p_notes_master()),
        ("ppt/notesMasters/_rels/notesMaster1.xml.rels", rels([
            ("rId1", "theme", "../theme/theme2.xml")])),
        ("ppt/theme/theme1.xml", p_theme("Seed theme")),
        ("ppt/theme/theme2.xml", p_theme("Seed notes theme")),
        ("ppt/media/image1.png", png_image()),
    ] + files
    assert_well_formed(files)
    return build_zip(files)


# --------------------------------------------------------------------------
# OpenDocument
# --------------------------------------------------------------------------

ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
    'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" '
    'xmlns:smil="urn:oasis:names:tc:opendocument:xmlns:smil-compatible:1.0" '
    'office:version="1.3"')
ODF_DECL = '<?xml version="1.0" encoding="UTF-8"?>\n'


def odf_manifest(mimetype: str, entries: Sequence[Tuple[str, str]]) -> bytes:
    rows = [f'<manifest:file-entry manifest:full-path="/" manifest:version="1.3" '
            f'manifest:media-type="{mimetype}"/>']
    rows += [f'<manifest:file-entry manifest:full-path="{path}" '
             f'manifest:media-type="{kind}"/>' for path, kind in entries]
    xml = ('<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:'
           'manifest:1.0" manifest:version="1.3">' + "".join(rows) + "</manifest:manifest>")
    return (ODF_DECL + xml).encode("utf-8")


def odf_meta(title: str) -> bytes:
    xml = (f"<office:document-meta {ODF_NS}><office:meta><meta:generator>{GENERATOR}"
           f"</meta:generator><dc:title>{title}</dc:title>"
           "<meta:creation-date>2026-01-01T00:00:00</meta:creation-date>"
           "<dc:date>2026-01-01T00:00:00</dc:date></office:meta></office:document-meta>")
    return (ODF_DECL + xml).encode("utf-8")


def odf_package(mimetype: str, title: str, content: str, styles: str,
                extra: Sequence[Tuple[str, str, bytes]] = ()) -> bytes:
    files: Files = [
        ("mimetype", mimetype.encode("ascii")),
        ("META-INF/manifest.xml", odf_manifest(
            mimetype, [("content.xml", "text/xml"), ("styles.xml", "text/xml"),
                       ("meta.xml", "text/xml")] + [(p, k) for p, k, _ in extra])),
        ("content.xml", (ODF_DECL + content).encode("utf-8")),
        ("styles.xml", (ODF_DECL + styles).encode("utf-8")),
        ("meta.xml", odf_meta(title)),
    ] + [(path, data) for path, _kind, data in extra]
    assert_well_formed([(n, d) for n, d in files if n != "mimetype"])
    return build_zip(files, stored_first=True)


def odt_basic() -> bytes:
    def cell(text: str) -> str:
        return (f'<table:table-cell office:value-type="string"><text:p>{text}</text:p>'
                "</table:table-cell>")
    table = ('<table:table table:name="SeedTable"><table:table-column '
             'table:number-columns-repeated="3"/>'
             + "".join("<table:table-row>" + "".join(cell(f"{c}{r}") for c in "ABC")
                       + "</table:table-row>" for r in (1, 2, 3))
             + "</table:table>")
    note = ('<text:note text:id="ftn1" text:note-class="footnote"><text:note-citation>1'
            "</text:note-citation><text:note-body><text:p>An OpenDocument footnote.</text:p>"
            "</text:note-body></text:note>")
    picture = ('<draw:frame draw:name="SeedImage" text:anchor-type="as-char" '
               'svg:width="4cm" svg:height="3cm"><draw:image xlink:href="Pictures/seed.png" '
               'xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/></draw:frame>')
    changes = (
        '<text:tracked-changes><text:changed-region text:id="ct1"><text:insertion>'
        "<office:change-info><dc:creator>Seed Reviewer</dc:creator>"
        "<dc:date>2026-01-02T09:00:00</dc:date></office:change-info></text:insertion>"
        "</text:changed-region></text:tracked-changes>")
    annotation = ("<office:annotation><dc:creator>Seed Reviewer</dc:creator>"
                  "<dc:date>2026-01-02T09:05:00</dc:date>"
                  "<text:p>An OpenDocument comment.</text:p></office:annotation>")
    body = (
        changes
        + '<text:h text:style-name="Heading_20_1" text:outline-level="1">Seed OpenDocument text'
          "</text:h>"
        + '<text:p text:style-name="Standard">Plain text, <text:span text:style-name="T1">bold'
          '</text:span> and <text:span text:style-name="T2">italic</text:span>, with a footnote'
        + note + " and a comment" + annotation + ".</text:p>"
        + '<text:p text:style-name="Standard">A tracked insertion: <text:change-start '
          'text:change-id="ct1"/>inserted words<text:change-end text:change-id="ct1"/>.</text:p>'
        + '<text:list><text:list-item><text:p>First item</text:p></text:list-item>'
          "<text:list-item><text:p>Second item</text:p></text:list-item></text:list>"
        + table
        + f'<text:p text:style-name="Standard">A picture: {picture}</text:p>'
        + '<text:p text:style-name="Standard">A <text:a xlink:type="simple" '
          'xlink:href="https://example.org/">hyperlink</text:a>.</text:p>')
    content = (
        f"<office:document-content {ODF_NS}><office:automatic-styles>"
        '<style:style style:name="T1" style:family="text"><style:text-properties '
        'fo:font-weight="bold"/></style:style>'
        '<style:style style:name="T2" style:family="text"><style:text-properties '
        'fo:font-style="italic"/></style:style></office:automatic-styles>'
        f"<office:body><office:text>{body}</office:text></office:body>"
        "</office:document-content>")
    styles = (
        f"<office:document-styles {ODF_NS}><office:font-face-decls>"
        '<style:font-face style:name="Liberation Serif" svg:font-family="&apos;Liberation '
        'Serif&apos;"/></office:font-face-decls><office:styles>'
        '<style:default-style style:family="paragraph"><style:text-properties '
        'style:font-name="Liberation Serif" fo:font-size="12pt" fo:language="en" '
        'fo:country="US"/></style:default-style>'
        '<style:style style:name="Standard" style:family="paragraph"/>'
        '<style:style style:name="Heading_20_1" style:display-name="Heading 1" '
        'style:family="paragraph" style:parent-style-name="Standard" '
        'style:default-outline-level="1"><style:text-properties fo:font-size="18pt" '
        'fo:font-weight="bold"/></style:style>'
        '<style:style style:name="Header" style:family="paragraph" '
        'style:parent-style-name="Standard"/>'
        '<style:style style:name="Footer" style:family="paragraph" '
        'style:parent-style-name="Standard"/></office:styles>'
        '<office:automatic-styles><style:page-layout style:name="pm1">'
        '<style:page-layout-properties fo:page-width="21cm" fo:page-height="29.7cm" '
        'fo:margin-top="2cm" fo:margin-bottom="2cm" fo:margin-left="2cm" '
        'fo:margin-right="2cm"/><style:header-style/><style:footer-style/>'
        "</style:page-layout></office:automatic-styles><office:master-styles>"
        '<style:master-page style:name="Standard" style:page-layout-name="pm1">'
        '<style:header><text:p text:style-name="Header">Seed header</text:p></style:header>'
        '<style:footer><text:p text:style-name="Footer">Page <text:page-number '
        'text:select-page="current">1</text:page-number></text:p></style:footer>'
        "</style:master-page></office:master-styles></office:document-styles>")
    return odf_package("application/vnd.oasis.opendocument.text", "Seed OpenDocument text",
                       content, styles, [("Pictures/seed.png", "image/png", png_image())])


def odp_basic() -> bytes:
    def frame(cls: str, box: Tuple[str, str, str, str], paragraphs: str) -> str:
        x, y, w, h = box
        return (f'<draw:frame presentation:class="{cls}" presentation:style-name="pr1" '
                f'svg:x="{x}" svg:y="{y}" svg:width="{w}" svg:height="{h}">'
                f"<draw:text-box>{paragraphs}</draw:text-box></draw:frame>")

    def notes(text: str) -> str:
        return ('<presentation:notes draw:style-name="dpn"><draw:page-thumbnail '
                'presentation:class="page" svg:x="2cm" svg:y="1.5cm" svg:width="14cm" '
                'svg:height="7.875cm"/>'
                '<draw:frame presentation:class="notes" presentation:style-name="pr1" '
                'svg:x="2cm" svg:y="11cm" svg:width="17cm" svg:height="11cm">'
                f"<draw:text-box><text:p>{text}</text:p></draw:text-box></draw:frame>"
                "</presentation:notes>")

    title_box = ("1.4cm", "0.8cm", "25.2cm", "2.6cm")
    body_box = ("1.4cm", "3.9cm", "25.2cm", "10cm")
    page1 = ('<draw:page draw:name="Slide 1" draw:style-name="dp1" '
             'draw:master-page-name="Default">'
             + frame("title", title_box, "<text:p>Seed OpenDocument presentation</text:p>")
             + frame("subtitle", body_box, "<text:p>Self-authored fidelity sample</text:p>")
             + "</draw:page>")
    page2 = ('<draw:page draw:name="Slide 2" draw:style-name="dp2" '
             'draw:master-page-name="Default">'
             + frame("title", title_box, "<text:p>Outline and notes</text:p>")
             + frame("outline", body_box,
                     "<text:list><text:list-item><text:p>First point</text:p></text:list-item>"
                     "<text:list-item><text:p>Second point</text:p></text:list-item>"
                     "</text:list>")
             + notes("Speaker notes for slide two.") + "</draw:page>")
    page3 = ('<draw:page draw:name="Slide 3" draw:style-name="dp2" '
             'draw:master-page-name="Default">'
             + frame("title", title_box, "<text:p>Picture</text:p>")
             + '<draw:frame draw:name="SeedImage" svg:x="3cm" svg:y="4.5cm" svg:width="8cm" '
               'svg:height="6cm"><draw:image xlink:href="Pictures/seed.png" '
               'xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/></draw:frame>'
             + "</draw:page>")
    content = (
        f"<office:document-content {ODF_NS}><office:automatic-styles>"
        '<style:style style:name="dp1" style:family="drawing-page">'
        '<style:drawing-page-properties presentation:background-visible="true" '
        'presentation:background-objects-visible="true"/></style:style>'
        '<style:style style:name="dp2" style:family="drawing-page">'
        '<style:drawing-page-properties presentation:transition-speed="medium" '
        'smil:type="fade" smil:subtype="crossfade" presentation:background-visible="true" '
        'presentation:background-objects-visible="true"/></style:style>'
        '<style:style style:name="dpn" style:family="drawing-page"/>'
        '<style:style style:name="pr1" style:family="presentation"/>'
        "</office:automatic-styles><office:body><office:presentation>"
        + page1 + page2 + page3
        + "</office:presentation></office:body></office:document-content>")
    styles = (
        f"<office:document-styles {ODF_NS}><office:styles>"
        '<style:default-style style:family="graphic"><style:text-properties '
        'style:font-name="Liberation Sans" fo:font-size="18pt"/></style:default-style>'
        "</office:styles><office:automatic-styles>"
        '<style:page-layout style:name="PM1"><style:page-layout-properties '
        'fo:margin-top="0cm" fo:margin-bottom="0cm" fo:margin-left="0cm" '
        'fo:margin-right="0cm" fo:page-width="28cm" fo:page-height="15.75cm" '
        'style:print-orientation="landscape"/></style:page-layout>'
        '<style:style style:name="Mdp1" style:family="drawing-page"/>'
        "</office:automatic-styles><office:master-styles>"
        '<style:master-page style:name="Default" style:page-layout-name="PM1" '
        'draw:style-name="Mdp1"/></office:master-styles></office:document-styles>')
    return odf_package("application/vnd.oasis.opendocument.presentation",
                       "Seed OpenDocument presentation", content, styles,
                       [("Pictures/seed.png", "image/png", png_image())])


# --------------------------------------------------------------------------
# RTF and plain text
# --------------------------------------------------------------------------

def rtf_basic() -> bytes:
    row = "\\trowd\\trgaph108\\cellx3000\\cellx6000\\cellx9000\n"
    lines = [
        "{\\rtf1\\ansi\\ansicpg1252\\deff0\\deflang1033",
        "{\\fonttbl{\\f0\\froman\\fcharset0 Liberation Serif;}"
        "{\\f1\\fswiss\\fcharset0 Liberation Sans;}}",
        "{\\colortbl;\\red0\\green0\\blue0;\\red178\\green34\\blue34;}",
        "{\\stylesheet{\\s0\\f0\\fs24 Normal;}{\\s1\\f1\\b\\fs32 heading 1;}}",
        "{\\info{\\title Seed RTF document}{\\author Seed Author}}",
        "\\paperw11906\\paperh16838\\margl1440\\margr1440\\margt1440\\margb1440",
        "{\\header\\pard\\qc\\f0\\fs20 Seed RTF header\\par}",
        "{\\footer\\pard\\qc\\f0\\fs20 Page \\chpgn\\par}",
        "\\pard\\s1\\f1\\b\\fs32 Seed RTF document\\b0\\par",
        "\\pard\\s0\\f0\\fs24 Plain text with {\\b bold}, {\\i italic}, {\\ul underlined} "
        "and {\\cf2 coloured} runs.\\par",
        "Non-ASCII text: \\u8364? \\u945?\\u946?\\u947? \\u1055?\\u1088?\\u1080?\\u1074?"
        "\\u1077?\\u1090?.\\par",
        "A sentence with a footnote{\\super\\chftn}{\\footnote\\pard\\s0\\f0\\fs20"
        "{\\super\\chftn} The RTF footnote text.\\par}.\\par",
        row + "\\pard\\intbl A1\\cell B1\\cell C1\\cell\\row",
        row + "\\pard\\intbl A2\\cell B2\\cell C2\\cell\\row",
        "\\pard\\s0\\f0\\fs24 Text after the table with a link: "
        "{\\field{\\*\\fldinst HYPERLINK \"https://example.org/\"}"
        "{\\fldrslt{\\ul example link}}}.\\par",
        "\\page Text on the second page.\\par",
        "}",
    ]
    return ("\n".join(lines) + "\n").encode("ascii")


def txt_utf8() -> bytes:
    lines = [
        "Seed plain text (UTF-8 with byte order mark)",
        "",
        "ASCII line: The quick brown fox jumps over the lazy dog.",
        "Latin: café naïve façade Zürich",
        "Greek: αβγδε  Cyrillic: Привет  Tamil: வணக்கம்",
        "Symbols: € £ ¥ © ™ → ✓",
        "\tA line that starts with a tab.",
        "Last line without a trailing newline.",
    ]
    return b"\xef\xbb\xbf" + "\r\n".join(lines).encode("utf-8")


def txt_ascii() -> bytes:
    lines = ["Seed plain text (ASCII, LF line ends)", ""]
    lines += [f"Line {number:03d}: plain ASCII content for paging tests." for number in range(1, 121)]
    return ("\n".join(lines) + "\n").encode("ascii")


# --------------------------------------------------------------------------
# catalogue
# --------------------------------------------------------------------------

#: file name -> (builder, application, feature tags)
CATALOGUE = {
    "seed-basic.docx": (docx_basic, "writer",
                        "styles;lists;tables;merged-cells;hyperlinks;bookmarks;"
                        "sections;columns;page-orientation"),
    "seed-template.dotx": (lambda: docx_basic(template=True), "writer",
                           "template;styles;lists;tables"),
    "seed-notes-headers.docx": (docx_notes_headers, "writer",
                                "headers-footers;first-page-header;footnotes;endnotes;"
                                "toc;fields"),
    "seed-review.docx": (docx_review, "writer", "tracked-changes;comments"),
    "seed-images.docx": (docx_images, "writer", "images;anchored-images"),
    "seed-fonts.docx": (docx_fonts, "writer", "proprietary-fonts"),
    "seed-basic.rtf": (rtf_basic, "writer",
                       "styles;tables;footnotes;headers-footers;hyperlinks;fields"),
    "seed-basic.odt": (odt_basic, "writer",
                       "styles;lists;tables;footnotes;comments;tracked-changes;images;"
                       "headers-footers;hyperlinks"),
    "seed-utf8-bom.txt": (txt_utf8, "writer", "plain-text;unicode"),
    "seed-ascii.txt": (txt_ascii, "writer", "plain-text"),
    "seed-basic.pptx": (pptx_basic, "impress",
                        "masters-layouts;notes;transitions;animations;tables;images;"
                        "hidden-slides;shapes"),
    "seed-show.ppsx": (lambda: pptx_basic("ppsx"), "impress",
                       "slideshow-file;masters-layouts;notes;transitions;animations"),
    "seed-template.potx": (lambda: pptx_basic("potx"), "impress",
                           "template;masters-layouts;notes;transitions;animations"),
    "seed-basic.odp": (odp_basic, "impress", "masters-layouts;notes;transitions;images"),
}


def generate() -> Dict[str, bytes]:
    return {name: builder() for name, (builder, _app, _tags) in sorted(CATALOGUE.items())}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--check", action="store_true",
                        help="do not write; fail if a file differs from the generator output")
    args = parser.parse_args(argv)
    if args.out.exists() and not args.out.is_dir():
        print(f"error: not a directory: {args.out}", file=sys.stderr)
        return EXIT_USAGE
    produced = generate()
    differing = []
    for name, data in produced.items():
        target = args.out / name
        if args.check:
            if not target.is_file() or target.read_bytes() != data:
                differing.append(name)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    if differing:
        print("differs from generator output: " + ", ".join(differing), file=sys.stderr)
        return EXIT_DIFFERS
    print(f"{'checked' if args.check else 'wrote'} {len(produced)} files in {args.out}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
