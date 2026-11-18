# Citrinitas

An open intelligence base for one person or a small group: open sources in one model, cut by place, time and
domain, on a single small machine. [Deutsch](README.de.md)

Citrinitas is the yellowing, the third stage of the alchemical opus between albedo and rubedo: the light in
which things become visible. It is built as a lighthouse, not a watchtower. It shows where things are; it does
not watch persons.

## What it does

- **One model for every source.** Every row carries place (ISO country, first administrative level, H3 cell),
  time (what it refers to, when it was reported, when it was fetched), one of fifteen domains, and its origin
  with licence.
- **Four classes that are never mixed.** `measured`, `official`, `reported`, `expected`. A count of news
  articles is not a count of events, and the model keeps them apart.
- **Questions steer collection.** Every source serves a question; every question has indicators with a
  threshold and a base rate fixed in advance.
- **Blind spots are measured.** A coverage matrix shows where no class, one source or only reporting exists; a
  probe ranks places with dense reporting and no hard fact.
- **Two time axes.** Corrections are new rows. `facta_asof(t)` answers what was known at time t.
- **Assessments are checked.** Seven fixed words of probability with their numbers, every figure backed by a
  returned row, at least two hypotheses, and the same figures on recomputation.
- **Read-only by construction.** One HTTP door with a token. Templates for displays, bounded read-only SQL for
  analysts. No alerts: indicators are state to be read.

The first sources are Fama (GDELT 2.0: events, mentions, knowledge graph in 65 languages) and the CISA Known
Exploited Vulnerabilities catalogue. The catalogue in `catalog/fontes.yaml` lists what is planned.

## What it does not do

It holds no profiles of persons. Person names in source data are dropped when a file is parsed, posts from
social networks are only ever counted, and the data model has no object for a private person. See
[ETHICS.md](ETHICS.md).

## Install on Proxmox VE

On the Proxmox host, as root:

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/pajew-ski/citrinitas/main/deploy/pve-create.sh)
```

This creates an unprivileged Debian 13 container (2 cores, 4 GB memory, 64 GB data volume), installs the
services under systemd and prints the address and the token. No container runtime is needed. Details and
settings: [docs/OPERATIONS.md](docs/OPERATIONS.md).

After that the node updates itself: every 15 minutes it fetches the branch, runs the self-test of the new
commit in its own directory, and switches only if the test passes and the API answers. A rejected commit is
named in the state document and the previous one keeps running.

## Ask

```sh
curl -s -H "Authorization: Bearer $TOKEN" http://$HOST:8765/status
curl -s -H "Authorization: Bearer $TOKEN" -d '{"template":"lang_gap","params":{"lang":"deu"}}' http://$HOST:8765/query
curl -s -H "Authorization: Bearer $TOKEN" -d '{"sql":"SELECT domain, classis, count(*) FROM facta GROUP BY ALL"}' http://$HOST:8765/query
```

The API is described in [docs/API.md](docs/API.md), the requirements in [SPEC.md](SPEC.md).

## Develop

```sh
pip install --require-hashes -r requirements.lock
python -m citrinitas selftest          # catalogue lint and the test suite
python scripts/spec_check.py           # every built requirement has a test marker
CITRINITAS_HOME=/tmp/citrinitas python -m citrinitas fetch && python -m citrinitas parse
```

A new source is one file in `citrinitas/fontes/` with `fetch` (network, writes raw files to the spool) and
`parse` (no network, writes Parquet), an entry in `catalog/fontes.yaml` and a projection onto the uniform view
`facta`.

## Licence

Code: [Apache-2.0](LICENSE). Data derived by Citrinitas itself: CC0-1.0. Source data keep the licence of their
source; the licence travels with every row and decides what may leave the system.
