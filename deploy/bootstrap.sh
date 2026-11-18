#!/usr/bin/env bash
# Run once as root inside the container (pve-create.sh does it). Safe to run again.
set -euo pipefail

HOME_DIR=/srv/citrinitas
BRANCH=${CITRINITAS_BRANCH:-main}
REPO=${CITRINITAS_REPO:-https://github.com/pajew-ski/citrinitas.git}
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq git python3 python3-venv ca-certificates curl util-linux >/dev/null

id citrinitas >/dev/null 2>&1 || useradd --system --home-dir "$HOME_DIR" --shell /usr/sbin/nologin citrinitas
usermod -aG systemd-journal citrinitas   # the state document shows the last journal lines of each unit

mkdir -p "$HOME_DIR"/{data,spool,state,releases,venvs} "$HOME_DIR"/etc/{keys,quaestiones.d}
chown citrinitas:citrinitas "$HOME_DIR"/{data,spool,state}
chown -R root:citrinitas "$HOME_DIR/etc"
chmod 750 "$HOME_DIR/etc" "$HOME_DIR/etc/keys"

if [ ! -s "$HOME_DIR/etc/token" ]; then
  python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "$HOME_DIR/etc/token"
fi
chown root:citrinitas "$HOME_DIR/etc/token"; chmod 640 "$HOME_DIR/etc/token"
echo "$BRANCH" > "$HOME_DIR/etc/branch"

if [ ! -d "$HOME_DIR/repo/.git" ]; then
  git clone -q --depth 1 --branch "$BRANCH" "$REPO" "$HOME_DIR/repo"
fi
install -m 755 "$HOME_DIR/repo/deploy/pull.sh" /usr/local/bin/citrinitas-pull
/usr/local/bin/citrinitas-pull || true

ADDR=$(hostname -I | awk '{print $1}')
echo
if curl -fsS -m 5 "http://127.0.0.1:8765/health" >/dev/null 2>&1; then
  echo "Citrinitas is running: $(curl -fsS -m 5 http://127.0.0.1:8765/health)"
else
  echo "Citrinitas is NOT running. Reason:"
  cat "$HOME_DIR/state/rejected.json" 2>/dev/null || journalctl -u citrinitas-athanor -n 20 --no-pager
fi
echo
echo "Address and token for clients (keep the token private):"
echo "  url:   http://$ADDR:8765"
echo "  token: $(cat "$HOME_DIR/etc/token")"
