#!/usr/bin/env bash
# Pull the latest from GitHub and restart the sync server. Run manually
# whenever you're ready to put changes made elsewhere live on this box.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PIP="$HOME/.venvs/grocery-shopper/bin/pip"
SERVICE="grocery-server"

cd "$REPO_DIR"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Uncommitted local changes in $REPO_DIR — aborting so nothing gets clobbered." >&2
  git status --short
  exit 1
fi

echo "Pulling latest from GitHub..."
BEFORE="$(git rev-parse HEAD)"
git pull --ff-only
AFTER="$(git rev-parse HEAD)"

if [[ "$BEFORE" == "$AFTER" ]]; then
  echo "Already up to date ($AFTER)."
  exit 0
fi

echo "Updated $BEFORE -> $AFTER"

if git diff --name-only "$BEFORE" "$AFTER" | grep -q '^server/requirements.txt$'; then
  echo "server/requirements.txt changed, reinstalling dependencies..."
  "$VENV_PIP" install -r server/requirements.txt
fi

echo "Restarting $SERVICE..."
systemctl --user restart "$SERVICE"

sleep 1
if curl -sf localhost:8000/api/health > /dev/null; then
  echo "Deploy complete, server healthy."
else
  echo "Server did not respond healthy after restart — check: journalctl --user -u $SERVICE -n 50" >&2
  exit 1
fi
