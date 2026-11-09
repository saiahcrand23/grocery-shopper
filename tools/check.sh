#!/usr/bin/env bash
# Static checks for index.html's script. There's no build step and no test
# runner here, so this is the safety net: run it before deploying a client
# change.
#
# Needs gjs (GNOME's SpiderMonkey), which is already on this box.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

python3 - "$ROOT/index.html" "$WORK/app.js" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
m = re.search(r"<script>(.*)</script>", src, re.S)
if not m:
    raise SystemExit("no <script> block found in index.html")
open(sys.argv[2], "w").write(m.group(1))
PY

cp "$ROOT/tools/syntax.js" "$ROOT/tools/defined.js" "$WORK/"
cd "$WORK"
gjs syntax.js
gjs defined.js
