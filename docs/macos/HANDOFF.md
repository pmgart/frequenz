# FREQUENZ on macOS: handoff

- Branch: `macos-app`, created from `main` (v0.2.1). `main` is not changed.
- Approved plan: [PLAN.md](PLAN.md) (rev 1, approved 2026-11-07).
- Last updated: 2026-11-09.

## Status
- **Phase 0 (feasibility): passed on a MacBook Pro (M2 Pro, macOS 27.2).**
  - Globe: OpenGL 4.1 Metal, GLSL 150 shaders compile, 400 frames in the probe,
    median render callback 1.49 ms. The 3.2-core request fixed the framebuffer
    error that the first runs hit.
  - Playback: a real station played for 20.7 s; pause, resume and next work.
  - Tests: 168 unit tests pass on macOS; the manual e2e suite passes 14 of 14
    from the bundle (search, favorites, random station, globe picking at 0.0 px).
  - Doctor: GTK 4.24.1, libadwaita 1.10, GStreamer 1.28.9, osxaudiosink and the
    MP3/AAC/Opus/Vorbis/FLAC decoders, the macOS window server, the globe map.
- **Phase 2 (packaging): done on this branch.** `packaging/macos/build-app.sh`
  builds a self-contained `dist/FREQUENZ.app` (Python, GTK, libadwaita,
  GStreamer, typelibs, schemas, Adwaita icons, Inter, globe map), ad-hoc signs
  it, and `make-dmg.sh` writes an unsigned `.dmg`. `verify-bundle.sh` checks that
  no Homebrew path is left, the signature verifies, and the app runs a doctor
  check and writes a window snapshot.
- **Phase 3 (real-Mac verification): partly done.** The bundle runs on the
  development Mac. The clean-account test from the mounted `.dmg` is still open.
- **Phase 4 (release): not started.** No notarisation, no Apple Developer
  account, no public Mac release.

## Set up on a Mac
You need Homebrew (https://brew.sh) and the Xcode Command Line Tools
(`xcode-select --install`).

```
brew install gh
gh auth login
gh repo clone pmgart/frequenz ~/Developer/frequenz
cd ~/Developer/frequenz
git switch macos-app
scripts/macos-setup.sh
```

`gh auth login` opens the browser. Log in there; no token goes into Terminal.

Then check OpenGL and start the app from source:

```
.venv/bin/python tests/globe_gl_probe.py 12
.venv/bin/frequenz
```

## Build the app bundle and the .dmg

```
brew install dylibbundler
packaging/macos/build-app.sh          # dist/FREQUENZ.app
packaging/macos/verify-bundle.sh      # leaks, signature, doctor, snapshot
packaging/macos/make-dmg.sh           # dist/FREQUENZ-<version>-arm64.dmg + SHA256SUMS
```

`build-app.sh` needs the Homebrew libraries, a `.venv`, the built globe map (it
runs `frequenz build-globe` when missing) and Inter in `~/Library/Fonts` (it
falls back to the system font if the file is absent). It signs every Mach-O file
ad hoc, then the framework, then the app.

The bundle is about 455 MB on disk. Almost all of that is GStreamer's plugin set
and Python; the `.dmg` compresses to roughly a third.

## How the bundle finds its files
`Contents/MacOS/frequenz` is a small launcher (compiled from `launcher.c`). It
sets `PYTHONHOME`, `GI_TYPELIB_PATH`, `GSETTINGS_SCHEMA_DIR`,
`GDK_PIXBUF_MODULEDIR`, the `GST_*` paths and `FREQUENZ_BUNDLE_RESOURCES`, then
executes `Contents/MacOS/frequenz-bin` (a copy of the framework's Python). Every
dylib is rewritten to `@executable_path/../Frameworks`, and `fix-rpaths.py`
removes the duplicate `LC_RPATH` entries dylibbundler leaves behind (dyld refuses
to load a library with duplicate rpaths, which silently kills plugins).

A typelib loads its library by bare name (`libgtk-4.1.dylib`), so those libraries
are copied explicitly; a link-time dependency walk does not see them.

GIO's TLS backend lives in `Resources/gio/modules` and the launcher points
`GIO_MODULE_DIR` at it. Without the module there is no https at all; with the
host's Homebrew module instead, Homebrew's glib is loaded next to the bundled one
and `GTlsBackendGnutls` fails, so every https stream stops. That bug made the
first bundle build play only unencrypted streams.

`FREQUENZ_BUNDLE_RESOURCES` also makes the app copy `Resources/globe` into the
data folder on first launch, and `frequenzradio/fonts.py` registers the bundled
Inter with CoreText for the process, so nothing is installed into the user's
font folder.

## Stations

The `.app` does not include the catalog. A fresh install shows
"Downloading the station list" in the right panel and fills a progress bar while
the catalog downloads in the background (12,852 places, roughly 15–20 minutes on
a good connection). The sync is resumable; quitting and reopening continues where
it stopped. `FREQUENZ_SAMPLE=1 scripts/macos-setup.sh` syncs only 40 places for a
quick look.

To use a complete catalog file from another machine, quit FREQUENZ, move the
existing `catalog.sqlite` in `~/Library/Application Support/frequenz` aside,
delete any `catalog.sqlite-wal` and `catalog.sqlite-shm` next to it, copy the file
in as `catalog.sqlite`, and check it with `.venv/bin/frequenz stats`.

## What to report back
- `sw_vers -productVersion` and `uname -m`
- the full output of `.venv/bin/frequenz doctor`
- the last 10 lines of the probe output
- what the window does (a screenshot or a description)
- the exact text of any error

## Known gaps
- The app is ad-hoc signed and not notarised. On another Mac the first launch
  needs Open Anyway; a public release needs a Developer ID and notarisation.
- The Homebrew bottles on this machine are built with `minos 27.0`, so the bundle
  requires macOS 27 or newer. Supporting macOS 26 would need older bottles or
  building GTK and GStreamer from source.
- The catalog is not bundled, by design: it is downloaded on first launch.
- Inter is taken from `~/Library/Fonts` at build time. Without it the UI falls
  back to the system font.
- The app keeps its own light/dark switch and does not follow the macOS
  appearance.
- No media-key or Now Playing integration yet.

## Tests
```
.venv/bin/python -m pytest -q
.venv/bin/python -m pyflakes frequenzradio tests
```
