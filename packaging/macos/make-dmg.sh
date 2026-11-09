#!/usr/bin/env bash
# Package dist/FREQUENZ.app into an unsigned .dmg and write SHA256SUMS.
#
# usage: packaging/macos/make-dmg.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="$ROOT/dist/FREQUENZ.app"
VERSION="$("$ROOT/.venv/bin/python" -c 'import frequenzradio; print(frequenzradio.__version__)')"
STAGE="$ROOT/build/dmg"
DMG="$ROOT/dist/FREQUENZ-$VERSION-arm64.dmg"

[[ -d "$APP" ]] || { echo "error: build the app first: packaging/macos/build-app.sh" >&2; exit 1; }

echo "==> Staging"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/FREQUENZ.app"
ln -s /Applications "$STAGE/Applications"

echo "==> Creating $DMG"
rm -f "$DMG"
hdiutil create -volname "FREQUENZ $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

echo "==> Checksums"
(
    cd "$ROOT/dist"
    shasum -a 256 "$(basename "$DMG")" > SHA256SUMS
    cat SHA256SUMS
)

echo "==> Done: $DMG ($(du -sh "$DMG" | cut -f1))"
