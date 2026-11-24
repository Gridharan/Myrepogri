# Parity matrix v0

Status values: **works** · **partial** · **missing** · **won't do** ·
**not measured** (v0 only: no evidence yet, so no claim is made).

Evidence base for every "measured" row: baseline run
`20261124T222749Z-7627aa7a` in `reports/fidelity.json` — unmodified
official LibreOffice 26.8.3 (build id `861effc5…`), **Linux x86-64 build**,
114 documents, criteria version 4 (`docs/fidelity-method.md`).
Counts are *pass / partial / fail* among corpus documents carrying the
feature tag. "works (structure)" means structure survived open → PDF →
save → reopen in every sample; it says nothing yet about how the page
looks. A feature tag marks documents that *contain* the feature; a
partial there can have another cause, which the row then says.

Overall: **84 pass, 30 partial, 0 fail (73.7 %)**. Writer formats
54 / 10 / 0 (docx 23/8, docm 1/2, doc 11/0, dotx 3/0, rtf 7/0, odt 7/0,
txt 2/0). Presentation formats 30 / 20 / 0 (pptx 14/13, ppt 4/5, ppsx 2/1,
potx 2/1, pptm 1/0, odp 7/0).

On our own 18 files alone (14 self-authored, 4 derived): 15 pass,
3 partial, 0 fail — the three partials are the push-transition defect.

## Formats

| Feature | Status | Evidence |
|---|---|---|
| Open/save .docx | partial | 23/8/0; all open, export and reopen; 8 change structure on save (rows below) |
| Open/save .doc | works (structure) | 11/0/0, incl. 3 files converted from our own .docx |
| Open/save .dotx | works (structure) | 3/0/0 |
| Open/save .rtf | works (structure) | 7/0/0 |
| Open/save .odt | works (structure) | 7/0/0 |
| Open/save .txt | works | 2/0/0 (UTF-8 with BOM, ASCII) |
| Open/save .pptx | partial | 14/13/0 |
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
| Lists | partial | `lists` 18/5/0; no partial is caused by a list metric |
| Tables | partial | `tables` 21/4/0; table count grows on save in `tdf102466.docx` (19→20) and `tdf157131.docx` (3→4) |
| Images | partial | `images` 22/10/0; image count grows on save in 3 files (two .docm 1→2, `tdf102466.docx` 2→4) |
| Headers and footers | partial | `headers-footers` 12/7/0; header text lost in `sw/qa/extras/uiwriter/data/tdf157131.docx` |
| Footnotes, endnotes | works (structure) | `footnotes` 10/1/0, `endnotes` 6/0/0; the one partial has another cause |
| Table of contents | partial | `toc` 9/5/0; the index object, its 3 sections and 4 of 9 hyperlinks are gone after save in `tdf154478.docx` and `tdf154481.docx` |
| Hyperlinks | partial | `hyperlinks` 16/9/0; link count drops on save in 4 documents (e.g. `tdf124637_sectionMargin.docx` 8→5) |
| Tracked changes | partial | `tracked-changes` 7/3/0; `tdf123705.docx` 19→18 changes |
| Comments | works (structure) | `comments` 10/3/0; no partial is caused by comments |
| Text boxes and shapes | partial | `textboxes` 11/4/0; drawing shapes 9→7 in `tdf157131.docx`; other causes not isolated |
| Content controls | partial | `content-controls` 6/8/0, cause not isolated |
| Math formulas | partial | `math` 3/2/0: kept in the three Writer samples; in presentations the formula is lost on save in both samples (`import-mce.pptx`: formula count 1→0; `import-characters.pptx`: the embedded formula object becomes a plain shape) |
| Embedded objects | partial | `ole` 10/4/0; none of the four partials is caused by an object count, causes not isolated |
| Spell check | not measured | dictionary licence review open (ledger `core-dictionaries`) |

## Presentation features

| Feature | Status | Evidence |
|---|---|---|
| Slide masters and layouts | partial | `multi-master` 7/3/0; master count +1 on save in `slide-sections.pptx` (3→4) and `slide-section-test.pptx` (18→19) |
| Speaker notes | works (structure) | `notes` 14/6/0; no partial is caused by notes |
| Transitions (classic) | **partial — defect found** | `<p:push dir="l"/>` is written back as `<p:push dir="r"/>`: sub-type 97 (FROMLEFT) becomes 99 (FROMRIGHT) in `self-seed-basic-pptx`, `-show-ppsx`, `-template-potx`. Candidate upstream patch for Phase 3 |
| Transitions (newer) | **missing on save** | `newer-transitions` 0/2/0: `morph` is replaced by its fallback (`tdf149588_transparentSolidFill.pptx`), `flythrough` and its fallback are dropped (`tdf156808.pptx`) |
| Animations | partial | `animations` 12/7/0; effect counts unchanged in all, but animation nodes drop on save in 3 decks (`bnc591147.pptx` 19→17, `narration-non-media-shape.pptx` 7→6, `tdf91060.pptx` 2→1) |
| Charts | partial | `charts` 3/2/0; `sd/qa/unit/data/pptx/tdf169781.pptx` loses both chart parts (2→0) on save; `chart_pt_color_bg1.pptx` loses the chart's embedded workbook |
| Tables, pictures, groups, connectors | works (structure) | `connectors` 7/0/0, `groups` 11/3/0 with other causes |
| Media | partial | `media` 1/2/0; media parts are kept, both partials are the animation-node drop above |
| Slideshow, presenter view | not measured | interactive; Phase 4 VM test |

## Weak spots named in the brief

| Feature | Status | Evidence |
|---|---|---|
| VBA macros — storage | works on the samples | `vba` 3/2/0; Basic module count unchanged after save in all 5 files and no VBA project part lost; the two partials are an extra image appearing in .docm files |
| VBA macros — running them | not measured | the harness never executes macros; product default will be "macros disabled" |
| SmartArt — kept on save | partial | `smartart` 5/1/0; diagram parts unchanged in 4 files, reduced in 2 (5→4, 24→8) |
| SmartArt — editing as SmartArt | not measured | needs a UI test |
| Newer PowerPoint transitions | missing on save | see above |
| Rights-managed (IRM) files | not measured | no sample in the corpus; none found in the upstream tree so far |
| Password-protected files | not measured | excluded from v0 selection (encrypted OOXML is not a zip package) |
| Embedded fonts | partial | `embedded-fonts` 2/2/0; embedded-font parts dropped on save in `subsetted-embedded-font.docx` and `multiplelayoutfooter.pptx` |
| Fonts we cannot ship | not measured yet | 95 distinct font names occur in the corpus (most used: Arial and Calibri 61 files each, Times New Roman 42, Calibri Light 26, Symbol 20, Wingdings 20, Tahoma 19, Cambria 18, Courier New 18). Read so far in the upstream replacement table (`officecfg/registry/data/org/openoffice/VCL.xcu`): calibri→carlito, cambria→caladea, arial→liberationsans…, timesnewroman→…liberationserif…, couriernew→…liberationmono…, arialnarrow→…liberationsansnarrow…. **Which corpus fonts end up without a metric-compatible open substitute is not determined**: the engine also shortens names before looking them up (so "Calibri Light" can resolve through the calibri entry), and that logic was not traced. The list is a Phase 2 deliverable. Liberation Sans Narrow carries a GPL text (ledger `ext-font-liberation-narrow`, needs review) |

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
