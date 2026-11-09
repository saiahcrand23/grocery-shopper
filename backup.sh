#!/usr/bin/env bash
# Nightly snapshot of the grocery database, run by the grocery-backup timer.
#
# Uses SQLite's online backup API rather than copying the file: the server is
# running and may be mid-write, and a plain cp can capture a torn page that
# only reveals itself the day you need it.
set -euo pipefail

DB="${GROCERY_DB_PATH:-$HOME/grocery-shopper-data/grocery.db}"
DEST="$HOME/grocery-shopper-data/backups"
KEEP_DAYS=30

mkdir -p "$DEST"
OUT="$DEST/grocery-$(date +%F).db"

python3 - "$DB" "$OUT" <<'PY'
import sqlite3, sys
src_path, out_path = sys.argv[1], sys.argv[2]
src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
dst = sqlite3.connect(out_path)
with dst:
    src.backup(dst)
# A backup nobody has opened is a guess. Check it before trusting it.
if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
    raise SystemExit("integrity check failed on the backup")
need = {"items", "orders", "order_lines", "recipes", "recipe_ingredients"}
have = {r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")}
missing = need - have
if missing:
    raise SystemExit(f"backup is missing tables: {', '.join(sorted(missing))}")
orders = dst.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
items = dst.execute("SELECT COUNT(*) FROM items").fetchone()[0]
dst.close(); src.close()
print(f"{out_path}: ok, {orders} orders, {items} items")
PY

# Prune old snapshots. Only ever touches this directory's own dated files.
find "$DEST" -maxdepth 1 -name 'grocery-????-??-??.db' -mtime "+$KEEP_DAYS" -print -delete

echo "kept $(find "$DEST" -maxdepth 1 -name 'grocery-*.db' | wc -l) snapshots in $DEST"
