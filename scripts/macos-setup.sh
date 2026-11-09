#!/usr/bin/env bash
# Set up FREQUENZ on a Mac from this checkout: Homebrew libraries, a Python environment, the app,
# a doctor check, the globe map and a 40-place station sample. Run it from the repository root
# (the script changes to it). It stops at the first failed step.
# Written without a macOS test run: see docs/macos/HANDOFF.md.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is for macOS." >&2
  exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "Note: this Mac is $(uname -m), not Apple Silicon. The plan targets arm64." >&2
fi
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is missing. Install it from https://brew.sh, then run this script again." >&2
  exit 1
fi

echo "== Homebrew libraries"
brew install gtk4 libadwaita gstreamer adwaita-icon-theme pygobject3

PY="$(brew --prefix)/bin/python3"
echo "== GTK check with $PY"
"$PY" -c "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk; print('GTK', Gtk.get_major_version(), Gtk.get_minor_version())"

echo "== Python environment"
"$PY" -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[test,build]'

echo "== Doctor (warnings about the catalog and the map are expected here)"
.venv/bin/frequenz doctor || true

echo "== Globe map (about 31 MB download)"
.venv/bin/frequenz build-globe

echo "== Station sample (first 40 places)"
.venv/bin/frequenz sync --limit 40

echo
echo "Done. Next:"
echo "  .venv/bin/python tests/globe_gl_probe.py 12   # OpenGL check"
echo "  .venv/bin/frequenz                            # start the app"
