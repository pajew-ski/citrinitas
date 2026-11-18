#!/bin/sh
# Installed as /usr/local/bin/citrinitas-pull and run by citrinitas-pull.timer as root.
# Brings the checkout to the tip of the branch and lets install.sh decide whether it goes live.
set -e
exec 9>/run/citrinitas-pull.lock
flock -n 9 || exit 0   # one install at a time
HOME_DIR=/srv/citrinitas
BRANCH=$(cat "$HOME_DIR/etc/branch" 2>/dev/null || echo main)
git -C "$HOME_DIR/repo" fetch -q --depth 1 origin "$BRANCH"
git -C "$HOME_DIR/repo" reset -q --hard FETCH_HEAD
exec "$HOME_DIR/repo/deploy/install.sh"
