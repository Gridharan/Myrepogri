# Phase 0 — GATE 0 report

Date: 2026-11-24. No product code was written. Phase 1 has not started.

## 1. Outcome in one paragraph

The default base holds: upstream LibreOffice core at tag
`libreoffice-26.8.3.1` is the newest stable release, the mirror matches
the official repository, and the official build runs our 114-document
seed corpus with 89 pass, 25 partial and 0 fail on structure. The licence
ledger has 177 rows, of which 88 need the owner's decision before
anything can ship. Two things block Phase 1 and both are the owner's: a
reachable Windows build machine, and rulings on the Microsoft runtime and
Visual Studio edition.

## 2. What was built

| Deliverable | Where |
|---|---|
| Base-choice decision record (proposed) | `docs/adr/0001-base-engine.md` |
| Licence ledger v0 (177 rows) with policy and evidence | `compliance/` |
| Branding and trademark plan, policy quoted | `docs/branding-plan.md` |
| Build-machine requirements quoted from the pinned tree | `docs/build-machine-requirements.md` |
| Seed corpus: 14 self-authored, 4 derived, 96 upstream test files by reference | `corpus/` |
| Baseline fidelity run and report | `reports/fidelity.json`, `reports/fidelity.html` |
| Parity matrix v0 | `docs/parity-matrix.md` |
| Risk register | `docs/risk-register.md` |
| Effort estimate | `docs/effort-estimate.md` |
| Tooling with unit tests (156 tests) | `tools/` |
| Configuration reference | `docs/CONFIG.md` |

## 3. Evidence

Log paths are under `compliance/evidence/logs/` (copies of the run logs;
the originals in `logs/` are not committed).

| Claim | Command | Result | Log / file |
|---|---|---|---|
| Tag → commit on the official repository and on the mirror; local checkout; release archive checksum; release build id | `python3 -m tools.pin.verify_pin --checkout <tree> --release-archive <file> --engine-home <dir>` | 5 of 5 checks passed, exit 0 | `verify-pin-20261124T212140Z-29646e5c.jsonl`, `compliance/evidence/upstream-pin.json` |
| 153 upstream archives fetched and matched to the SHA-256 in `download.lst` | `python3 -m tools.ledger.fetch_externals --download-lst <tree>/download.lst --dest <dir>` | 153 downloaded, 0 failed, exit 0 | `fetch-externals-20261124T144144Z-926ff4b7.jsonl`, `compliance/evidence/externals-fetch-summary.json` |
| Licence files copied out of all 153 archives | `python3 -m tools.ledger.extract_licences …` | 153 ok, exit 0 | `extract-licences-20261124T211530Z-321a48c5.jsonl` |
| Ledger built | `python3 -m tools.ledger.build_ledger …` | 177 rows: 89 allow, 88 needs-review, 0 reject | `build-ledger-20261124T213621Z-4c5fd59a.jsonl` |
| Ledger gate fails, as it must while rows are open | `python3 -m tools.ledger.check_ledger` | exit 8 | — |
| Baseline fidelity run | `python3 -m tools.fidelity.run_fidelity --engine-home <dir> --upstream-tree <tree> --label baseline` | 114 files: 89 pass, 25 partial, 0 fail; pass rate 0.7807; exit 0 | `fidelity-20261124T212654Z-a01b9301.jsonl`, `reports/fidelity.json` |
| Unit tests, including one engine integration test | `SUITE_ENGINE_HOME=<dir> python3 -m pytest tools/tests -q` | 156 passed | console output only (no log file kept) |

Not verified, stated as such:

- OpenPGP signature of the release archive (checksum only).
- Anything on Windows. The baseline used the official **Linux** build of
  the pinned release.
- How faithfully pages render (structure only).
- Collabora's Windows build and packaging path (pages read, not built).

## 4. Findings worth the owner's attention

1. **Upstream keeps an MPL-only build mode** (`--enable-mpl-subset`,
   `configure.ac:1750`) and a reduced Windows configuration
   (`distro-configs/CODAWindows.conf`). It is the cleanest route for
   commercial distribution, at the cost of some components; it also
   switches off OpenGL slide transitions, which must be measured first.
2. **Upstream's own Windows release switches enable online update and
   crash reporting.** Our product configuration must turn both off.
3. **Real defects in the unmodified base**, each a parity-matrix row:
   a push transition changes direction on save; newer transitions (morph,
   fly-through) are dropped; one deck's charts are gone after saving;
   embedded fonts are dropped in two files; a table of contents
   disappears in two files; .ppt files change slide-advance mode on save.
4. **Fonts**: four font families used by the corpus have no entry in the
   upstream replacement table (Segoe UI, Aptos, Calibri Light, Cambria
   Math); Liberation Sans Narrow ships with a GPL text.
5. **English dictionaries** include a GPL-2.0 text; spell-check data needs
   a licence ruling.
6. **The build machine setup is versioned upstream** (`.config/*.winget`,
   `.config/2022.vsconfig`) with download URLs and checksums — Phase 1
   can script it exactly.

## 5. Ledger changes

New in this phase (there was no ledger before): 177 rows.

| Group | Rows | allow | needs-review |
|---|---|---|---|
| Upstream externals from `download.lst` | 153 | 83 | 70 |
| Upstream core, dictionaries, help, translations, icon theme | 5 | 1 | 4 |
| Tools used in Phase 0 (interpreter, test framework, baseline engine, git) | 8 | 5 | 3 |
| Corpus inputs | 1 | 0 | 1 |
| Planned tool chain for Phase 1 (not installed) | 10 | 0 | 10 |

Why rows are open: GPL or AGPL text present (ask first); a licence not on
the pre-approved list (for example BSL-1.0, PSF-2.0, Unicode-3.0, IJG,
FTL, curl, X11-style, public-domain statements); several texts whose
combination a tool cannot decide; licence known only from source headers;
nothing recognised (5 archives); or a proprietary tool whose terms the
owner must confirm.

## 6. What went wrong in this phase

- A parallel research run with sub-agents exhausted the account's
  5-hour usage allowance and returned almost nothing: a single sub-agent
  result came back (how the font archives are used in the build), and it
  was kept only after its quotes were checked against the tree. The rest
  of the work was redone with deterministic scripts. Cost to the owner:
  several hours of blocked usage.
- Four defects in my own tooling were caught and fixed before the
  numbers above were produced: a file-name rule that skipped
  `COPYING.LIB`; GPL-3.0 texts recognised as LGPL-3.0; licence notices
  wrapped across comment lines not recognised; a GPL notice hidden when
  the same text also named the LGPL. Each has a regression test.
- The fidelity criteria were revised twice after trial runs (history in
  `docs/fidelity-method.md`).
- An early status message said the release build had been downloaded
  when only a redirect page had been saved; it was corrected in the next
  message and the download was then verified by checksum.

## 7. Open risks

See `docs/risk-register.md`. The five that decide the schedule: R1 (no
Windows machine), R2 (Microsoft runtime vs. rule 3), R3 (Visual Studio
edition), R4 (88 open ledger rows), R8 (trademark residue).

## 8. What is needed from the owner

Blocking Phase 1:

1. A Windows 10/11 x64 build machine the session can use, with
   administrator rights for setup.
2. Which Visual Studio 2022 edition and licence to use.

Needed before Phase 2 ends:

3. `PRODUCT_NAME` (cleared for use) and `DISTRIBUTION`
   (private, free public, or commercial). Phase 0 assumed commercial.
4. Ruling on shipping Microsoft's C++ runtime inside the installer.
5. Preference on the MPL-only build, subject to the transition measurement.
6. Ruling on using upstream test documents as test input, and on the
   English dictionary package.
7. Decisions on the open ledger rows (a short review session; the list is
   `compliance/licence-ledger.csv` filtered on `needs-review`).

Optional, improves Phase 3:

8. Your own representative documents, and reference PDFs made on a
   licensed installation.

Reply **approved** to accept GATE 0 (base choice and pin), or say what to
change.
