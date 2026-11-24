# Fidelity method

How `tools/fidelity` measures a document, and what the three verdicts mean.
The numbers in `reports/fidelity.json` are only comparable between runs
that use the same corpus (`corpus/MANIFEST.csv`) and the same criteria
version (recorded in the report under `settings.criteria_version`).

## What is done per document

1. A private, headless engine process is started (own profile, no display,
   proxy variables removed). Macros are never executed
   (`MacroExecutionMode` = never) and links are never updated.
2. The document is opened; the import filter the engine chose is recorded.
3. The document model is measured through the public UNO API: page or
   slide count, tables, images, footnotes, comments, tracked changes,
   indexes, masters, notes, transitions, animation effects, fonts, Basic
   modules, and more.
4. It is exported to PDF.
5. It is saved again **with the filter it was loaded with** (what a user
   gets with "Keep current format").
6. The saved copy is reopened and measured again.
7. Outside the engine, for zip-based formats, the original and the saved
   package are compared: kinds of parts, counts of structural elements,
   user content inside container parts, fonts, slide transition effects.
   The PDF's page count is read from its page tree.

Each document has a hard time limit (default 240 s); the engine's whole
process group is killed afterwards.

## Verdicts (criteria version 4)

| Verdict | Meaning |
|---|---|
| `fail` | did not open, PDF export failed, save failed, saved copy did not reopen, engine crashed, or time limit hit |
| `partial` | everything ran, but: page/slide count changed; or a *critical* model metric changed; or a critical kind of package part vanished (VBA project, SmartArt diagram, chart, embedded object, media, embedded font, slide, slide master); or user content counted in the package was lost (comments, footnotes, endnotes, formulas, tracked changes, header/footer/notes text); or an amount of content shrank by more than 5 % between the first and second reading (words, characters, paragraphs, shapes, text frames, hyperlinks, sections, slide text, notes text, animation nodes); or a transition effect named in the file is gone after saving; or the PDF page count does not match or could not be read |
| `pass` | none of the above |

Other differences (growth, shape-type breakdown, fonts, style counts …)
are recorded and never change the verdict.

Pass rate = pass ÷ total. `--baseline <older fidelity.json>` makes the
runner exit with code 6 when the pass rate is lower than in that file.

## What the method does not see

- **Rendering.** No pixel or layout comparison yet; a document can keep
  its structure and still look different. Visual diff against reference
  PDFs is Phase 3 and needs renderings supplied by the owner.
- **Loss at first import that leaves no trace in the package counts.**
  The package comparison catches comments, notes, formulas, tracked
  changes, transitions and the critical part kinds; other content
  dropped on import is invisible. The 5 % tolerance also hides small
  losses of text.
- **Binary formats** (.doc, .ppt, .rtf) have no package comparison; only
  the model before/after is compared.
- **Behaviour**: macros are not run, slideshows are not played, printing
  is not exercised.
- **Windows.** The baseline ran the official Linux build. The engine code
  is the same commit, but fonts and some platform code differ; the
  baseline must be repeated on Windows in Phase 1.

## History of the criteria

| Version | Change | Why |
|---|---|---|
| 1 | first rules; any "container" part that vanished counted as a loss | — |
| 2 | container parts (comments, notes, headers …) judged by the content inside them; ODF object-replacement images no longer counted as embedded objects | a trial run counted 29 losses of footnote/endnote parts that held no notes (the producer writes them empty), and one comment part that held no comment; 12 documents changed from `partial` to `pass` |
| 3 | a transition effect present before and absent after is a loss | a trial run showed a "morph" transition replaced by "fade" while the verdict stayed `pass` |
| 4 | content that shrinks by more than 5 % is a loss; formulas and tracked changes are counted in the package; ODF comments and notes are counted; an unreadable PDF page count is `partial`; PDF page trees of any length are read | an independent review showed that a document losing all its text would still `pass`, that a lost formula went unseen, and that the PDF page count could not be read above about 45 pages |

Versions 1 to 3 were only used for trial runs on 2026-11-24. The baseline
kept in `reports/` uses version 4. The criteria were changed **after**
seeing results; each change removed a false alarm or exposed a real loss,
and none was made to raise the pass rate (versions 3 and 4 lowered it).
Pass rates under the four versions on the same 114 documents: 69.3 %,
79.8 %, 78.1 %, 73.7 %.
