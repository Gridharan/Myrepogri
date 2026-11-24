# Corpus

Every file the harness may read has a row in `MANIFEST.csv`. The 18 files
we wrote ourselves are cleared. The 96 upstream test documents are the
category the brief permits ("upstream test files under their licence"),
but no per-file licence is stated upstream, so their use as test input
awaits the owner's decision; results are also reported for our own files
alone.

| Source | Count | Where the bytes live | Licence |
|---|---|---|---|
| `self-authored` | 14 | `corpus/self/` (committed) | MPL-2.0 — written by `tools/corpus/gen_seed.py` from public format specifications |
| `derived` | 4 | `corpus/derived/` (committed) | MPL-2.0 — our own files converted to .doc/.ppt by the baseline engine; see `derived/DERIVED.json` |
| `upstream-test-file` | 96 | **not in this repository**; read from the pinned upstream checkout | no licence stated per file — ledger row `corpus-upstream-test-documents`, needs the owner's decision |

`upstream-selection.json` records which upstream files were chosen and by
which algorithm (`tools/corpus/select_upstream.py`). The harness refuses a
file whose SHA-256 differs from its manifest row.

## Rules

- Files **we add** must not come from an unknown source, and must not be
  made with or taken from Microsoft templates, clip art or sample
  documents. (The upstream test documents were written by many people
  with many applications, Microsoft Word and PowerPoint among them; they
  stay in the upstream tree and are never copied or redistributed by us.)
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
