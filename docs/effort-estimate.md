# Effort estimate (v0)

Ranges, not promises. They assume one engineer-equivalent working with
the scripts in this repository, a Windows build machine that is ready,
and quick owner answers at each gate. Machine time (builds, test runs) is
listed separately because it does not need attention. Every figure is an
estimate made before the first Windows build; the build-time figures in
particular are UNKNOWN until Phase 1 measures them.

| Phase | Work | Effort (working days) | Machine time | Main uncertainty |
|---|---|---|---|---|
| 0 | Feasibility and legal baseline | done | — | — |
| 1 | Reproducible upstream build on Windows; `bootstrap.ps1`, `build.ps1`; upstream tests; `BUILDINFO.json`; Windows baseline | 4–8 | first full build and test run: UNKNOWN, plan for 1–2 days of wall-clock | machine setup, reboot mid-setup, antivirus, upstream test failures on Windows |
| 2 | Product layer: branding, defaults, hidden modules, fonts, network off; patch series | 8–15 | several rebuilds | number of hard-coded upstream strings; MPL-only decision; font licences |
| 3 | Fidelity harness on Windows, visual diff, fixes for the defects found | 8–20 | harness minutes per run; rebuild per fix | how many defects are fixable with small patches |
| 4 | Installer, signing hook, silent install, upgrade/downgrade, clean-VM tests, release checklist | 6–12 | VM runs | runtime redistribution decision; code-signing material |
| 5 | Ubuntu investigation report | 2–4 | — | — |
| 6 | Ubuntu build and packaging per the chosen option | 5–12 | builds | packaging route chosen at Gate 5 |
| Ongoing | Each upstream security release: rebase, rebuild, harness, release | 1–3 per release | one build | patch conflicts |

Not included: legal review time, trademark clearance of the product name,
icon and artwork design, and purchase or provisioning of the build
machine and signing certificate.

## What would move the numbers most

1. A ready Windows machine with Visual Studio licensed and installed
   (removes most of Phase 1's uncertainty).
2. The owner's rulings on the 108 open ledger rows — choosing the MPL-only
   build early shrinks that list.
3. Owner-supplied reference renderings and real documents for Phase 3.
