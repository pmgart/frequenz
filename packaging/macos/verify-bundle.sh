#!/usr/bin/env bash
# Check a built FREQUENZ.app: no Homebrew paths, a valid signature, and a doctor
# run plus a snapshot from inside the bundle.
#
# usage: packaging/macos/verify-bundle.sh [dist/FREQUENZ.app]

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="${1:-$ROOT/dist/FREQUENZ.app}"
BIN="$APP/Contents/MacOS/frequenz"
failures=0

check() {
    local name="$1"
    shift
    if "$@"; then
        printf 'PASS %s\n' "$name"
    else
        printf 'FAIL %s\n' "$name"
        failures=$((failures + 1))
    fi
}

[[ -d "$APP" ]] || { echo "error: no app at $APP" >&2; exit 1; }

echo "==> Homebrew load paths"
check "no Homebrew paths in Mach-O dependencies" \
      "$ROOT/.venv/bin/python" "$ROOT/packaging/macos/check-dylibs.py" "$APP"

echo "==> Signature"
check "signature verifies" codesign --verify --deep --strict "$APP"

echo "==> Doctor from inside the bundle"
if "$BIN" doctor >/tmp/frequenz-bundle-doctor.log 2>&1; then
    grep -E '^\[|^==|^Done' /tmp/frequenz-bundle-doctor.log | sed -n '1,20p'
    check "doctor exits 0" true
else
    tail -n 20 /tmp/frequenz-bundle-doctor.log
    check "doctor exits 0" false
fi

echo "==> Window snapshot"
SNAPSHOT="${TMPDIR:-/tmp}/frequenz-bundle.png"
rm -f "$SNAPSHOT"
FREQUENZ_SNAPSHOT="$SNAPSHOT" FREQUENZ_SNAPSHOT_AFTER=6 "$BIN" >/tmp/frequenz-bundle-run.log 2>&1 &
pid=$!
for _ in $(seq 1 20); do
    [[ -f "$SNAPSHOT" ]] && break
    sleep 1
done
kill "$pid" 2>/dev/null || true
wait "$pid" 2>/dev/null || true
check "snapshot written" test -s "$SNAPSHOT"
if [[ -s "$SNAPSHOT" ]]; then
    echo "     $SNAPSHOT"
fi

echo
if [[ "$failures" -eq 0 ]]; then
    echo "All bundle checks passed."
else
    echo "$failures bundle check(s) failed."
    exit 1
fi
