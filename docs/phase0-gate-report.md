# Phase 0 — GATE 0 report

Date: 2026-11-24. No product code was written. Phase 1 has not started.

## 1. Outcome in one paragraph

The default base holds: upstream LibreOffice core at tag
`libreoffice-26.8.3.1` is the newest stable release, the mirror matches
the official repository, and the official build runs our 114-document
seed corpus with 84 pass, 30 partial and 0 fail on structure. The 26.8
line ends on June 13, 2027. The licence ledger has 184 rows, of which 108
need the owner's decision before anything can ship. Phase 1 is blocked on
two things only the owner can provide: a reachable Windows build machine,
and rulings on the Microsoft runtime, the Visual Studio edition and
upstream's internal file names.

## 2. What was built

| Deliverable | Where |
|---|---|
| Base-choice decision record (proposed) | `docs/adr/0001-base-engine.md` |
| Licence ledger v0 (184 rows) with policy and evidence | `compliance/` |
| Branding and trademark plan, policy quoted | `docs/branding-plan.md` |
| Build-machine requirements quoted from the pinned tree | `docs/build-machine-requirements.md` |
| Seed corpus: 14 self-authored, 4 derived, 96 upstream test files by reference | `corpus/` |
| Baseline fidelity run and report | `reports/fidelity.json`, `reports/fidelity.html` |
| Parity matrix v0 | `docs/parity-matrix.md` |
| Risk register | `docs/risk-register.md` |
| Effort estimate | `docs/effort-estimate.md` |
| Tooling with unit tests | `tools/` |
| Configuration reference | `docs/CONFIG.md` |

## 3. Evidence

Every log named here is in `compliance/evidence/logs/`.

| Claim | Command | Result | Log / file |
|---|---|---|---|
| Tag → commit on the official repository and on the mirror; pinned release is the newest in the official stable listing; source archive of that release is named after the tag; local checkout; release archive checksum; release build id | `python3 -m tools.pin.verify_pin --checkout <tree> --release-archive <file> --engine-home <dir>` | 7 of 7 checks passed, exit 0 | `verify-pin-20261124T222503Z-11f5475b.jsonl`, `compliance/evidence/upstream-pin.json` |
| 153 upstream archives fetched and matched to the SHA-256 in `download.lst` | `python3 -m tools.ledger.fetch_externals --download-lst <tree>/download.lst --dest <dir>` | 153 downloaded, 0 failed, exit 0 | `fetch-externals-20261124T144144Z-926ff4b7.jsonl`, `compliance/evidence/externals-fetch-summary.json` |
| Licence-named files copied out of all 153 archives | `python3 -m tools.ledger.extract_licences --download-lst <tree>/download.lst --tarballs <dir> --dest <dir>` | 153 ok, exit 0 | `extract-licences-20261124T222216Z-de69bbb6.jsonl` |
| Ledger built | `python3 -m tools.ledger.build_ledger --upstream-tree <tree> --licences <dir> --tarballs <dir>` | 184 rows: 76 allow, 108 needs-review, 0 reject | newest `build-ledger-*.jsonl` |
| Ledger gate fails, as it must while rows are open | `python3 -m tools.ledger.check_ledger --download-lst <tree>/download.lst` | exit 8, no malformed rows | newest `check-ledger-*.txt` |
| Baseline fidelity run | `python3 -m tools.fidelity.run_fidelity --engine-home <dir> --upstream-tree <tree> --label baseline` | 114 files: 84 pass, 30 partial, 0 fail; pass rate 0.7368; exit 0 | `fidelity-20261124T222749Z-7627aa7a.jsonl`, `reports/fidelity.json` |
| Unit tests, including one engine integration test | `SUITE_ENGINE_HOME=<dir> python3 -m pytest tools/tests -q` | all passed, exit 0 (count in the log) | newest `pytest-*.txt` |

Not verified, stated as such:

- OpenPGP signature of the release archive (checksum only).
- Anything on Windows. The baseline used the official **Linux** build of
  the pinned release.
- How faithfully pages render (structure only).
- Collabora's Windows build and packaging path (pages read, not built).
- Which corpus fonts lack a metric-compatible open substitute.

## 4. Findings worth the owner's attention

1. **The 26.8 line ends on June 13, 2027** (upstream release plan). A
   product pinned to it needs a planned move to the next line.
2. **Upstream has an MPL-only build mode** (`--enable-mpl-subset`,
   `configure.ac:1750`). It drops several components and switches off
   OpenGL slide transitions, which must be measured before it is chosen.
   Upstream's reduced Windows configuration
   (`distro-configs/CODAWindows.conf`) is a useful template but is not
   MPL-only by itself.
3. **Upstream's own Windows release switches enable online update and
   crash reporting.** Our product configuration must turn both off.
4. **Real defects in the unmodified base**, each a parity-matrix row:
   a push transition changes direction on save; newer transitions (morph,
   fly-through) are dropped; formulas are lost in presentations; one
   deck's charts are gone after saving; embedded fonts are dropped in two
   files; a table of contents disappears in two files; .ppt files change
   slide-advance mode on save.
5. **Upstream file names contain "office" and "word"** (`soffice.exe`,
   the `msword` filter library and others). Rule 3 read strictly forbids
   that; renaming them means patching the upstream build system.
6. **English dictionaries** include a GPL-2.0 text; spell-check data needs
   a licence ruling. Liberation Sans Narrow also ships with a GPL text.
7. **The build machine setup is versioned upstream** (`.config/*.winget`,
   `.config/2022.vsconfig`) with download URLs and checksums — Phase 1
   can script it exactly. It installs Visual Studio **Community**; the
   edition we may use is the owner's call.

## 5. Ledger changes

New in this phase (there was no ledger before): 184 rows.

| Group | Rows | allow | needs-review |
|---|---|---|---|
| Upstream externals from `download.lst` | 153 | 70 | 83 |
| Upstream core, dictionaries, help, translations, icon theme | 5 | 1 | 4 |
| Tools used in Phase 0 (interpreter, test framework, baseline engine, git) | 8 | 5 | 3 |
| Corpus inputs | 1 | 0 | 1 |
| Planned tool chain for Phase 1 (not installed) | 17 | 0 | 17 |

Why rows are open: GPL or AGPL text present (ask first); a licence not on
the pre-approved list (for example BSL-1.0, PSF-2.0, Unicode-3.0, IJG,
FTL, curl, X11-style, public-domain statements); several texts whose
combination a tool cannot decide; a licence-named file the tool could not
recognise; licence known only from source headers; nothing recognised
(3 archives); or a tool whose licence has not been read yet.

## 6. What went wrong in this phase

- **Usage limit.** A parallel research run with sub-agents exhausted the
  account's 5-hour usage allowance and returned almost nothing: a single
  result came back (how the font archives are used in the build), kept
  only because its quotes check out against the tree on every ledger
  build. The rest was redone with deterministic scripts. Cost to the
  owner: several hours of blocked usage.
- **A wrong status message.** An early message said the release build had
  been downloaded when only a redirect page had been saved. It was
  corrected in the next message and the download was then verified by
  checksum.
- **Defects in my own tooling**, found by tests or by the independent
  review and fixed, each with a regression test: a file-name rule that
  skipped `COPYING.LIB`; GPL-3.0 texts recognised as LGPL-3.0; licence
  notices wrapped across comment lines not recognised; a GPL notice
  hidden when the same text also named the LGPL; rows marked `allow`
  although the archive's own licence file was unrecognised or unread;
  permissive texts with an added restriction read as the plain licence;
  stale extraction evidence accepted; a gate check that passed an empty
  ledger; a verdict rule that passed a document which had lost its text;
  PDF page counts unreadable above about 45 pages; an engine process
  that could outlive a timeout.
- **Wrong statements in the first draft of these documents**, corrected
  after the review: the end-of-life date was reported as unknown although
  it is on the page cited; `CODAWindows.conf` was called MPL-only; four
  fonts were said to lack a substitute on the basis of an incomplete
  check; math formulas were reported as working.
- **Criteria changed after seeing results.** The fidelity criteria went
  through four versions (history in `docs/fidelity-method.md`). The
  baseline pass rate moved 69 % → 80 % → 78 % → 74 % as false alarms
  were removed and missed losses added. The figure to hold future builds
  to is the last one, with criteria version 4.

## 7. Open risks

See `docs/risk-register.md`. The ones that decide the schedule: R1 (no
Windows machine), R2 (Microsoft runtime vs. rule 3), R3 (Visual Studio
edition), R4 (108 open ledger rows), R8 (trademark residue), R15 (end of
life in June 2027), R19 (upstream file names).

## 8. What is needed from the owner

Blocking Phase 1:

1. A Windows 10/11 x64 build machine the session can use, with
   administrator rights for setup.
2. Which Visual Studio 2022 edition and licence to use.

Needed before Phase 2 ends:

3. `PRODUCT_NAME` (cleared for use) and `DISTRIBUTION`
   (private, free public, or commercial). Phase 0 assumed commercial.
4. Ruling on shipping Microsoft's C++ runtime inside the installer.
5. Ruling on internal file names that contain "office" or "word".
6. Preference on the MPL-only build, subject to the transition measurement.
7. Ruling on using upstream test documents as test input, and on the
   English dictionary package.
8. Decisions on the open ledger rows (the list is
   `compliance/licence-ledger.csv` filtered on `needs-review`).

Optional, improves Phase 3:

9. Your own representative documents, and reference PDFs made on a
   licensed installation.

Reply **approved** to accept GATE 0 (base choice and pin), or say what to
change.
