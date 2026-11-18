#!/usr/bin/env bash
# Run on the Proxmox VE host as root. Creates an unprivileged LXC and installs Citrinitas in it.
# The node is its own container, apart from whatever displays its values (Spec F12).
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/pajew-ski/citrinitas/main/deploy/pve-create.sh)
#
# Settings come from the environment; every one has a default:
#   CT_HOSTNAME=citrinitas CT_CORES=2 CT_MEMORY=4096 CT_SWAP=512 CT_ROOT_GB=8 CT_DATA_GB=64
#   CT_BRIDGE=vmbr0 CT_STORAGE=<first storage that holds containers> CT_ID=<next free id>
#   CITRINITAS_BRANCH=main CITRINITAS_REPO=https://github.com/pajew-ski/citrinitas.git
set -euo pipefail

CT_HOSTNAME=${CT_HOSTNAME:-citrinitas}
CT_CORES=${CT_CORES:-2}
CT_MEMORY=${CT_MEMORY:-4096}
CT_SWAP=${CT_SWAP:-512}
CT_ROOT_GB=${CT_ROOT_GB:-8}
CT_DATA_GB=${CT_DATA_GB:-64}
CT_BRIDGE=${CT_BRIDGE:-vmbr0}
BRANCH=${CITRINITAS_BRANCH:-main}
REPO=${CITRINITAS_REPO:-https://github.com/pajew-ski/citrinitas.git}
RAW=${CITRINITAS_RAW:-https://raw.githubusercontent.com/pajew-ski/citrinitas}

command -v pct >/dev/null || { echo "pct not found: run this on a Proxmox VE host" >&2; exit 1; }
if pct list | awk 'NR>1 {print $NF}' | grep -qx "$CT_HOSTNAME"; then
  echo "a container named $CT_HOSTNAME already exists; nothing done" >&2; exit 1
fi

pveam update >/dev/null
TEMPLATE=$(pveam available --section system | awk '/debian-13-standard/ {print $2}' | sort -V | tail -1)
[ -n "$TEMPLATE" ] || { echo "no Debian 13 template available" >&2; exit 1; }
pveam list local | grep -q "$TEMPLATE" || pveam download local "$TEMPLATE"
CT_STORAGE=${CT_STORAGE:-$(pvesm status --content rootdir | awk 'NR==2 {print $1}')}
CT_ID=${CT_ID:-$(pvesh get /cluster/nextid)}

# The data volume is left out of Proxmox backups: everything on it can be fetched again from its source.
# nesting=1 lets systemd inside the container sandbox the services (private network, read-only system).
pct create "$CT_ID" "local:vztmpl/$TEMPLATE" --hostname "$CT_HOSTNAME" \
  --cores "$CT_CORES" --memory "$CT_MEMORY" --swap "$CT_SWAP" \
  --rootfs "$CT_STORAGE:$CT_ROOT_GB" --mp0 "$CT_STORAGE:$CT_DATA_GB,mp=/srv/citrinitas,backup=0" \
  --net0 "name=eth0,bridge=$CT_BRIDGE,ip=dhcp" --unprivileged 1 --features nesting=1 --onboot 1 --start 1

echo "container $CT_ID created, waiting for the network"
for _ in $(seq 1 30); do
  pct exec "$CT_ID" -- sh -c 'getent hosts github.com >/dev/null 2>&1' && break
  sleep 2
done
pct exec "$CT_ID" -- sh -c "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates >/dev/null"
pct exec "$CT_ID" -- env CITRINITAS_BRANCH="$BRANCH" CITRINITAS_REPO="$REPO" \
  bash -c "curl -fsSL '$RAW/$BRANCH/deploy/bootstrap.sh' | bash"
