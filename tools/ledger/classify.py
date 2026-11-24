# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Recognise licence texts by what is written in them.

The ledger rule is that a licence identifier is *read from the licence
file*, never recalled.  This module does that mechanically: a licence is
reported only when distinctive wording of that licence is present in the
file, and the line that matched is returned as evidence.

The signatures are short phrases quoted from the public licence texts
(the same texts SPDX publishes).  They identify *which text a file
contains*; they say nothing about how several texts in one archive
combine (AND / OR / sub-component), which stays a human decision.

Nothing here is legal advice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

_SPACE = re.compile(r"\s+")
_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "`": "'"})


_COMMENT_MARK = re.compile(r"^[ \t]*(?:/\*+|\*+/?|//+|#+|;+|--+|%+|dnl\b|rem\b)[ \t]?", re.M | re.I)


def normalise(text: str) -> str:
    """Lower-case, straighten quotes, drop comment decoration, collapse whitespace.

    Licence notices in source files are wrapped across comment lines
    (`` * ``, ``# ``, ``// `` ...); the decoration is removed so that a
    phrase can be matched across the line break.
    """
    text = _COMMENT_MARK.sub("", text.translate(_QUOTES))
    return _SPACE.sub(" ", text).strip().lower()


@dataclass(frozen=True)
class Signature:
    spdx: str
    required: Tuple[str, ...]          # every phrase must occur (normalised text)
    forbidden: Tuple[str, ...] = ()    # none of these may occur


#: Order matters only for readability; every matching signature is reported.
SIGNATURES: Tuple[Signature, ...] = (
    Signature("Apache-2.0", ("apache license", "version 2.0, january 2004")),
    Signature("MPL-2.0", ("mozilla public license version 2.0",)),
    Signature("MPL-1.1", ("mozilla public license version 1.1",)),
    # GNU licences are told apart by their exact title line: the GPL text itself
    # mentions the Lesser and Affero licences, so looser phrases confuse them.
    Signature("AGPL-3.0", ("gnu affero general public license version 3, 19 november 2007",)),
    Signature("GPL-3.0", ("gnu general public license version 3, 29 june 2007",)),
    Signature("GPL-2.0", ("gnu general public license version 2, june 1991",)),
    Signature("LGPL-3.0", ("gnu lesser general public license version 3, 29 june 2007",)),
    Signature("LGPL-2.1", ("gnu lesser general public license version 2.1, february 1999",)),
    Signature("LGPL-2.0", ("gnu library general public license version 2, june 1991",)),
    Signature("MIT", ("permission is hereby granted, free of charge, to any person obtaining",
                      "the software is provided \"as is\", without warranty of any kind"),
              ("except as contained in this notice",)),
    Signature("X11", ("permission is hereby granted, free of charge, to any person obtaining",
                      "except as contained in this notice")),
    Signature("BSD-4-Clause", ("redistribution and use in source and binary forms",
                               "all advertising materials mentioning features or use")),
    Signature("BSD-3-Clause", ("redistribution and use in source and binary forms",
                               "endorse or promote products"),
              ("all advertising materials mentioning features or use",)),
    Signature("BSD-2-Clause", ("redistribution and use in source and binary forms",
                               "redistributions in binary form must reproduce"),
              ("endorse or promote products", "all advertising materials")),
    Signature("ISC", ("permission to use, copy, modify, and/or distribute this software for "
                      "any purpose with or without fee is hereby granted",)),
    Signature("ISC", ("permission to use, copy, modify, and distribute this software for any "
                      "purpose with or without fee is hereby granted",
                      "disclaims all warranties")),
    Signature("curl", ("permission to use, copy, modify, and distribute this software for any "
                       "purpose with or without fee is hereby granted",
                       "except as contained in this notice, the name of a copyright holder")),
    Signature("Zlib", ("this software is provided 'as-is', without any express or implied",
                       "altered source versions must be plainly marked as such")),
    Signature("BSL-1.0", ("boost software license - version 1.0",)),
    Signature("OFL-1.1", ("sil open font license", "version 1.1")),
    Signature("OFL-1.0", ("sil open font license", "version 1.0"), ("version 1.1",)),
    Signature("CC0-1.0", ("cc0 1.0 universal",)),
    Signature("CC-BY-4.0", ("creative commons attribution 4.0 international",)),
    Signature("CC-BY-SA-3.0", ("creative commons", "attribution-sharealike 3.0")),
    Signature("CC-BY-SA-4.0", ("creative commons attribution-sharealike 4.0 international",)),
    Signature("Unlicense", ("this is free and unencumbered software released into the public "
                            "domain",)),
    Signature("Unicode-3.0", ("unicode license v3",)),
    Signature("Unicode-DFS-2016", ("unicode, inc. license agreement - data files and software",)),
    Signature("ICU", ("icu license - icu 1.8.1 and later",)),
    Signature("PSF-2.0", ("python software foundation license version 2",)),
    Signature("FTL", ("the freetype project license",)),
    Signature("libpng-2.0", ("png reference library license version 2",)),
    Signature("IJG", ("this software is based in part on the work of the independent jpeg group",)),
    Signature("libtiff", ("permission to use, copy, modify, distribute, and sell this software "
                          "and its documentation for any purpose is hereby granted without fee",
                          "silicon graphics")),
    Signature("OpenSSL", ("openssl license", "original ssleay license")),
    Signature("PostgreSQL", ("permission to use, copy, modify, and distribute this software and "
                             "its documentation for any purpose, without fee, and without a "
                             "written agreement is hereby granted",)),
    Signature("OLDAP-2.8", ("the openldap public license", "version 2.8")),
    Signature("Bitstream-Vera", ("bitstream vera fonts copyright",)),
    Signature("EPL-1.0", ("eclipse public license - v 1.0",)),
    Signature("EPL-2.0", ("eclipse public license - v 2.0",)),
    Signature("CPL-1.0", ("common public license version 1.0",)),
    Signature("CDDL-1.0", ("common development and distribution license (cddl) version 1.0",)),
    Signature("Interbase-1.0", ("interbase public license",)),
    Signature("LicenseRef-IDPL-1.0", ("initial developer's public license",)),
    Signature("W3C", ("w3c software notice and license",)),
    Signature("Artistic-2.0", ("the artistic license 2.0",)),
    Signature("NCSA", ("university of illinois/ncsa open source license",)),
    Signature("HPND", ("permission to use, copy, modify, and distribute this software and its "
                       "documentation for any purpose and without fee is hereby granted",)),
    Signature("MIT-0", ("permission is hereby granted, free of charge, to any person obtaining",
                        "the software is provided \"as is\", without warranty of any kind"),
              ("the above copyright notice and this permission notice shall be included",)),
    Signature("blessing", ("the author disclaims copyright to this source code",)),
    Signature("LicenseRef-public-domain", ("public domain",),
              ("unencumbered software released into the public domain", "cc0 1.0 universal",
               "gnu general public license", "gnu lesser general public license",
               "mozilla public license", "apache license")),
)

#: Licence *notices* as they appear in source-file headers and READMEs.  Weaker than
#: a full licence text, so they are only used where no licence file settles it.
NOTICES: Tuple[Signature, ...] = (
    Signature("MPL-2.0", ("subject to the terms of the mozilla public license, v. 2.0",)),
    Signature("Apache-2.0", ("licensed under the apache license, version 2.0",)),
    Signature("MPL-1.1", ("mozilla public license version 1.1",)),
    Signature("MPL-1.1", ("version: mpl 1.1",)),
    Signature("BSL-1.0", ("distributed under the boost software license, version 1.0",)),
    Signature("W3C", ("w3c ipr software notice",)),
    Signature("W3C", ("w3c software license",)),
)

# GNU notices are matched per sentence, not per file: one text often names several
# GNU licences ("the library is LGPL, the tools are GPL"), and a file-wide rule
# would let one of them hide the other.
_GPL_NOTICE = re.compile(
    r"(?<!lesser )(?<!library )(?<!affero )gnu general public license[^.]{0,200}?"
    r"version (\d)(?!\.\d)")
_LGPL_NOTICE = re.compile(
    r"gnu (?:lesser|library) general public license[^.]{0,200}?version (\d(?:\.\d)?)")
_AGPL_NOTICE = re.compile(r"gnu affero general public license[^.]{0,200}?version (\d)")
_TAG_NOTICE = re.compile(r"\blicen[cs]e: (a?l?gpl)-(\d(?:\.\d)?)")
_GNU_VERSIONS = {("gpl", "2"): "GPL-2.0", ("gpl", "3"): "GPL-3.0", ("lgpl", "2"): "LGPL-2.0",
                 ("lgpl", "2.0"): "LGPL-2.0", ("lgpl", "2.1"): "LGPL-2.1",
                 ("lgpl", "3"): "LGPL-3.0", ("agpl", "3"): "AGPL-3.0"}


def gnu_notices(flat: str) -> List[Tuple[str, str]]:
    """``(spdx, matched phrase)`` for every GNU licence notice in normalised text."""
    found: List[Tuple[str, str]] = []
    for family, pattern in (("gpl", _GPL_NOTICE), ("lgpl", _LGPL_NOTICE),
                            ("agpl", _AGPL_NOTICE)):
        for match in pattern.finditer(flat):
            spdx = _GNU_VERSIONS.get((family, match.group(1)))
            if spdx:
                found.append((spdx, match.group(0)))
    for match in _TAG_NOTICE.finditer(flat):
        spdx = _GNU_VERSIONS.get((match.group(1), match.group(2)))
        if spdx:
            found.append((spdx, match.group(0)))
    return found


#: Statements (normalised) that a GNU licence applies in "or any later version" form.
OR_LATER_PHRASES = ("or (at your option) any later version", "or any later version",
                    "either version 2 of the license, or", "either version 2.1 of the license, or",
                    "either version 3 of the license, or", "version 2 or later",
                    "version 2.1 or later", "version 3 or later", "or (at your option) version 3")
#: Wording that signals a choice between licences.
CHOICE_PHRASES = ("dual licensed", "dual-licensed", "tri-licensed", "triple licensed",
                  "at your option", "alternatively, the contents of this file may be used",
                  "you may choose", "either of the following licenses", "under either",
                  "is licensed under your choice", "any of the following licenses")
_SPDX_TAG = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.+()\- ]{2,120})")
GNU_IDS = ("GPL-2.0", "GPL-3.0", "LGPL-2.0", "LGPL-2.1", "LGPL-3.0", "AGPL-3.0")


@dataclass(frozen=True)
class Detection:
    spdx: str
    quote: str  # the original line that carries the first required phrase


def _evidence_line(text: str, phrase: str) -> str:
    """Return the original line containing ``phrase`` (or its beginning)."""
    words = phrase.split(" ")
    for length in range(len(words), 0, -1):
        probe = " ".join(words[:length])
        for line in text.splitlines():
            if probe in normalise(line):
                return _COMMENT_MARK.sub("", line).strip()[:200]
    return ""


def detect(text: str, notices: bool = False) -> List[Detection]:
    """All licence texts recognised in ``text`` (deduplicated by SPDX id).

    With ``notices`` the header/README notice wording is accepted as well.
    """
    flat = normalise(text)
    found: Dict[str, Detection] = {}
    for signature in SIGNATURES + (NOTICES if notices else ()):
        if signature.spdx in found:
            continue
        if not all(phrase in flat for phrase in signature.required):
            continue
        if any(phrase in flat for phrase in signature.forbidden):
            continue
        found[signature.spdx] = Detection(signature.spdx,
                                          _evidence_line(text, signature.required[0]))
    if notices:
        for spdx, phrase in gnu_notices(flat):
            if spdx not in found:
                found[spdx] = Detection(spdx, _evidence_line(text, phrase))
    # A file that contains a specific licence text is not also "public domain".
    if len(found) > 1:
        found.pop("LicenseRef-public-domain", None)
    # The MIT text is a superset of MIT-0's wording.
    if "MIT" in found:
        found.pop("MIT-0", None)
    # The Bitstream Vera licence is itself an MIT-style text with a name-use clause.
    if "Bitstream-Vera" in found:
        found.pop("X11", None)
    return list(found.values())


def states_or_later(text: str) -> bool:
    flat = normalise(text)
    return any(phrase in flat for phrase in OR_LATER_PHRASES)


def states_choice(text: str) -> Optional[str]:
    """The line that offers a choice of licences, if any."""
    flat = normalise(text)
    for phrase in CHOICE_PHRASES:
        if phrase in flat:
            return _evidence_line(text, phrase)
    return None


def spdx_tags(text: str) -> List[str]:
    """Values of ``SPDX-License-Identifier:`` tags found in ``text``."""
    values = []
    for match in _SPDX_TAG.finditer(text):
        value = match.group(1).strip().rstrip("*/ ").strip()
        if value and value not in values:
            values.append(value)
    return values


def gnu_suffix(spdx: str, or_later: bool) -> str:
    """``LGPL-2.1`` -> ``LGPL-2.1-or-later`` / ``LGPL-2.1-only``."""
    if spdx not in GNU_IDS:
        return spdx
    return f"{spdx}-or-later" if or_later else f"{spdx}-only"


def summarise(detections: Iterable[Sequence[Detection]]) -> List[str]:
    """Distinct SPDX ids over several files, in first-seen order."""
    seen: List[str] = []
    for group in detections:
        for item in group:
            if item.spdx not in seen:
                seen.append(item.spdx)
    return seen
