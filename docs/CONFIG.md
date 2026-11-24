# Configuration

All configuration and all secrets come from environment variables or
command-line options. Nothing secret is stored in the repository.

## Variables used today (Phase 0 tools)

| Variable | Used by | Default | Meaning |
|---|---|---|---|
| `SUITE_LOG_DIR` | every tool | `<repo>/logs` | directory for JSON-lines run logs (git-ignored) |
| `SUITE_WORK_DIR` | `tools.fidelity.run_fidelity` | `<repo>/work` | scratch area: engine profiles, exported PDFs, round-trip files (git-ignored) |
| `SUITE_ENGINE_HOME` | `tools.fidelity.run_fidelity`, integration test | none (required) | directory that contains `program/soffice` and `program/python` of the engine under test |
| `SUITE_UPSTREAM_TREE` | `tools.fidelity.run_fidelity` | none (required when the manifest lists upstream test files) | checkout of the pinned upstream tag |

Files that hold configuration:

| File | Meaning |
|---|---|
| `config/upstream-pin.json` | pinned upstream tag, commit, repositories, release archive and its SHA-256 |
| `compliance/licence-policy.json` | which licences are pre-approved, which need the owner's decision |
| `corpus/MANIFEST.csv` | which documents the harness may read, with provenance and SHA-256 |

## Reserved for later phases (not implemented yet)

| Variable | Phase | Meaning |
|---|---|---|
| `SUITE_SIGN_PFX_PATH`, `SUITE_SIGN_PFX_PASSWORD`, `SUITE_SIGN_TIMESTAMP_URL` | 4 | code-signing material; read from the environment only. Unsigned developer builds must work when they are unset. The exact names the upstream build expects are UNKNOWN until `--enable-windows-build-signing` (`configure.ac:2161`) is read in Phase 1 |
| `SUITE_PRODUCT_NAME`, `SUITE_VENDOR` | 2 | values passed to `--with-product-name` and `--with-vendor` |

## Logs and metrics

- Logs: one JSON object per line with `ts`, `level`, `run_id`, `phase`,
  `step`, `duration_ms`, `result`, plus step-specific fields.
- Metrics: `reports/build-metrics.json`, one section per tool
  (`fidelity_baseline`, `ledger`; later `build`, `tests`, `installer`).

## Running the tools

```bash
python3 -m pytest tools/tests -q
```

```bash
python3 -m tools.pin.verify_pin --checkout "$SUITE_UPSTREAM_TREE"
```

```bash
python3 -m tools.fidelity.run_fidelity --label baseline
```

```bash
python3 -m tools.ledger.check_ledger --report-only
```
