# Compliance

| File | What it is |
|---|---|
| `licence-ledger.csv` | one row per third-party item that is linked, bundled, or used to build, test or package. Generated: do not edit by hand |
| `ledger-static.csv` | the hand-maintained rows (upstream core, dictionaries, tools, planned tool chain, corpus inputs). Edit this, then rebuild |
| `licence-policy.json` | which licences are pre-approved and which need the owner's decision (legal rule 6 of the brief) |
| `evidence/upstream-pin.json` | result of `tools.pin.verify_pin` |
| `evidence/external-usage.json` | how font archives are used in the build, with quotes checked against the pinned tree |
| `evidence/externals-fetch-summary.json` | the 153 upstream archives fetched and checksum-verified |
| `evidence/web-sources.json` | upstream pages read, with revision ids and hashes |
| `evidence/logs/` | the run logs that back the Phase 0 gate report |

## How a ledger row is made

1. `tools.ledger.fetch_externals` downloads every archive named in the
   upstream `download.lst` and checks it against the SHA-256 pinned there.
2. `tools.ledger.extract_licences` copies licence-looking files out of
   each archive without unpacking anything else, and records their hashes.
3. `tools.ledger.build_ledger` recognises licence texts in those files by
   their wording (`tools/ledger/classify.py`), samples source headers,
   and applies `licence-policy.json`.

A row is `allow` only when a licence **file** (or a font's own embedded
licence statement) was read and every licence recognised is pre-approved,
and no sampled source header names another licence. Everything else is
`needs-review`. The tools never write `reject` and never promote a row:
both are decisions for a person.

The `spdx` column lists the licence texts **found**. Where several were
found, how they combine (a choice, or all at once, or a bundled
sub-component) is not decided by the tool.

This is not legal advice. Identification is mechanical and must be
confirmed by a qualified reviewer before any release.

## Rebuild

```bash
python3 -m tools.ledger.build_ledger --upstream-tree "$SUITE_UPSTREAM_TREE" --licences <dir> --tarballs <dir>
```

```bash
python3 -m tools.ledger.check_ledger
```

`check_ledger` exits 8 while any row is not `allow` — that is the CI gate.
