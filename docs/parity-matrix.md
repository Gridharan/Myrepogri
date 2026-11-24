# Parity matrix v0

Status values: **works** · **partial** · **missing** · **won't do** ·
**not measured** (v0 only: no evidence yet, so no claim is made).

Evidence base for every "measured" row: baseline run
`20261124T212654Z-a01b9301` in `reports/fidelity.json` — unmodified
official LibreOffice 26.8.3 (build id `861effc5…`), **Linux x86-64 build**,
114 documents, criteria version 3 (`docs/fidelity-method.md`).
Counts are *pass / partial / fail* among corpus documents carrying the
feature tag. A "pass" means structure survived open → PDF → save → reopen;
it says nothing yet about how the page looks.

Overall: **89 pass, 25 partial, 0 fail (78.1 %)**. Writer formats
55 / 9 / 0 (docx 24/7, docm 1/2, doc 11/0, dotx 3/0, rtf 7/0, odt 7/0,
txt 2/0). Presentation formats 34 / 16 / 0 (pptx 18/9, ppt 4/5, ppsx 2/1,
potx 2/1, pptm 1/0, odp 7/0).

## Formats

| Feature | Status | Evidence |
|---|---|---|
| Open/save .docx | partial | 24/7/0; all open, export and reopen; 7 change structure on save (rows below) |
| Open/save .doc | works (structure) | 11/0/0, incl. 3 files converted from our own .docx |
| Open/save .dotx | works (structure) | 3/0/0 |
| Open/save .rtf | works (structure) | 7/0/0 |
| Open/save .odt | works (structure) | 7/0/0 |
| Open/save .txt | works | 2/0/0 (UTF-8 with BOM, ASCII) |
| Open/save .pptx | partial | 18/9/0 |
| Open/save .ppt | partial | 4/5/0 — every partial is the slide-advance mode changing from 0 to 2 on save (`transitions` metric); 5 upstream files, e.g. `sd/qa/unit/data/ppt/tdf48083.ppt` |
| Open/save .ppsx | partial | 2/1/0 (the partial is our own file, push-transition defect below) |
| Open/save .potx | partial | 2/1/0 (same defect) |
| Open/save .odp | works (structure) | 7/0/0 |
| PDF export | works | 114 of 114 produced a PDF whose page count matched the document (hidden slides excluded) |
| Printing | not measured | needs a Windows printer path; Phase 4 VM test |

## Word-processor features

| Feature | Status | Evidence |
|---|---|---|
| Paragraph and character styles | works (structure) | `styles` 5/0/0 |
| Lists | partial | `lists` 19/4/0; no partial is caused by a list metric |
| Tables | partial | `tables` 21/4/0; table count grows on save in `tdf102466.docx` (19→20) and `tdf157131.docx` (3→4) |
| Images | partial | `images` 24/8/0; image count grows on save in 3 files (two .docm 1→2, `tdf102466.docx` 2→4) |
| Headers and footers | partial | `headers-footers` 13/6/0; header text lost in `sw/qa/extras/uiwriter/data/tdf157131.docx` |
| Footnotes, endnotes | works (structure) | `footnotes` 11/0/0, `endnotes` 6/0/0 |
| Table of contents | partial | `toc` 10/4/0; the index object is gone after save in `tdf154478.docx` and `tdf154481.docx` |
| Tracked changes | partial | `tracked-changes` 7/3/0; `tdf123705.docx` 19→18 changes |
| Comments | works (structure) | `comments` 11/2/0; neither partial is caused by comments |
| Text boxes | partial | `textboxes` 11/4/0, cause not isolated |
| Content controls | partial | `content-controls` 7/7/0, cause not isolated |
| Math formulas | works (structure) | `math` 4/1/0, the partial has another cause |
| Embedded objects | partial | `ole` 10/4/0; one presentation loses its OLE object (`oox/qa/unit/data/import-characters.pptx`, 1→0) |
| Spell check | not measured | dictionary licence review open (ledger `core-dictionaries`) |

## Presentation features

| Feature | Status | Evidence |
|---|---|---|
| Slide masters and layouts | partial | `multi-master` 7/3/0; master count +1 on save in `slide-sections.pptx` (3→4) and `slide-section-test.pptx` (18→19) |
| Speaker notes | works (structure) | `notes` 15/5/0; no partial is caused by notes |
| Transitions (classic) | **partial — defect found** | `<p:push dir="l"/>` is written back as `<p:push dir="r"/>`: sub-type 97 (FROMLEFT) becomes 99 (FROMRIGHT) in `self-seed-basic-pptx`, `-show-ppsx`, `-template-potx`. Candidate upstream patch for Phase 3 |
| Transitions (newer) | **missing on save** | 2 files: `morph` and `flythrough` are replaced by the fallback or dropped (`transition-lost:morph`, `transition-lost:flythrough`) |
| Animations | works (structure) | `animations` 15/4/0; effect counts unchanged in all, partials have other causes |
| Charts | partial | `charts` 3/2/0; `sd/qa/unit/data/pptx/tdf169781.pptx` loses both chart parts (2→0) on save; `chart-pt-color-bg1.pptx` loses the embedded workbook |
| Tables, pictures, groups, connectors | works (structure) | `connectors` 7/0/0, `groups` 11/3/0 with other causes |
| Media | works (structure) | `media` 3/0/0 |
| Slideshow, presenter view | not measured | interactive; Phase 4 VM test |

## Weak spots named in the brief

| Feature | Status | Evidence |
|---|---|---|
| VBA macros — storage | works on the samples | 5 files with macro storage; Basic module count unchanged after save in all 5, no VBA project part lost |
| VBA macros — running them | not measured | the harness never executes macros; product default will be "macros disabled" |
| SmartArt — kept on save | partial | 6 files; diagram parts unchanged in 4, reduced in 2 (5→4, 24→8) |
| SmartArt — editing as SmartArt | not measured | needs a UI test |
| Newer PowerPoint transitions | missing on save | see above |
| Rights-managed (IRM) files | not measured | no sample in the corpus; none found in the upstream tree so far |
| Password-protected files | not measured | excluded from v0 selection (encrypted OOXML is not a zip package) |
| Embedded fonts | partial | 4 files; embedded-font parts dropped on save in 2 (`subsetted-embedded-font.docx`, `multiplelayoutfooter.pptx`) |
| Fonts we cannot ship | partial | 95 distinct font names in the corpus. Most used: Arial 61 files, Calibri 61, Times New Roman 42, Calibri Light 26, Symbol 20, Wingdings 20, Tahoma 19, Cambria 18, Courier New 18. The upstream replacement table (`officecfg/registry/data/org/openoffice/VCL.xcu`) maps calibri→carlito, cambria→caladea, arial→liberationsans, timesnewroman→…liberationserif, couriernew→…liberationmono, arialnarrow→…liberationsansnarrow, symbol/wingdings→…opensymbol. **No entry found** for segoeui, aptos, calibrilight, cambriamath; tahoma, verdana and consolas map to generic fallbacks, not metric-compatible fonts. Liberation Sans Narrow carries a GPL text (ledger `ext-font-liberation-narrow`, needs review) |

## Product requirements not yet measurable

| Feature | Status | Evidence |
|---|---|---|
| Tabbed toolbar as default | not measured | key exists: `ToolbarMode.xcu` `Applications/Writer/Active`, mode `Tabbed` (line 101); set in Phase 2 |
| OOXML as default save format | not measured | shipped default is `writer8` / `impress8` (`Setup.xcu` lines 275, 145); changed in Phase 2 |
| Strict macro security | not measured | `MacroSecurityLevel` 0–3 in `Common.xcs` line 2149; set in Phase 2 |
| No network calls | not measured | offline smoke test, Phase 4 |
| Only two launchers visible | not measured | Phase 2 |
| Installer: silent install, upgrade, uninstall | not measured | Phase 4 |
| Cloud, co-authoring, add-in store | won't do (v1) | out of scope in the brief |

## Limits of v0

- Structural pass only; no visual comparison.
- Upstream test documents are regression samples chosen by an algorithm
  (`tools/corpus/select_upstream.py`), not a sample of real-world files.
- Results come from the Linux build of the pinned release; repeat on
  Windows in Phase 1.
