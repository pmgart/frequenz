#!/usr/bin/env bash
# Install FREQUENZ for the current user (no root needed).
#   scripts/install-desktop.sh            install launcher + icon for the venv in ./.venv
#   scripts/install-desktop.sh --repair   rebuild the venv if the interpreter changed, then install
#   scripts/install-desktop.sh --remove   remove the launcher and icon again
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ID="se.laps.Frequenz"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
DESKTOP_FILE="$APPS_DIR/$APP_ID.desktop"
ICON_FILE="$ICON_DIR/$APP_ID.svg"
VENV="$ROOT/.venv"
LAUNCHER="$VENV/bin/frequenz"

REPAIR=0
ACTION="install"
for arg in "$@"; do
    case "$arg" in
        --remove) ACTION="remove" ;;
        --repair) REPAIR=1 ;;
        -h|--help)
            sed -n '2,5p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "error: unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

if [[ "$ACTION" == "remove" ]]; then
    rm -f "$DESKTOP_FILE" "$ICON_FILE"
    echo "Removed $DESKTOP_FILE and $ICON_FILE"
    exit 0
fi

# A virtualenv records the interpreter it was built with and keeps its packages in
# lib/pythonX.Y/site-packages. A Fedora release upgrade moves /usr/bin/python3 to a new
# minor version, the venv's python3 symlink follows it, and the old site-packages folder
# drops off sys.path: the app then dies with "ModuleNotFoundError: No module named
# 'frequenzradio'" even though nothing is wrong with the code or the data.
venv_healthy() {
    # -P keeps the current directory off sys.path and we run from /, so the import has to
    # come from the venv's site-packages, exactly like the console script started by the
    # desktop file. Without this, the source tree in $ROOT satisfies the import and a
    # venv that cannot run the app still looks healthy.
    [[ -x "$VENV/bin/python" ]] && ( cd / && "$VENV/bin/python" -P -c 'import frequenzradio' ) 2>/dev/null
}

venv_declared() {
    local cfg="$VENV/pyvenv.cfg"
    [[ -f "$cfg" ]] || return 0
    awk -F= '/^ *version *=/ { gsub(/ /, "", $2); print $2; exit }' "$cfg"
}

# The venv needs PyGObject, GTK and GStreamer from the OS, so it must be built with the
# system interpreter: a conda, pyenv or uv python3 earlier in PATH has no gi module and
# would produce a venv that cannot start the app.
find_python() {
    if [[ -n "${FREQUENZ_PYTHON:-}" ]]; then
        printf '%s\n' "$FREQUENZ_PYTHON"
    elif [[ -x /usr/bin/python3 ]]; then
        printf '%s\n' /usr/bin/python3
    else
        command -v python3 || true
    fi
}

repair_venv() {
    if [[ -z "$PYTHON" ]]; then
        echo "error: python3 not found; install it with: sudo dnf install python3" >&2
        exit 1
    fi
    if [[ -d "$VENV" ]]; then
        echo "Rebuilding $VENV for $("$PYTHON" -V 2>&1) ($PYTHON)" >&2
        rm -rf "$VENV"
    else
        echo "Creating $VENV for $("$PYTHON" -V 2>&1) ($PYTHON)" >&2
    fi
    "$PYTHON" -m venv --system-site-packages "$VENV"
    "$VENV/bin/python" -m pip install --quiet --upgrade pip
    ( cd "$ROOT" && "$VENV/bin/python" -m pip install --quiet -e '.[build,test]' )
    echo "Venv rebuilt: $VENV" >&2
}

PYTHON="$(find_python)"

if [[ ! -x "$LAUNCHER" ]]; then
    if [[ "$REPAIR" == "1" ]]; then
        repair_venv
    else
        echo "error: $LAUNCHER not found. Create the venv first (see README.md)," >&2
        echo "       or run this script with --repair." >&2
        exit 1
    fi
fi

if ! venv_healthy; then
    declared="$(venv_declared)"
    echo "warning: $VENV cannot import frequenzradio." >&2
    if [[ -n "$declared" && -n "$PYTHON" ]]; then
        echo "         pyvenv.cfg was built for Python $declared; $PYTHON is $("$PYTHON" -V 2>&1)." >&2
    fi
    if [[ "$REPAIR" == "1" ]]; then
        repair_venv
        if ! venv_healthy; then
            echo "error: $VENV still cannot import frequenzradio after the rebuild." >&2
            exit 1
        fi
    else
        echo "         Re-run with --repair to rebuild it:" >&2
        echo "           $0 --repair" >&2
        exit 1
    fi
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
