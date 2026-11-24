# Risk register (v0)

Scale: likelihood and impact are Low / Medium / High. "Detect" says how we
would notice; "Mitigation" what limits it; "Rollback" what we fall back to.

| # | Risk | L | I | Detect | Mitigation | Rollback |
|---|---|---|---|---|---|---|
| R1 | **No Windows build machine is reachable.** Phase 0 ran in a Linux container; Phase 1 needs Windows 10/11 x64 with Visual Studio 2022 | High | High | `list_computer_folders` returned no machine on 2026-11-24 | owner provides a Windows machine and runs the session there or attaches it by Remote Control | none: Phase 1 stays blocked |
| R2 | **Microsoft runtime inside our installer vs. legal rule 3.** A Visual C++ build needs the Microsoft C++ runtime; upstream's component list includes `VC.Redist.MSM` | High | High | forbidden-asset scan of the installer payload | owner decides: ship the redistributable under its licence, require it as a prerequisite, or other; record in the ledger | prerequisite-only installer |
| R3 | **Visual Studio edition licence.** Upstream's setup file installs the Community edition; its terms may not cover our organisation | Medium | High | ledger row `planned-visual-studio` is `needs-review` | owner names the licensed edition before bootstrap | none |
| R4 | **108 of 184 ledger rows are `needs-review`.** CI must fail while any row is not `allow` | High | Medium | `python3 -m tools.ledger.check_ledger` exits 8 | reduce the set by configuration (an MPL-only build removes several GPL/LGPL items), then the owner rules on the rest | drop the feature that needs the item |
| R5 | **Licence identification is mechanical.** A signature can miss or mislabel a text (Phase 0 found and fixed several: GPL-3.0 read as LGPL-3.0; notices wrapped in comment lines missed; a GPL notice hidden when the same text also named the LGPL; an archive's own unrecognised licence file ignored; texts with added restrictions read as plain MIT) | Medium | High | regression tests in `tools/tests/test_ledger_rules.py`; second reading by a person | `allow` requires a recognised licence file and no unrecognised or unread licence-named file; headers-only, sampled and mixed evidence stay `needs-review`; human review before release | treat row as `needs-review` |
| R6 | **GPL text in the English dictionary package** (`dictionaries/en/license.txt`) | High | Medium | ledger row `core-dictionaries` | review which files of `dictionaries/en` are needed for en-US and under which terms | ship without spell-check data and let users add dictionaries |
| R7 | **Upstream test documents have no stated licence**; many came from bug reports | Medium | Medium | ledger row `corpus-upstream-test-documents` | they are read in place and never redistributed; grow the self-authored corpus; owner supplies own documents | our own 18 files only (baseline on them alone: 15 pass, 3 partial) |
| R8 | **Trademark residue.** Upstream name or logo left somewhere the switches do not reach | High | High | forbidden-string and asset scan on the installer payload (planned gate) | inventory of hard-coded strings at the start of Phase 2; small patches | block release |
| R9 | **Fidelity defects in the base** (push transition direction; newer transitions dropped; chart parts lost on save in one deck and a chart's embedded workbook dropped in another; formulas lost in presentations; embedded fonts dropped; TOC lost in two files) | High | Medium | `reports/fidelity.json`; pass rate gate against the baseline | minimal upstreamable patches with regression tests in Phase 3; document what stays | list as known limitation |
| R10 | **Baseline is Linux, product is Windows.** Fonts and platform code differ | High | Medium | repeat baseline on Windows in Phase 1 and diff the two reports | same corpus, same criteria version | — |
| R11 | **Fonts without an open metric-compatible substitute.** 95 font names occur in the corpus; which of them lack a compatible open font is not determined yet (the engine shortens names before lookup; not traced) | High | Medium | font inventory per corpus file in the fidelity report | bundle open fonts where a compatible one exists and is ledger-approved; list the rest for users | document reflow as a known limitation |
| R12 | **MPL-only build changes behaviour**: `configure.ac` clears `ENABLE_OPENGL_TRANSITIONS` and drops several components | Medium | Medium | harness run on both configurations | choose per measured parity | default (MPL + LGPL parts) configuration |
| R13 | **Build size and time not measured.** The unversioned upstream LODE page says "count 25 GB to be safe with one debug build environment" and "This may take 1 to 2 hours, or more depending on your machine"; no RAM figure and no release-build figure was found | Medium | Medium | `reports/build-metrics.json` stage durations | incremental, resumable scripts; ccache off as upstream sets it | — |
| R14 | **Network use at run time.** Upstream's Windows release switches turn on online update and crash reporting | High | High | offline smoke test with a firewall log; gate fails on any outbound connection | product configuration disables them; inventory of every network feature in Phase 2 | block release |
| R15 | **Upstream security releases and end of life.** Releases 26.8.4 to 26.8.7 are planned; the 26.8 line ends on June 13, 2027 (upstream release plan) | High | Medium | watch the upstream release directory; `verify_pin` against a new tag | small patch series, rebase and full harness run per release; plan the move to the next upstream line before the end-of-life date | stay on the previous release with the fix back-ported |
| R16 | **Release signature not verified** for the baseline engine (checksum only) | Low | Low | `compliance/evidence/upstream-pin.json` | verify the OpenPGP signature once the key is fetched | — |
| R17 | **Harness blind spots**: no rendering comparison; binary formats have no package check; macros not executed | High | Medium | `docs/fidelity-method.md`, "What the method does not see" | visual diff against owner-supplied reference PDFs in Phase 3 | — |
| R18 | **Usage limits on automated sub-agents.** A parallel research run exhausted the account's 5-hour allowance in Phase 0 | Medium | Low | task failures naming the limit | deterministic scripts first; sub-agents only in small, sequential batches | finish by hand |

| R19 | **Upstream file names contain restricted words.** Rule 3 forbids "Word" and "Office" in executable and file names; the base ships `soffice`, `soffice.bin`, `sofficerc`, a library built as `msword` (`sw/Library_msword.mk:20`), `officehelper.py` and others | High | High | file-name scan of the installer payload (planned gate) | owner rules whether the rule covers internal file names that merely contain those letters; renaming launchers and libraries needs patches and touches many upstream scripts | keep upstream internal names, rename only what the user sees |

## Judgement calls flagged for a human (not decided here)

1. Whether a renamed build with hidden modules could still count as
   "substantially unmodified" under the upstream trademark policy. We
   assume **no** and remove the marks.
2. How rule 3 applies to Microsoft's redistributable C++ runtime (R2).
3. Whether mixed-licence items elected under an allowed alternative
   (for example an LGPL option beside a GPL option) may be marked `allow`.
4. Whether quoting the upstream policy and build files in our documents
   needs anything beyond attribution.
5. Whether rule 3's ban on "Word"/"Office" in file names reaches internal
   upstream names such as `soffice.exe` (R19).
6. Whether an MPL-only build is the better compliance position.
7. Whether the credit sentence must carry a trademark symbol (the upstream
   policy asks for one on the first or most prominent mention of a mark).
