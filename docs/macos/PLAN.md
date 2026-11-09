# FREQUENZ for macOS: plan

> Approved 2026-11-07 (rev 1). Status 2026-11-09: Phase 0 passed on the MacBook Pro (M2 Pro); Phase 1 and Phase 2 are on branch `macos-app`; the bundle and dmg build and run, the clean-account test is open. A GitHub macOS job is optional. Current state and setup: `HANDOFF.md`.

## Summary
- Build a native Mac app, `FREQUENZ.app`, from the same GTK 4, libadwaita and GStreamer code as Linux. One source tree. The Mac work lives on the `macos-app` branch.
- Chosen 2026-11-07: Apple Silicon only, macOS 26 Tahoe or newer; unsigned `.dmg` now, notarisation before any public launch; the Mac build stays on a separate release track until it passes on a real Mac.
- Feasibility is open until Phase 0. Three risks: (1) the globe needs OpenGL 3.3 core on macOS, and the desktop shader path has never run on real hardware; (2) bundling GTK, GStreamer and Python into a relocatable app; (3) libadwaita is mainly tested on Linux.
- Rejected: a native Swift/AppKit rewrite (a second codebase, globe shaders rewritten, highest cost).
- Fallback if Phase 0 fails: a Homebrew formula (Q2, option 3). Work stops there for your decision.

## Key changes

### Shared code (one codebase; Linux behaviour unchanged)
1. `frequenzradio/osinfo.py` (new): `is_macos()`, `desktop_gl_version()` (3, 3 on macOS; 3, 0 elsewhere), `primary_label()` ("⌘" on macOS, "Ctrl" elsewhere), `quit_accels()` (`<Meta>q` and `<Control>q` on macOS; `<Primary>q` elsewhere). Consumers: items 3 to 6.
2. `frequenzradio/paths.py` `data_dir()`: on macOS, `~/Library/Application Support/frequenz` when `XDG_DATA_HOME` is unset; the override stays first. Consumers: `catalog_path` (cli.py lines 76, 130, 146; doctor.py 64; window.py 48, 795), `state_path` (state.py 30, 42), `naturalearth_dir` (cli.py 51, 63, 65; tests/test_globe_data.py 98), `globe_dir` (cli.py 51, 64, 65; doctor.py 79, 81; window.py 24, 97; tests/test_globe_data.py). tests/test_state.py sets `XDG_DATA_HOME` and stays unchanged.
3. `frequenzradio/globe.py`: PyOpenGL uses EGL only on Linux with `WAYLAND_DISPLAY`; the request becomes `set_required_version(*desktop_gl_version())`. The shader source (desktop GLSL 330 path) and `_setup_gl` stay as they are. Consumers: window.py (`GlobeView(...)`); tests/globe_zoom_check.py and tests/e2e_gui_check.py run the GTK app.
4. `frequenzradio/doctor.py`: on macOS the display check asks GTK whether a display opens (`Gtk.init_check()`), since neither `WAYLAND_DISPLAY` nor `DISPLAY` is set there. Consumers: cli.py lines 159–161 (`doctor` subcommand).
5. `frequenzradio/window.py`: shortcut dialog text uses `primary_label()` (⌘ on macOS). The search key (`_on_key_pressed`) accepts Control, and Command as well on macOS, through `_primary_mask()`. About `comments` reads "for Linux and macOS". Consumers: the `win.shortcuts` action (line 325). preferences.py is unchanged.
6. `frequenzradio/app.py`: quit accelerators come from `quit_accels()`. New: if `FREQUENZ_BUNDLE_RESOURCES` is set and `globe_dir()` has no map, the bundled `globe/` folder is copied there. Consumers: `run_gui` (cli.py gui path); snapshot hooks unchanged.
7. `frequenzradio/cli.py`: description reads "for Linux and macOS"; the globe-build hint names `frequenzradio[build]` (the old `frequenz-linux` name was a leftover from the rename).
8. `pyproject.toml`: description reads "for Linux and macOS". No dependency changes.
9. `README.md`: a macOS status note with a pointer to `docs/macos/HANDOFF.md`.
10. `.gitignore`: already ignores `build/` and `dist/`; no change needed.
11. New tests: `tests/test_osinfo.py`, `tests/test_paths_macos.py`, `tests/test_doctor_display.py`, `tests/test_bundle_seed.py`.
12. `tests/globe_gl_probe.py` (new, manual): prints GL_VERSION, GL_SHADING_LANGUAGE_VERSION, GL_RENDERER, GL_POINT_SIZE_RANGE and render timing. It writes no snapshot; use the app's `FREQUENZ_SNAPSHOT` hook for that.

### macOS packaging (Phase 2; done 2026-11-09, see HANDOFF.md)
13. `packaging/macos/build-app.sh` (new): builds `dist/FREQUENZ.app` with a relocatable Python (Phase 0 choice); PyGObject built against the bundled GTK; dylibs relocated into `Contents/Frameworks` (dylibbundler or equivalent); GStreamer plugins and `gst-plugin-scanner`; GdkPixbuf loaders; GSettings schemas; Adwaita icons; Inter (OFL); the pre-built globe map (`frequenz build-globe` in CI); `.icns` from the app icon (`iconutil`); licence texts; ad-hoc signature (`codesign --force --deep -s -`).
14. `packaging/macos/Info.plist.in` (new): `CFBundleIdentifier` `se.laps.Frequenz`; version taken from pyproject.toml; `LSMinimumSystemVersion` 27.0; `NSHighResolutionCapable` true; `CFBundleIconFile`.
15. `packaging/macos/launcher.c` (new; installed as `Contents/MacOS/frequenz`): a small Mach-O launcher that derives every path from the bundle, sets `PYTHONHOME`, `GI_TYPELIB_PATH`, `GSETTINGS_SCHEMA_DIR`, `GDK_PIXBUF_MODULEDIR`, the `GST_*` paths, `XDG_DATA_DIRS`, `DYLD_FALLBACK_LIBRARY_PATH` and `FREQUENZ_BUNDLE_RESOURCES`, then execs `frequenz-bin -m frequenzradio "$@"`. A shell script cannot be the main executable of a bundle whose Python sits several directories down without breaking `@executable_path`. `fix-rpaths.py` and `check-dylibs.py` are helpers.
16. `packaging/macos/make-dmg.sh` (new): `hdiutil create -format UDZO` → `FREQUENZ-<ver>-arm64.dmg`; `shasum -a 256` → `SHA256SUMS`.
17. `packaging/macos/verify-bundle.sh` (new): checks for Homebrew load paths, the signature, `frequenz doctor` inside the bundle, and a snapshot run.
18. `packaging/macos/licenses/` (new): GPL-3.0 and LGPL texts (GTK, libadwaita, GStreamer), Python licence, Inter OFL, Lucide ISC, Natural Earth note.
19. `.github/workflows/macos.yml` (not done; optional): `workflow_dispatch`; runner `macos-26` (arm64); Homebrew: gtk4, libadwaita, gstreamer, pygobject3, dylibbundler, librsvg (formula names to confirm); venv; pytest; `frequenz build-globe`; `build-app.sh`; `verify-bundle.sh`; `make-dmg.sh`; artifact upload. No signing secrets in v1.

### Release
20. Skill `laps-frequenz-release`: Mac steps and the separate-track rule (Q3). No consumers.

### Phases and gates
- **Phase 0, feasibility (throwaway, no product commits).** Run the app from source on the MacBook Pro first; the GitHub macOS job is optional. Gate: GL_VERSION ≥ 3.2 core and the shaders compile (GLSL 150 on macOS; `tests/globe_gl_probe.py`); GL_POINT_SIZE_RANGE covers the marker size; `osxaudiosink` and the decoders are present; 20 s of playback with no bus error; Inter resolved by Pango; header bar placement; minimum macOS from the Homebrew bottles. Output: go/no-go and the bundling choice. No-go → stop and report.
- **Phase 1, shared code** (items 1–12) on `macos-app`.
- **Phase 2, packaging** (items 13–19) on `macos-app`. Done: `build-app.sh` makes a self-contained 455 MB bundle; `verify-bundle.sh` and `make-dmg.sh` complete the pipeline.
- **Phase 3, real-Mac verification** on the MacBook Pro (see Assumption 4).
- **Phase 4, release** as a separate Mac track (item 20).

## Test plan
Linux regression (after Phase 1, and again after the packaging branches merge `macos-app`):
- `cd ~/Developer/Frequenz && .venv/bin/python -m pytest -q`: expect the current count plus the new tests.
- `.venv/bin/python -m pyflakes frequenzradio tests`: no output.
- `.venv/bin/frequenz doctor`: the display line is ok on Wayland.
- `FREQUENZ_DEB_OUT=$HOME/frequenz-release/<ver>/deb packaging/debian/verify-in-ubuntu.sh docker ubuntu:26.04`
- `FREQUENZ_RPM_OUT=$HOME/frequenz-release/<ver>/rpm packaging/fedora/verify-in-fedora.sh docker fedora:latest`

macOS setup, unit tests and doctor (MacBook Pro):
- `scripts/macos-setup.sh`: Homebrew libraries, `.venv` with Homebrew's Python, the app, `frequenz doctor`, the globe map and a 40-place sample. The same commands are listed by hand in HANDOFF.md.
- `.venv/bin/python -m pytest -q`
- `.venv/bin/frequenz doctor`: the display line reads `macOS window server`.

GL and GStreamer gates (Phase 0 and 3):
- `.venv/bin/python tests/globe_gl_probe.py 12`: renderer shown, GL 3.3 or higher core, no GL error.
- `gst-inspect-1.0 osxaudiosink`, `gst-inspect-1.0 avdec_aac`, `gst-inspect-1.0 mpg123audiodec`, `gst-inspect-1.0 opusdec`, `gst-inspect-1.0 vorbisdec`, `gst-inspect-1.0 flacdec`: each element found.
- `.venv/bin/python tests/e2e_gui_check.py`: manual; plays real streams; expect 14 of 14 as on Linux (needs network and a synced catalog).
- `.venv/bin/python tests/globe_zoom_check.py`: manual; expect 10 of 10 as on Linux.

Bundle checks (Phase 2 and 3):
- `packaging/macos/build-app.sh` then `packaging/macos/verify-bundle.sh dist/FREQUENZ.app`
- `find dist/FREQUENZ.app -type f \( -name '*.dylib' -o -perm -u+x \) -exec otool -L {} + | grep -E '/opt/homebrew|/usr/local'`: no output.
- `codesign --verify --deep --strict --verbose=2 dist/FREQUENZ.app`: "valid on disk".
- `FREQUENZ_SNAPSHOT=/tmp/frequenz-mac.png FREQUENZ_SNAPSHOT_AFTER=10 dist/FREQUENZ.app/Contents/MacOS/frequenz`: check the PNG.
- Clean-account test: a second macOS user without Homebrew on PATH; open the app from the mounted `.dmg` after Open Anyway; the globe draws and a station plays.
- `shasum -a 256 -c SHA256SUMS` in the release folder.

Leftover checks: `grep -rn "frequenz-linux" .` → no matches. `grep -rn "for Linux" frequenzradio pyproject.toml` → no matches.

## Implementation notes (2026-11-09)
- The doctor uses `Gtk.init_check()`: `Gdk.Display.get_default()` returns nothing until GTK has initialised.
- The probe writes no snapshot; the app's `FREQUENZ_SNAPSHOT` hook does that.
- The README gets a status note only. There is no `.dmg` to install from yet.
- Search and quit accept Command on macOS. This was added after the shortcut list showed ⌘ while the key handler only read Control.
- `scripts/macos-setup.sh` and the handoff are untested on macOS until the first run.
- First Mac run (2026-11-09): the window, search panel and player drew correctly in light and dark themes. The globe showed "3D globe unavailable: no usable OpenGL context" with the 3.3 request, so the macOS request is now 3.2 core with GLSL 150 shaders. The missing stations came from the 40-place sync; the setup script now syncs the full catalog unless `FREQUENZ_SAMPLE=1` is set.

## Packaging notes (2026-11-09)
- The bundle carries Python 3.15, GTK 4, libadwaita, GStreamer, the typelibs, the GSettings schemas, Adwaita icons, Inter and the globe map. Every dylib is rewritten to `@executable_path/../Frameworks`.
- A typelib loads its library by bare name, so `build-app.sh` copies each typelib's library explicitly; the link-time walk does not see it.
- dylibbundler rewrites all rpaths to the same prefix and leaves duplicates; dyld then refuses to load those plugins. `fix-rpaths.py` removes the duplicates (118 in the 0.2.1 build).
- Homebrew paths the bundle still carried: `Python` referenced by `frequenz-bin` (fixed by rewriting both the `opt` and `Cellar` spellings), `libgstpython` (dropped), and the `lib-dynload`/`gi` override modules (now bundled).
- The Homebrew bottles are built with `minos 27.0`; the bundle therefore requires macOS 27, not 26. Supporting 26 means older bottles or source builds.
- GIO TLS: the bundle carries glib-networking's module and sets `GIO_MODULE_DIR`. Without it the system module loads a second glib and https streams fail.
- First-run catalog: the app already had an empty-catalog sync; it now shows a progress bar and a place/station count on the status page, and a failure message instead of a silent toast.

## Assumptions
1. Target: Apple Silicon, macOS 26 Tahoe or newer (answered 2026-11-07). Intel Macs are out: Tahoe is the last macOS release for them.
2. Unsigned `.dmg` now (answered). arm64 code needs at least an ad-hoc signature; first launch needs Open Anyway in System Settings › Privacy & Security. Public launch needs a Developer ID and notarisation: the Apple Developer Program costs USD 99 a year, and organisation enrolment asks for the legal entity name and a D-U-N-S number.
3. Separate Mac track until it passes on a real Mac (answered). Fedora and Ubuntu keep shipping together under the standing rule.
4. A MacBook Pro with Apple Silicon (M2 Pro) is available from 2026-11-09 and serves Phase 0 and Phase 3. At planning time there was no Mac, so the Mac build was planned as a CI artefact with no real-hardware GUI check.
5. GitHub's `macos-26` arm64 runner is generally available (GitHub changelog, 2026-02-26). Reports say private-repo macOS minutes count about 10× Linux minutes (third-party; check billing). CI may lack a GL 3.3 core context; if so, the GL gate needs a real Mac.
6. GDK tries an OpenGL 3.2 core context by default (GTK docs), but the shader is GLSL 330 core, so the Mac path first requested 3.3 and then 4.1; both failed on the first runs (a generic message, then "invalid share context"). It now requests 3.2 core, the profile GTK uses, with GLSL 150 shaders. The desktop GLSL 330 path has not run on real hardware in the test records: the Ubuntu NVIDIA runs used OpenGL ES 3.2 through EGL.
7. Homebrew provides gtk4, libadwaita and gstreamer, and a public project builds GTK and libadwaita on macOS. libadwaita is mainly tested on Linux (a 2024 article), so Phase 0 decides. Homebrew bottle platforms are unverified.
8. The bundling method (relocated dylibs, relocatable Python, PyGObject against the bundled GTK) is unverified and chosen in Phase 0. The Homebrew gstreamer formula bundles all plugin modules (good, bad, ugly, libav); the element list in the test plan is unverified.
9. The GTK modifier mapping for `<Meta>` and `<Primary>` on macOS is unverified. Both Command and Control are accepted, so the shortcuts work either way.
10. Data folder: `~/Library/Application Support/frequenz`; `XDG_DATA_HOME` still overrides it.
11. The Mac app ships the pre-built globe map (Natural Earth, public domain), so the globe works at first launch. Linux packages keep their current `frequenz build-globe` step; changing that is a separate decision.
12. The radio catalog is not bundled (personal use, not redistributed). It downloads on first use, as on Linux.
13. The User-Agent strings in api.py and player.py stay unchanged; the generic string works today.
14. The app keeps its own light/dark switch and does not follow macOS appearance in v1.
15. Out of scope: the Mac App Store (sandbox and distribution terms need their own review), Intel and universal builds, Sequoia and older.
16. Licences: the .app bundles GPL and LGPL code and Inter (OFL). The release ships the licence texts and the source tarball. A Swedish lawyer should check redistribution and AAC decoding before any public launch (existing legal item).
17. The trademark searches (EUIPO, DPMA, PRV) are still open and must be done before any public Mac launch.
18. Phase 1 must not change Linux behaviour; the Linux tests and container builds check that.
19. No signing secrets are needed in v1. If notarisation is chosen later, the credentials go into GitHub secrets, never into the repo or chat.
20. If Phase 0 fails on GL or bundling, the work stops and you choose between fixing the blocker and the Homebrew formula.
