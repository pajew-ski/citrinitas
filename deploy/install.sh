#!/usr/bin/env bash
# Runs as root inside the container after every pull. Idempotent.
#
# A new commit goes live only after its self-test passed on this machine (Spec C16):
#   1. the commit is unpacked into its own directory under releases/
#   2. the self-test runs there as the service user
#   3. only then the `current` link moves and the services restart
#   4. if the API does not answer with the new commit, the link moves back
# A rejected commit is written to state/rejected.json, shown in the state document, and not tried again.
set -euo pipefail

HOME_DIR=${CITRINITAS_HOME:-/srv/citrinitas}
REPO=$HOME_DIR/repo
STATE=$HOME_DIR/state
UNITS=/etc/systemd/system
COMMIT=$(git -C "$REPO" rev-parse HEAD)
PREVIOUS=$(readlink -f "$HOME_DIR/current" 2>/dev/null || true)

reject() {
  python3 - "$COMMIT" "$1" "$STATE" <<'PY'
import json, sys, datetime, pathlib
commit, reason, state = sys.argv[1:4]
log = pathlib.Path(state, "selftest.log")
tail = log.read_text(errors="replace").splitlines()[-40:] if log.exists() else []
pathlib.Path(state, "rejected.json").write_text(json.dumps(
    {"commit": commit, "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
     "reason": reason, "log": tail}))
PY
  chown citrinitas:citrinitas "$STATE/rejected.json" 2>/dev/null || true
  echo "commit $COMMIT rejected: $1" >&2
  exit 0
}

if [ -n "$PREVIOUS" ] && [ "$(basename "$PREVIOUS")" = "$COMMIT" ]; then exit 0; fi
if [ -f "$STATE/rejected.json" ] && grep -q "\"$COMMIT\"" "$STATE/rejected.json"; then exit 0; fi

# 1. unpack
REL=$HOME_DIR/releases/$COMMIT
if [ -d "$REL" ]; then mv "$REL" "$REL.old.$$"; fi
mkdir -p "$REL"
git -C "$REPO" archive "$COMMIT" | tar -x -C "$REL"
echo "$COMMIT" > "$REL/COMMIT"

# one virtual environment per lock file; dependencies are installed with pinned hashes only
LOCK=$(sha256sum "$REL/requirements.lock" | cut -c1-16)
VENV=$HOME_DIR/venvs/$LOCK
if [ ! -f "$VENV/.ok" ]; then
  python3 -m venv --clear "$VENV"
  "$VENV/bin/python" -m pip install -q --disable-pip-version-check --require-hashes -r "$REL/requirements.lock" \
    || reject "dependencies could not be installed"
  touch "$VENV/.ok"
fi
ln -sfn "$VENV" "$REL/.venv"

# 2. self-test as the service user, in the release directory, against a throwaway home
TEST_HOME=$(mktemp -d)
chown citrinitas:citrinitas "$TEST_HOME"
if ! (cd "$REL" && runuser -u citrinitas -- env CITRINITAS_HOME="$TEST_HOME" PYTHONDONTWRITEBYTECODE=1 \
      "$VENV/bin/python" -m citrinitas selftest) > "$STATE/selftest.log" 2>&1; then
  reject "self-test failed"
fi

# units and the pull script follow the release; the API unit needs its one writable directory to exist
install -d -o citrinitas -g citrinitas "$HOME_DIR/data" "$HOME_DIR/data/_meta" "$HOME_DIR/spool" "$HOME_DIR/state"
install -m 644 "$REL"/deploy/units/* "$UNITS/"
install -m 755 "$REL/deploy/pull.sh" /usr/local/bin/citrinitas-pull

# Sandboxing depends on what the container allows. Probe once per install and step down in the open:
# the level is written to state/sandbox.json and shown in the state document.
SERVICES="citrinitas-athanor citrinitas-fetch citrinitas-parse citrinitas-daily"
FULL="-p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes -p PrivateDevices=yes -p ProtectKernelTunables=yes -p ProtectKernelModules=yes -p ProtectControlGroups=yes -p ReadWritePaths=$STATE -p User=citrinitas"
dropin() {  # dropin <service> <content>; empty content removes the drop-in
  local dir="/etc/systemd/system/${1:?}.service.d"
  mkdir -p "$dir"
  if [ -n "${2:-}" ]; then printf '[Service]\n%b' "$2" > "$dir/10-sandbox.conf"; else : > "$dir/10-sandbox.conf"; fi
}
for s in $SERVICES; do dropin "$s" ""; done
# shellcheck disable=SC2086
if systemd-run --quiet --wait --collect $FULL -p PrivateNetwork=yes /bin/true 2>/dev/null; then
  LEVEL=full
elif systemd-run --quiet --wait --collect $FULL /bin/true 2>/dev/null; then
  LEVEL=no-private-network
  for s in citrinitas-parse citrinitas-daily; do dropin "$s" 'PrivateNetwork=no\n'; done
else
  LEVEL=degraded
  for s in $SERVICES; do
    dropin "$s" 'PrivateNetwork=no\nProtectSystem=no\nProtectHome=no\nPrivateTmp=no\nPrivateDevices=no\nProtectKernelTunables=no\nProtectKernelModules=no\nProtectControlGroups=no\nReadWritePaths=\n'
  done
fi
printf '{"level":"%s"}' "$LEVEL" > "$STATE/sandbox.json"
chown citrinitas:citrinitas "$STATE/sandbox.json"
systemctl daemon-reload

# 3. switch
ln -sfn "$REL" "$HOME_DIR/current.new"
mv -T "$HOME_DIR/current.new" "$HOME_DIR/current"
systemctl enable -q citrinitas-athanor.service citrinitas-fetch.timer citrinitas-daily.timer citrinitas-pull.timer
systemctl restart citrinitas-athanor.service

# 4. the API must answer with the new commit
OK=0
for _ in $(seq 1 20); do
  if curl -fsS -m 3 http://127.0.0.1:8765/health 2>/dev/null | grep -q "$COMMIT"; then OK=1; break; fi
  sleep 1
done
if [ "$OK" != 1 ]; then
  journalctl -u citrinitas-athanor -n 40 --no-pager > "$STATE/selftest.log" 2>&1 || true
  if [ -n "$PREVIOUS" ] && [ -d "$PREVIOUS" ]; then
    ln -sfn "$PREVIOUS" "$HOME_DIR/current.new"
    mv -T "$HOME_DIR/current.new" "$HOME_DIR/current"
    systemctl restart citrinitas-athanor.service || true
  fi
  reject "the API did not come up with the new commit"
fi
systemctl start citrinitas-fetch.timer citrinitas-daily.timer citrinitas-pull.timer
systemctl start --no-block citrinitas-fetch.service || true
if [ -f "$STATE/rejected.json" ]; then mv "$STATE/rejected.json" "$STATE/rejected.last.json"; fi

# Old releases and unused environments are removed by tidy.py, which only ever deletes directories named
# like a commit or a lock hash below releases/ and venvs/.
"$VENV/bin/python" "$REL/deploy/tidy.py" "$HOME_DIR" || true
echo "commit $COMMIT is live (sandbox: $LEVEL)"
