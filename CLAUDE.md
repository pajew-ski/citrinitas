# Working in this repository

Citrinitas is an open intelligence base: open sources in one model, cut by place, time and domain. Read
`SPEC.md` before changing behaviour; it is the contract.

## Rules

- **Spec first.** A change to behaviour changes `SPEC.md` (requirement, acceptance, status), the code and a
  test in the same pull request. Tests carry `# Spec <ID>` at the check. `python scripts/spec_check.py` must pass.
- **No person-level data.** No names of persons, no accounts, no objects for private persons, in code,
  catalogue, fixtures or documentation. Drop such columns at parse time. See `ETHICS.md`.
- **This repository is public.** Nothing private goes into files, commits, issues or pull requests: no
  addresses, host names, tokens, or notes about anyone's network or life. Use neutral example values.
- **Classes are never mixed.** `measured`, `official`, `reported`, `expected` stay apart in every query and view.
- **A source has two phases.** `fetch` talks to the network and only writes raw files to the spool with a
  logged SHA-256. `parse` has no network. A file of the wrong shape is an error, never a column of nulls.
- **Every source is declared.** An entry in `catalog/fontes.yaml` with licence, reliability and reason, cells,
  budget and at least one question from `catalog/quaestiones.yaml`.
- **Verify before you build.** Check access, format and licence of a source against the source itself on the
  day you build the adapter, and write the date into the catalogue.
- **English in files, Latin for the parts.** Athanor (core), Fontes (sources), Fama (GDELT), Quaestiones
  (questions), Tabula (coverage), Specillum (probe).
- **Dependencies** are pinned with hashes in `requirements.lock` (`pip-compile --generate-hashes`). Add one
  only if the standard library and DuckDB cannot do the job.

## Commands

```sh
python -m citrinitas selftest       # lint of the catalogue and all tests; the node runs this before going live
python scripts/spec_check.py
CITRINITAS_HOME=/tmp/citrinitas python -m citrinitas fetch
CITRINITAS_HOME=/tmp/citrinitas python -m citrinitas parse
CITRINITAS_HOME=/tmp/citrinitas python -m citrinitas daily
CITRINITAS_HOME=/tmp/citrinitas python -m citrinitas query --template indicators
```

Merging to `main` is the release: nodes pull it within 15 minutes and switch if the self-test passes.
