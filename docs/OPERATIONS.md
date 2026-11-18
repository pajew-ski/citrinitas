# Operations

## The container

`deploy/pve-create.sh` runs on the Proxmox VE host. It creates an unprivileged Debian 13 container with
`nesting=1`, so that systemd inside can sandbox the services, and a separate data volume mounted at
`/srv/citrinitas` that is excluded from Proxmox backups. Settings are environment variables:

```sh
CT_HOSTNAME=citrinitas CT_CORES=2 CT_MEMORY=4096 CT_DATA_GB=64 CT_BRIDGE=vmbr0 \
  bash <(curl -fsSL https://raw.githubusercontent.com/pajew-ski/citrinitas/main/deploy/pve-create.sh)
```

`CITRINITAS_BRANCH` installs another branch than `main`. Grow the data volume later with
`pct resize <id> mp0 +64G`; change cores and memory with `pct set`.

Give the container a fixed address in your router, so that clients keep reaching it.

## Layout on the node

| Path | Content | Owner |
|---|---|---|
| `/srv/citrinitas/repo` | checkout of the branch | root |
| `/srv/citrinitas/releases/<commit>` | one directory per commit; `current` links to the live one | root |
| `/srv/citrinitas/venvs/<lock hash>` | one virtual environment per lock file | root |
| `/srv/citrinitas/data` | the lake: Parquet per source, table and day; provenance; results | citrinitas |
| `/srv/citrinitas/spool` | raw files between fetch and parse | citrinitas |
| `/srv/citrinitas/state` | state files, the rejected commit, the sandbox level | citrinitas |
| `/srv/citrinitas/etc` | `token`, `branch`, `keys/`, `quaestiones.d/` for private questions | root, readable by citrinitas |

## Units

| Unit | When | What |
|---|---|---|
| `citrinitas-athanor.service` | always | the read-only API on port 8765 |
| `citrinitas-fetch.timer` | minute 2, 17, 32, 47 | fetch raw files (network), then start parse |
| `citrinitas-parse.service` | after fetch | parse into the lake, without network |
| `citrinitas-daily.timer` | 03:40 UTC | compaction, pruning, drift, budget, indicators; monthly coverage and probe |
| `citrinitas-pull.timer` | every 15 minutes | fetch the branch, self-test, switch |

## Updates

Merging to the branch is the release. `install.sh` unpacks the commit, installs dependencies with pinned
hashes, runs `python -m citrinitas selftest` as the service user, moves the `current` link, restarts the API
and checks that it answers with the new commit. If any step fails, the previous commit keeps running and
`state/rejected.json` names the commit, the reason and the log tail; the state document shows it. A rejected
commit is not tried again; push a fix.

To take a change back, revert it on the branch.

## Sandbox

The units ask systemd for a read-only system, private temporary files and devices, and no network for parsing.
What an unprivileged container allows differs between hosts. `install.sh` probes once per install and writes
the level to `state/sandbox.json`:

- `full`: everything as declared
- `no-private-network`: parsing runs with network access
- `degraded`: the namespace settings are off; user separation and resource limits remain

## Looking inside without a shell

`GET /status` returns everything needed to judge an installation: running commit, rejected commit, sandbox
level, disk, memory, the state of every source and the last 50 journal lines of every unit.

With a shell: `pct enter <id>`, then `journalctl -u citrinitas-fetch -n 50`, or
`runuser -u citrinitas -- /srv/citrinitas/current/.venv/bin/python -m citrinitas status` in
`/srv/citrinitas/current`.

## Sizes

Measured on 2026-11-18 for GDELT, both streams: about 14 MB download per quarter hour, about 1.8 GB per day.
In the lake one quarter hour takes about 0.6 MB, of which the knowledge graph extract is the largest part.
Budgets per source are in `catalog/fontes.yaml`; the daily run compares them with what was used.

## Private questions

Questions that should not be public go to `/srv/citrinitas/etc/quaestiones.d/*.yaml` in the format of
`catalog/quaestiones.yaml`. They are evaluated with the shipped ones.
