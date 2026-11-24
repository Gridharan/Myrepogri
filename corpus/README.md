# Corpus

Only files we have the right to use, each with a row in `MANIFEST.csv`.

| Source | Count | Where the bytes live | Licence |
|---|---|---|---|
| `self-authored` | 14 | `corpus/self/` (committed) | MPL-2.0 — written by `tools/corpus/gen_seed.py` from public format specifications |
| `derived` | 4 | `corpus/derived/` (committed) | MPL-2.0 — our own files converted to .doc/.ppt by the baseline engine; see `derived/DERIVED.json` |
| `upstream-test-file` | 96 | **not in this repository**; read from the pinned upstream checkout | no licence stated per file — ledger row `corpus-upstream-test-documents`, needs the owner's decision |

`upstream-selection.json` records which upstream files were chosen and by
which algorithm (`tools/corpus/select_upstream.py`). The harness refuses a
file whose SHA-256 differs from its manifest row.

## Rules

- No file from an unknown source. No file made with or taken from
  Microsoft templates, clip art or sample documents.
- Reference renderings may be added only if the owner supplies them from
  a licensed installation; they go in `corpus/reference/` with a manifest
  row each.
- To add your own documents: put them in `corpus/owner/`, add manifest
  rows with `source` = `self-authored`, and re-run the harness.

## Regenerate

```bash
python3 -m tools.corpus.gen_seed --out corpus/self --check
```

```bash
python3 -m tools.corpus.build_manifest --upstream-tree "$SUITE_UPSTREAM_TREE" --upstream-tag libreoffice-26.8.3.1 --upstream-commit 861effc5289d539f15c4c18d1ba8579ffd78728b
```
