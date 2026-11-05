#!/usr/bin/env bash
# Install FREQUENZ for the current user (no root needed).
#   scripts/install-desktop.sh            install launcher + icon for the venv in ./.venv
#   scripts/install-desktop.sh --remove   remove the launcher and icon again
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ID="se.laps.Frequenz"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
DESKTOP_FILE="$APPS_DIR/$APP_ID.desktop"
ICON_FILE="$ICON_DIR/$APP_ID.svg"

if [[ "${1:-}" == "--remove" ]]; then
    rm -f "$DESKTOP_FILE" "$ICON_FILE"
    echo "Removed $DESKTOP_FILE and $ICON_FILE"
    exit 0
fi

LAUNCHER="$ROOT/.venv/bin/frequenz"
if [[ ! -x "$LAUNCHER" ]]; then
    echo "error: $LAUNCHER not found. Create the venv first (see README.md)." >&2
    exit 1
fi

mkdir -p "$APPS_DIR" "$ICON_DIR"
cp "$ROOT/frequenzradio/data/icons/hicolor/scalable/apps/$APP_ID.svg" "$ICON_FILE"
if grep -q '[\\"`$]' <<< "$LAUNCHER"; then
    echo "error: launcher path contains a quote, backslash, dollar sign or backtick; cannot write it to Exec= safely: $LAUNCHER" >&2
    exit 1
fi
# Exec= values with spaces must be quoted. Unquoted, GLib rejects the entry
# ("Unable to load application information") and the app menu cannot start the app.
EXEC_LINE="Exec=\"$LAUNCHER\""
while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == Exec=* ]]; then
        printf '%s\n' "$EXEC_LINE"
    else
        printf '%s\n' "$line"
    fi
done < "$ROOT/frequenzradio/data/$APP_ID.desktop" > "$DESKTOP_FILE"
chmod 644 "$DESKTOP_FILE"

command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database -q "$APPS_DIR" 2>/dev/null || true

echo "Installed: $DESKTOP_FILE"
echo "Launch from the app menu (FREQUENZ) or run: $LAUNCHER"
