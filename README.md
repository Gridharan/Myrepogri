# Offline word processor and presentation app (working title: PRODUCTNAME)

An installable, offline word processor ("PRODUCTNAME Write") and
presentation app ("PRODUCTNAME Present") for Windows 10/11 x64, later
Ubuntu, built on an existing open-source office engine. It opens, edits
and saves .docx, .doc, .dotx, .rtf, .odt, .txt and .pptx, .ppt, .ppsx,
.potx, .odp files.

**Status: Phase 0 (feasibility and legal baseline) — waiting at GATE 0.**
There is no product code yet. Start with `docs/phase0-gate-report.md`.

| Path | Contents |
|---|---|
| `docs/` | gate report, base-engine decision record, branding plan, build requirements, parity matrix, risks, estimate, configuration |
| `compliance/` | licence ledger, policy, evidence |
| `corpus/` | fidelity corpus manifest and our own sample documents |
| `config/` | the pinned upstream version |
| `tools/` | scripts and their unit tests |
| `reports/` | fidelity report and run metrics |
| `build/`, `patches/`, `branding/` | empty until Phases 1–2 |
| `logs/` | run logs (not committed) |

Our own files are under the Mozilla Public License 2.0 (`LICENSE`).
Third-party items are listed in `compliance/licence-ledger.csv`.
