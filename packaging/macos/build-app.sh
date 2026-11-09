#!/usr/bin/env bash
# Build dist/FREQUENZ.app: a self-contained Apple Silicon app bundle.
#
# The bundle carries its own Python, GTK 4, libadwaita, GStreamer, the GIR
# typelibs, the GSettings schemas, the Adwaita icons, Inter and the globe map,
# with every dylib rewritten to @executable_path. Nothing outside the bundle is
# needed at run time.
#
# Requirements: the Homebrew libraries from scripts/macos-setup.sh, the dylibbundler
# formula, and a built .venv in the checkout.
#
# usage: packaging/macos/build-app.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BREW="$(brew --prefix)"
PYTHON="$ROOT/.venv/bin/python"
APP_NAME="FREQUENZ"
APP="$ROOT/dist/FREQUENZ.app"
DATA="${XDG_DATA_HOME:-$HOME/Library/Application Support}/frequenz"

step() { printf '\n==> %s\n' "$1"; }
fail() { printf 'error: %s\n' "$1" >&2; exit 1; }

[[ -x "$PYTHON" ]] || fail "no .venv; run scripts/macos-setup.sh first"
command -v dylibbundler >/dev/null || fail "dylibbundler is missing; run: brew install dylibbundler"
command -v rsvg-convert >/dev/null || fail "rsvg-convert is missing; run: brew install librsvg"
[[ -d "$BREW/opt/gtk4" ]] || fail "gtk4 is missing; run scripts/macos-setup.sh"

PY_VER="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
VENV_SP="$ROOT/.venv/lib/python$PY_VER/site-packages"
PY_FW_SRC="$(cd "$BREW/opt/python@$PY_VER/Frameworks/Python.framework" && pwd -P)"
VERSION="$("$PYTHON" -c 'import frequenzradio; print(frequenzradio.__version__)')"
PYTHON_BIN="$PY_FW_SRC/Versions/$PY_VER/Resources/Python.app/Contents/MacOS/Python"

[[ -d "$VENV_SP" ]] || fail "no site-packages in .venv for Python $PY_VER"
[[ -x "$PYTHON_BIN" ]] || fail "no Homebrew Python $PY_VER framework"

step "Bundle skeleton ($APP_NAME $VERSION)"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Frameworks" "$APP/Contents/Resources"
printf 'APPL????' > "$APP/Contents/PkgInfo"

step "Python $PY_VER framework"
rsync -a "$PY_FW_SRC/" "$APP/Contents/Frameworks/Python.framework/"
PY_FW="$APP/Contents/Frameworks/Python.framework/Versions/$PY_VER"
STDLIB="$PY_FW/lib/python$PY_VER"
SP="$STDLIB/site-packages"

# Homebrew points the framework's site-packages at /opt/homebrew and adds that path
# from a sitecustomize; both must go, or the bundle would import host packages.
rm -rf "$SP"
mkdir -p "$SP"
rm -f "$STDLIB/sitecustomize.py"

# Documentation, tests and the Tk GUI are not needed at run time.
rm -rf "$STDLIB/test" "$STDLIB/idlelib" "$STDLIB/turtledemo" "$STDLIB/tkinter" \
       "$STDLIB/ensurepip" "$STDLIB/lib2to3" "$STDLIB/venv"

step "Python packages"
cp -R "$ROOT/frequenzradio" "$SP/frequenzradio"
rm -rf "$SP/frequenzradio/__pycache__"
cp -R "$VENV_SP/OpenGL" "$SP/OpenGL"
cp -R "$VENV_SP/numpy" "$SP/numpy"
# Homebrew's site-packages are symlink farms into the Cellar; dereference them.
cp -RL "$BREW/lib/python$PY_VER/site-packages/gi" "$SP/gi"
cp -RL "$BREW/lib/python$PY_VER/site-packages/cairo" "$SP/cairo"
find "$SP" -name '__pycache__' -type d -prune -exec rm -rf {} +

step "GIR typelibs"
mkdir -p "$APP/Contents/Resources/girepository-1.0"
for typelib in "$BREW/lib/girepository-1.0/"*.typelib; do
    if [[ -e "$typelib" ]]; then cp "$typelib" "$APP/Contents/Resources/girepository-1.0/"; fi
done
# The GTK 3 typelibs are not used and would let a stray import load a second GTK.
rm -f "$APP/Contents/Resources/girepository-1.0/Gtk-3.0.typelib" \
      "$APP/Contents/Resources/girepository-1.0/Gdk-3.0.typelib" \
      "$APP/Contents/Resources/girepository-1.0/GdkX11-3.0.typelib"

# A typelib dlopens its library by bare name (libgtk-4.1.dylib), so those
# libraries are never seen as a link-time dependency. Copy them in and let the
# bundler fix their own dependencies.
TYPELIB_BINARIES=()
for typelib in "$APP/Contents/Resources/girepository-1.0/"*.typelib; do
    library="$(strings "$typelib" | grep -E '\.dylib$' | head -n 1 || true)"
    if [[ -n "$library" && -e "$BREW/lib/$library" ]]; then
        rm -f "$APP/Contents/Frameworks/$library"
        cp "$BREW/lib/$library" "$APP/Contents/Frameworks/$library"
        TYPELIB_BINARIES+=("$APP/Contents/Frameworks/$library")
    fi
done

step "GStreamer plugins and scanner"
mkdir -p "$APP/Contents/Resources/gstreamer-1.0"
for plugin in "$BREW/lib/gstreamer-1.0/"*.dylib; do
    if [[ -e "$plugin" ]]; then cp "$plugin" "$APP/Contents/Resources/gstreamer-1.0/"; fi
done
# libgstgtk links GTK 3 (duplicate Objective-C classes next to GTK 4); the
# python plugin would load a second interpreter.
rm -f "$APP/Contents/Resources/gstreamer-1.0/libgstgtk.dylib" \
      "$APP/Contents/Resources/gstreamer-1.0/libgstgtk4.dylib" \
      "$APP/Contents/Resources/gstreamer-1.0/libgstpython.dylib"
# The scanner is a second executable; it sits next to the launcher so that
# @executable_path/../Frameworks resolves the same way for it.
cp "$(brew --prefix gstreamer)/libexec/gstreamer-1.0/gst-plugin-scanner" "$APP/Contents/MacOS/"

step "GdkPixbuf loaders"
mkdir -p "$APP/Contents/Resources/gdk-pixbuf-2.0/loaders"
for loader in "$BREW/lib/gdk-pixbuf-2.0/2.10.0/loaders/"*.so; do
    if [[ -e "$loader" ]]; then cp "$loader" "$APP/Contents/Resources/gdk-pixbuf-2.0/loaders/"; fi
done

step "GIO modules (TLS)"
# souphttpsrc asks glib-networking for TLS. Without a module there is no https;
# with the host's module, Homebrew's glib would be loaded next to the bundled
# one (duplicate ObjC classes, GTlsBackendGnutls fails). GIO_MODULE_DIR points
# at this folder in the launcher.
mkdir -p "$APP/Contents/Resources/gio/modules"
GIO_MODULES=()
for module in "$BREW/lib/gio/modules/"*.so; do
    if [[ -e "$module" ]]; then
        cp "$module" "$APP/Contents/Resources/gio/modules/"
    fi
done
for module in "$APP/Contents/Resources/gio/modules/"*.so; do
    GIO_MODULES+=("$module")
done

step "GSettings schemas"
mkdir -p "$APP/Contents/Resources/share/glib-2.0/schemas"
for schema in "$BREW/share/glib-2.0/schemas/"*.xml "$BREW/share/glib-2.0/schemas/"*.dtd; do
    if [[ -e "$schema" ]]; then cp "$schema" "$APP/Contents/Resources/share/glib-2.0/schemas/"; fi
done
glib-compile-schemas "$APP/Contents/Resources/share/glib-2.0/schemas"

step "Adwaita icons"
# Homebrew's icon trees are symlink farms into the Cellar, with some links to
# files that are not installed. Copy the real files and skip the broken links.
copy_tree() {
    "$PYTHON" - "$1" "$2" <<'PY_ICONS'
import os, shutil, sys
source, target = sys.argv[1], sys.argv[2]
for root, _dirs, files in os.walk(source):
    relative = os.path.relpath(root, source)
    out = target if relative == "." else os.path.join(target, relative)
    os.makedirs(out, exist_ok=True)
    for name in files:
        path = os.path.join(root, name)
        if os.path.exists(path):
            shutil.copy2(path, os.path.join(out, name))
PY_ICONS
}
mkdir -p "$APP/Contents/Resources/share/icons"
copy_tree "$BREW/share/icons/Adwaita" "$APP/Contents/Resources/share/icons/Adwaita"
if [[ -d "$BREW/share/icons/hicolor" ]]; then
    copy_tree "$BREW/share/icons/hicolor" "$APP/Contents/Resources/share/icons/hicolor"
fi

step "Globe map"
GLOBE_SRC="$DATA/globe"
if [[ ! -f "$GLOBE_SRC/manifest.json" ]]; then
    "$ROOT/.venv/bin/frequenz" build-globe
fi
[[ -f "$GLOBE_SRC/manifest.json" ]] || fail "no globe map at $GLOBE_SRC"
cp -R "$GLOBE_SRC" "$APP/Contents/Resources/globe"

step "Inter"
mkdir -p "$APP/Contents/Resources/fonts"
INTER="$HOME/Library/Fonts/Inter-VariableFont_slnt,wght.ttf"
if [[ -f "$INTER" ]]; then
    cp "$INTER" "$APP/Contents/Resources/fonts/Inter.ttf"
else
    printf 'warning: Inter is not in ~/Library/Fonts; the app falls back to the system font\n' >&2
fi

step "App icon"
ICONSET="$ROOT/build/Frequenz.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
SVG="$ROOT/frequenzradio/data/icons/hicolor/scalable/apps/se.laps.Frequenz.svg"
for size in 16 32 128 256 512; do
    rsvg-convert -w "$size" -h "$size" "$SVG" -o "$ICONSET/icon_${size}x${size}.png"
    double=$((size * 2))
    rsvg-convert -w "$double" -h "$double" "$SVG" -o "$ICONSET/icon_${size}x${size}@2x.png"
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/Frequenz.icns"

step "Licences"
mkdir -p "$APP/Contents/Resources/licenses"
cp "$ROOT/LICENSE" "$APP/Contents/Resources/licenses/GPL-3.0-or-later.txt"
cp "$ROOT/packaging/macos/licenses/LGPL-2.1.txt" "$APP/Contents/Resources/licenses/"
cp "$ROOT/packaging/macos/licenses/Inter-OFL.txt" "$APP/Contents/Resources/licenses/"
cp "$STDLIB/LICENSE.txt" "$APP/Contents/Resources/licenses/Python-2.0.txt"
cp "$ROOT/frequenzradio/data/icons/symbolic/LICENSE-lucide.txt" "$APP/Contents/Resources/licenses/Lucide-ISC.txt"
cat > "$APP/Contents/Resources/licenses/Natural-Earth.txt" <<'EOF'
Natural Earth vector data (1:10m land, lakes, glaciated areas, admin boundaries,
rivers) is in the public domain: https://www.naturalearthdata.com/about/terms-of-use/
EOF

step "Info.plist and launcher"
sed -e "s/@VERSION@/$VERSION/g" "$ROOT/packaging/macos/Info.plist.in" > "$APP/Contents/Info.plist"
clang -O2 -Wall -Wextra -DPYTHON_VERSION="\"$PY_VER\"" \
      -o "$APP/Contents/MacOS/frequenz" "$ROOT/packaging/macos/launcher.c"
cp "$PYTHON_BIN" "$APP/Contents/MacOS/frequenz-bin"

step "Relocating the Python framework"
# Python's dylib and everything that links it point at the Cellar; rewrite them to
# the copy that travels inside the bundle.
PY_DYLIB="$PY_FW/Python"
NEW_PY="@executable_path/../Frameworks/Python.framework/Versions/$PY_VER/Python"
install_name_tool -id "$NEW_PY" "$PY_DYLIB"
# A Homebrew build mixes the opt and Cellar spellings of the same path.
for binary in "$APP/Contents/MacOS/frequenz-bin" "$STDLIB/lib-dynload/"*.so; do
    for old in "$BREW/opt/python@$PY_VER/Frameworks/Python.framework/Versions/$PY_VER/Python" \
               "$PY_FW_SRC/Versions/$PY_VER/Python"; do
        if otool -L "$binary" | grep -qF "$old"; then
            install_name_tool -change "$old" "$NEW_PY" "$binary"
        fi
    done
done

step "Bundling dylibs (this takes a few minutes)"
BINARIES=("$APP/Contents/MacOS/frequenz-bin")
for binary in "$SP/gi/"*.so "$SP/gi/overrides/"*.so "$SP/cairo/"*.so "$STDLIB/lib-dynload/"*.so \
              "$APP/Contents/Resources/gstreamer-1.0/"*.dylib \
              "$APP/Contents/Resources/gdk-pixbuf-2.0/loaders/"*.so "${GIO_MODULES[@]}" \
              "${TYPELIB_BINARIES[@]}"; do
    BINARIES+=("$binary")
done
DYLIB_ARGS=()
for binary in "${BINARIES[@]}"; do
    DYLIB_ARGS+=(-x "$binary")
done
mkdir -p "$ROOT/build"
if ! dylibbundler -cd -b -of -ns -s "$BREW/lib" -s "$BREW/lib/gstreamer-1.0" "${DYLIB_ARGS[@]}" \
             -d "$APP/Contents/Frameworks" -p "@executable_path/../Frameworks/" \
             < /dev/null > "$ROOT/build/dylibbundler.log" 2>&1; then
    tail -n 30 "$ROOT/build/dylibbundler.log" >&2
    fail "dylibbundler failed (full log: build/dylibbundler.log)"
fi

# The scanner runs as its own process from Contents/MacOS.
if ! dylibbundler -cd -b -of -ns -s "$BREW/lib" -s "$BREW/lib/gstreamer-1.0" \
             -x "$APP/Contents/MacOS/gst-plugin-scanner" \
             -d "$APP/Contents/Frameworks" -p "@executable_path/../Frameworks/" \
             < /dev/null >> "$ROOT/build/dylibbundler.log" 2>&1; then
    tail -n 30 "$ROOT/build/dylibbundler.log" >&2
    fail "dylibbundler failed on the GStreamer scanner (full log: build/dylibbundler.log)"
fi

step "Byte-compiling the bundle"
# Use the host interpreter: the bundled one has an invalid signature until the
# signing step, and arm64 macOS kills binaries whose signature is broken.
"$PYTHON" -m compileall -q "$STDLIB" >/dev/null || true

step "Cleaning up rpaths"
"$PYTHON" "$ROOT/packaging/macos/fix-rpaths.py" "$APP"

step "Signing (ad hoc)"
# install_name_tool invalidates signatures, and the copied framework carries a
# stale seal. Drop the nested Python.app (the launcher is a copy of its binary),
# clear every seal, sign each Mach-O, then the framework, then the app bundle.
rm -rf "$APP/Contents/Frameworks/Python.framework/Versions/$PY_VER/Resources/Python.app"
find "$APP" -type d -name _CodeSignature -prune -exec rm -rf {} +
signed=0
while IFS= read -r -d '' binary; do
    if file -b "$binary" | grep -q 'Mach-O'; then
        codesign --force --sign - "$binary" >/dev/null 2>&1
        signed=$((signed + 1))
    fi
done < <(find "$APP" -type f -print0)
codesign --force --sign - "$APP/Contents/Frameworks/Python.framework" >/dev/null 2>&1
codesign --force --sign - "$APP" >/dev/null 2>&1
printf '   signed %d Mach-O files\n' "$signed"

step "Done: $APP ($(du -sh "$APP" | cut -f1))"
