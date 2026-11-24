# Compliance

| File | What it is |
|---|---|
| `licence-ledger.csv` | one row per third-party item that is linked, bundled, or used to build, test or package. Generated: do not edit by hand |
| `ledger-static.csv` | the hand-maintained rows (upstream core, dictionaries, tools, planned tool chain, corpus inputs). Edit this, then rebuild |
| `licence-policy.json` | which licences are pre-approved and which need the owner's decision (legal rule 6 of the brief) |
| `evidence/upstream-pin.json` | result of `tools.pin.verify_pin` |
| `evidence/external-usage.json` | how 26 of the 33 font archives are used in the build; each entry stores its quotes (file, line, text), and `build_ledger` re-checks them against the pinned tree on every run |
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

A scanned row is `allow` only when all of this holds: a licence **file**
(or the font's own embedded licence statement, read from every font file)
was recognised; every licence recognised is pre-approved; no
licence-named file in the archive was left unrecognised or unread; no
sampled source header or SPDX tag names a licence that is not
pre-approved; and the extracted evidence belongs to exactly the archive
`download.lst` names. Everything else is `needs-review`. The tools never
write `reject` and never promote a row: both are decisions for a person.
A text that carries an added restriction (non-commercial use, an
advertising or acknowledgement clause, and similar) is reported with the
extra identifier `LicenseRef-additional-restriction`, which no policy
pre-approves.

Limits that remain: recognition matches distinctive wording, not the
whole text, so an unusual variant can still be mislabelled; source
headers are sampled (60 files per archive), not read in full.

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

`check_ledger` exits 8 while any row is not `allow`, when the ledger is empty,
when an `allow` row names no licence or one the policy does not pre-approve,
or (with `--download-lst`) when a row's checksum differs — that is the CI gate.
