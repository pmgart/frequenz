# Code review — FREQUENZ 0.2.1 (2026-11-11)

Full-project review before cutting a stable release. Method: the `dev-prompts`
Code Review set — Prompt 1 (senior reviewer pass), Prompt 2 (security), Prompt 3
(performance), Prompt 5 (test gaps), Prompt 7 (concurrency), Prompt 8 (dependencies),
Prompt 9 (error handling) and Prompt 10 (accessibility), run over the complete tree
(`frequenzradio/`, `tests/`, `scripts/`, `packaging/`, README).

**Findings:** 96 — 2 blocker, 26 major, 59 minor, 9 nit.

**Verdict: Request Changes.** No data-loss or security blocker in the application code;
the blockers are packaging defects that make the published RPM uninstallable and the
RPM/DEB artifacts non-identical under the same version.

| Severity | Count | Meaning |
|---|---|---|
| blocker | 2 | must fix before a stable release |
| major | 26 | should fix before a stable release |
| minor | 59 | fix when touching the file |
| nit | 9 | optional |

## Findings

### Blocker (2)

#### B1. Release artifacts are not built from one source: the 0.2.1 RPM and .deb contain different code

- **File:** `packaging/fedora/README.md` line 23 (packaging, release-integrity)
- **Problem:** The README states both packages were built 'from the same program source (commit 8a47904 on main)'. That is not what the branches contain: 8a47904 is on main, the Fedora packaging commit 5ffab86 and the follow-up f363f2f add a cli.py fix plus 38 lines in doctor.py, 102 lines in scripts/install-desktop.sh and tests/test_doctor_venv.py; origin/ubuntu-deb (6b03ae7) is 8a47904 plus Debian packaging only and lacks all of those. So the .rpm and the .deb are different programs under the same version: `frequenz doctor` behaves differently and only the RPM has the venv/--repair fix the README documents. Nothing in either package records the commit it came from.
- **Fix:** Merge the packaging branches into one tree, cut a single commit for 0.2.1, rebuild the RPM, .deb and tarball from that commit, and write that commit id (and the tarball sha256) into both packaging READMEs. Add a generated version/commit file (e.g. baked into __init__) so the artifacts can be traced.

#### B2. Hard Requires on gstreamer1-libav makes the RPM uninstallable on stock Fedora

- **File:** `packaging/fedora/frequenz.spec` line 35 (packaging, packaging-rpm)
- **Problem:** `Requires: gstreamer1-libav` is a hard dependency on a package shipped by RPM Fusion Free, not Fedora. On a stock Fedora install (including the `fedora:latest` container used by verify-in-fedora.sh) `dnf install ./frequenz-0.2.1-1.fc45.noarch.rpm` fails with 'nothing provides gstreamer1-libav', so the documented install command cannot work. It also disqualifies the package for Fedora review, which forbids dependencies on external repositories. The 'Install with runtime dependencies' line in packaging/fedora/README.md:46 was recorded for 0.1.1, before this dependency existed.
- **Fix:** Delete the Requires. Fedora's gstreamer1-plugins-bad-free already provides AAC decoding; if libav is still wanted for other codecs, downgrade it to `Recommends: gstreamer1-libav` so dnf can install the package without RPM Fusion.

### Major (26)

#### M1. One malformed place entry aborts the entire /places payload

- **File:** `frequenzradio/api.py` line 92 (core, correctness)
- **Problem:** parse_places has no per-entry guard: geo[0]/geo[1] are fed to float() and size to int() with only a None/length check. Verified with a real call: one entry with geo ["n/a", 2.0] raises ValueError('could not convert string to float: n/a') and the other 1999 valid places are discarded, so first-run `frequenz sync` fails outright on a single bad remote row. Coordinates are also never range-checked, although the test at tests/test_api.py:25 assumes they are.
- **Fix:** Wrap the loop body in `try: ... except (TypeError, ValueError): continue`, validate -180 <= lng <= 180 and -90 <= lat <= 90 before appending, and coerce size defensively (`int(raw.get("size") or 0)` inside the same try).

#### M2. schema_version is committed before the migration that it gates

- **File:** `frequenzradio/catalog.py` line 131 (core, error-handling)
- **Problem:** `previous` is read, then `set_meta("schema_version", "3")` and `commit()` run, and only afterwards (line 133) does `_clean_existing_metadata()` / `rebuild_search_index()` execute. If the migration raises (disk full, corrupt page, interrupted process), the DB is already stamped version 3 and the repair never runs again on any future open — the unclean metadata stays forever, silently. There is no rollback and no re-check.
- **Fix:** Run the cleanup and index rebuild first, then write schema_version and commit in the same transaction (`with self.db:`), so the version only advances when the migration succeeded.

#### M3. Incremental sync can never pick up new stations in an existing place

- **File:** `frequenzradio/catalog.py` line 175 (core, correctness)
- **Problem:** targets are `WHERE channels_synced = 0`; the upsert at lines 160-168 updates size but never resets channels_synced, and the stored places_version is never compared with the new one (grep confirms it is only printed by `frequenz stats`). So after the first complete run, a plain `frequenz sync` selects zero places and does nothing, and stations added to a city that was already synced stay invisible until the user runs `--full`, which re-fetches all ~2000 places. tests/test_sync_client.py:126-131 encodes this behaviour, and it contradicts the Preferences promise 'Downloads new and changed stations'.
- **Fix:** In the ON CONFLICT clause add `channels_synced = CASE WHEN places.size <> excluded.size THEN 0 ELSE places.channels_synced END`, and compare the fetched `version` with the stored places_version to reset all places when the API signals a change.

#### M4. A corrupt catalog crashes the doctor instead of being reported

- **File:** `frequenzradio/doctor.py` line 106 (core, error-handling)
- **Problem:** Catalog(path) is called with no try/except, unlike every other check in the module. Verified with a non-sqlite file at FREQUENZ_CATALOG: the doctor prints all GTK/GStreamer lines and then raises sqlite3.DatabaseError('file is not a database'), exiting with a traceback and never reaching the vector-map check. This is exactly the situation where a user runs `frequenz doctor`. catalog.close() at line 108 is also not in a finally, so a failure in stats() leaks the connection.
- **Fix:** Wrap the block in try/except (sqlite3.Error, OSError) and report('station catalog', False, str(exc)) with a hint ('the file is not a SQLite database; move it aside and run frequenz sync'); use try/finally for close().

#### M5. A failed batch write aborts the whole sync and is retried blindly in finally

- **File:** `frequenzradio/sync.py` line 85 (core, error-handling)
- **Problem:** `catalog.save_place_stations(pending)` inside the result loop is unguarded, unlike the fetch path which catches per place. Any write error — SQLITE_BUSY after the timeout, a value sqlite rejects, disk full — propagates into the `finally`, which calls save_place_stations(pending) again on the same un-cleared batch (line 91). That second call raises too, replacing the original exception ('During handling of the above exception...') and aborting the entire run, discarding the progress of up to batch_size=100 places that were queued but not yet written. Only the HTTP failure path is isolated.
- **Fix:** Flush per place and catch sqlite3.Error around each flush, adding the place ids to report.failures and continuing; wrap the finally flush in its own try/except so it can never mask the original exception. Committing per place also bounds the blast radius to one place.

#### M6. Documented data directory is wrong; the uninstall instructions disagree with it

- **File:** `README.md` line 22 (packaging, docs)
- **Problem:** README.md:22, :81-82 and :124 point at `~/.local/share/frequenzradio/`, but paths.data_dir() (frequenzradio/paths.py:14) uses `~/.local/share/frequenz`. The same README contradicts itself at :228 and :244, which use `~/.local/share/frequenz`. A user following sections 21-22 or 124 and then the Uninstall section at :244 will `rm -rf` the wrong (non-existent) directory and keep the catalog, favourites, state and the 36 MB globe build.
- **Fix:** Replace all four `frequenzradio/` occurrences with `frequenz/` (or drop the literal path and say `<XDG_DATA_HOME>/frequenz`), and add a test that asserts README's path string matches paths.data_dir().name.

#### M7. build-globe error message names a distribution that does not exist

- **File:** `frequenzradio/cli.py` line 57 (packaging, correctness)
- **Problem:** The ImportError path prints `pip install 'frequenz-linux[build]'`. The project's distribution name in pyproject.toml is `frequenzradio`; `frequenz-linux` appears nowhere else in the repo. The same text is on main:57 (the released 0.2.1) and on origin/ubuntu-deb:frequenzradio/cli.py:57, and it is the fix that only exists on fedora-compat. Because the .deb only Recommends python3-shapely, Debian/Ubuntu users who run `frequenz build-globe` are likely to hit this message and be sent to an install command that fails.
- **Fix:** Print the correct extra (`pip install 'frequenzradio[build]'`) and mention the distro package on packaged installs (`sudo apt install python3-shapely` / `sudo dnf install python3-shapely`); cherry-pick the fedora-compat one-line fix onto main and the ubuntu-deb branch.

#### M8. No tests for the CLI at all

- **File:** `frequenzradio/cli.py` line 164 (packaging, tests)
- **Problem:** No test file imports frequenzradio.cli (verified by AST scan of tests/). The CLI is the documented interface (`sync`, `stats`, `search`, `doctor`, `build-globe`, `--version`) and it carries release-visible behaviour: `_cmd_sync` returns 1 when report.failures is non-empty (cli.py:124), `--version` prints __version__, `_cmd_search` formats rows, and `_cmd_build_globe` returns 1 on the missing-shapely path where the wrong package name lives. None of these exit codes or strings is asserted anywhere.
- **Fix:** Add tests/test_cli.py: call build_parser()/main() with capsys for `--version` (compare with __version__), `stats` and `search` against a tmp FREQUENZ_CATALOG, assert exit code 1 with a fake failing sync, and assert the build-globe ImportError message contains `frequenzradio[build]` (that test would have caught the current bug).

#### M9. Audio-decoder check passes when any single decoder is present

- **File:** `frequenzradio/doctor.py` line 80 (packaging, verification)
- **Problem:** `decoders = [name for name in AUDIO_DECODERS if Gst.ElementFactory.find(name)]` followed by `report(..., bool(decoders), ...)` reports 'ok' as soon as one of MP3/AAC/Opus/Vorbis/FLAC exists. That is why the missing MP3 plugin above went unnoticed in the container run: doctor printed ok, and this is the only runtime check the packaging verification relies on.
- **Fix:** Require each decoder the app promises, e.g. report one row per element (`mpg123audiodec`, `avdec_aac` or the bad-free AAC element, `opusdec`, `vorbisdec`, `flacdec`) and count a missing MP3/AAC decoder as a failure. Then add the same assertions to packaging/fedora/verify-in-fedora.sh after `frequenz doctor`.

#### M10. Player state machine is untested; only clean_icy_title has tests

- **File:** `frequenzradio/player.py` line 189 (packaging, tests)
- **Problem:** tests/test_player_titles.py is the only test that touches player.py and it covers just the pure title cleaner. Untested: the stale-pipeline guard at player.py:190, reconnect/back-off and MAX_RECONNECTS exhaustion (_handle_failure, :218-230), `_on_source_setup` property probing (:179-187), buffering state transitions (:203-208), volume clamping (:116-119) and the pause-disconnects semantics (:85-90). This is the app's core feature and the only part that talks to remote streams; the reconnect and stale-message logic is where a regression would look like 'radio sometimes stops'.
- **Fix:** Unit-test the pure parts by driving `_on_bus_message` with stub message objects and `pipeline is self.pipeline` set/unset, assert the reconnect counter and final error state, and assert set_volume clamps at 0/1. Keep the GStreamer element construction behind a small injectable factory so tests do not need a device.

#### M11. About dialog hardcodes version 0.2.1 instead of __version__

- **File:** `frequenzradio/window.py` line 853 (packaging, correctness)
- **Problem:** `version="0.2.1"` is a fifth copy of the version string (pyproject.toml:7, frequenzradio/__init__.py:3, frequenz.spec:10, debian/changelog:1, here). The next bump that touches only pyproject/__init__ will make the UI report a stale version, and `frequenz --version` and the About dialog will disagree — exactly the kind of drift a stable release must not ship.
- **Fix:** `from . import __version__` and pass `version=__version__`; add a small test that asserts __version__ equals the pyproject version (tomllib) and the spec Version: line, so the release checklist is automated.

#### M12. debian/copyright declares all files GPL-3+ but ships ISC icons

- **File:** `packaging/debian/copyright (origin/ubuntu-deb)` line 6 (packaging, packaging-debian)
- **Problem:** `Files: *` with `License: GPL-3+` covers the whole source tree, yet the package installs frequenzradio/data/icons/symbolic/*.svg (Lucide, ISC) and their LICENSE-lucide.txt into /usr/lib/python3/dist-packages. Debian policy 12.5 requires every copyright and license in the package to be documented, so the .deb's copyright file is factually wrong and would fail an archive/lintian review.
- **Fix:** Add a separate stanza before `Files: *`: `Files: frequenzradio/data/icons/symbolic/*` / `Copyright: 2026 Lucide Icons and Contributors` / `License: ISC` with the ISC text copied from LICENSE-lucide.txt, and restrict the GPL stanza accordingly (or add a `Comment:` noting the bundled Lucide assets).

#### M13. 3.0 (native) cannot produce or rebuild a source package from the shipped tarball

- **File:** `packaging/debian/source/format (origin/ubuntu-deb)` line 1 (packaging, packaging-debian)
- **Problem:** With `3.0 (native)` dpkg-source expects ../frequenz_0.2.1.tar.gz (underscore, no Debian revision), but verify-in-ubuntu.sh ships `frequenz-0.2.1.tar.gz` (dash) with a top-level `frequenz-0.2.1/` directory. `dpkg-buildpackage -S`/`dpkg-source -b` therefore fails, no .dsc can be generated, and the 'source tarball goes with the binary' promise in packaging/debian/README.md:13 does not give anyone a rebuildable Debian source package. Native format is also semantically wrong for software maintained outside Debian.
- **Fix:** Switch to `3.0 (quilt)`, rename the tarball to `frequenz_0.2.1.orig.tar.gz` with the same top-level directory, use version `0.2.1-1` in debian/changelog, and have verify-in-ubuntu.sh run `dpkg-buildpackage -us -uc -b -sa` so a .dsc and .changes are produced and checked.

#### M14. No AppStream metainfo file in either package

- **File:** `packaging/fedora/frequenz.spec` line 5 (packaging, packaging)
- **Problem:** The spec's own header records that there is no metainfo file, and neither the spec nor debian/rules installs /usr/share/metainfo/se.laps.Frequenz.metainfo.xml. Consequences: the app is invisible in GNOME Software and KDE Discover, and the package fails Fedora's mandatory AppStream guidance (and `appstreamcli validate`), so it cannot pass review. The app id is already correct and stable, so the file is cheap to add.
- **Fix:** Add frequenzradio/data/se.laps.Frequenz.metainfo.xml (component id `se.laps.Frequenz`, name/summary/description, GPL-3.0-or-later, launchable `se.laps.Frequenz.desktop`, the screenshots you already produce), install it to %{_datadir}/metainfo in the spec and to /usr/share/metainfo in debian/rules, and add `appstreamcli validate --no-net` to %check and to override_dh_auto_test.

#### M15. License tag omits the bundled ISC-licensed Lucide icons

- **File:** `packaging/fedora/frequenz.spec` line 13 (packaging, packaging-rpm)
- **Problem:** `License: GPL-3.0-or-later` does not mention the icon set: frequenzradio/data/icons/symbolic/LICENSE-lucide.txt says the fq-*-symbolic SVGs come from Lucide under ISC, and that file plus the SVGs are installed into site-packages by `%pyproject_save_files`. Fedora requires the License tag to describe every license in the binary package, so this is a review blocker as written, and the ISC notice is not installed as a %license file.
- **Fix:** Use `License: GPL-3.0-or-later AND ISC` and install the Lucide text explicitly, e.g. `install -Dpm0644 frequenzradio/data/icons/symbolic/LICENSE-lucide.txt %{buildroot}%{_licensedir}/frequenz/LICENSE-lucide.txt` (or add it to %files as %license).

#### M16. No MP3 decoder on Fedora: gstreamer1-plugins-ugly-free is not required

- **File:** `packaging/fedora/frequenz.spec` line 34 (packaging, packaging-rpm)
- **Problem:** The dependency block requires base, good, bad-free and libav but not gstreamer1-plugins-ugly-free. On Fedora the MP3 decoder `mpg123audiodec` (the first entry in doctor.AUDIO_DECODERS) is packaged in gstreamer1-plugins-ugly-free, so a stock Fedora install of this RPM cannot play the most common radio stream format, which is the core function of the app. Packaging/fedora/README.md:33 nevertheless claims MP3 playback is covered.
- **Fix:** Add `Requires: gstreamer1-plugins-ugly-free` (it is in Fedora proper). Confirm with `dnf repoquery -l gstreamer1-plugins-ugly-free | grep mpg123` and re-run the container verification, checking that mpg123audiodec is found.

#### M17. Ctrl+Q quits through the app action, bypassing MainWindow teardown

- **File:** `frequenzradio/app.py` line 47 (ui, concurrency)
- **Problem:** The quit action calls `self.quit()` directly. `Gtk.Application.quit()` ends the main loop; windows are destroyed during `GtkApplication` shutdown and `close-request` is never emitted, so `MainWindow._on_close_request()` (window.py:842) never runs. `_on_shutdown()` only calls `stop_background_work()` (window.py:838), which sets the sync cancel event. Consequences: (a) `Player.shutdown()` is never called, so the Gst pipeline is still in PLAYING when the interpreter finalises it from another thread — the audio device stays open and GStreamer teardown at exit is the classic source of a hanging quit; (b) `Catalog.close()` never runs, leaving the WAL open; (c) `_persist_view()` is not called, so up to 10 s of view state, volume and `last_station` are lost on every Ctrl+Q. Interleaving: Ctrl+Q at t0 → `_on_shutdown` at t0+ε (cancel event set, nothing else) → main loop ends → GTK destroys the window → Python exits while the daemon sync thread and the live pipeline are still running.
- **Fix:** Make `_on_shutdown` perform the full teardown (`self.window.player.shutdown()`, `self.window._persist_view()`, `self.window.catalog.close()`, all idempotent), or change the quit action to `self.window.close()` so `close-request` is emitted and the existing teardown path runs once.

#### M18. Globe cannot be focused or operated without a pointer, and exposes no accessible name

- **File:** `frequenzradio/globe.py` line 352 (ui, accessibility)
- **Problem:** The globe is the primary navigation surface, but `set_focusable(False)` (line 352) makes it unreachable by Tab, and every interaction is a pointer gesture registered in `_install_controllers` (461–480): drag, click, scroll, motion. There is no accessible role/name (`update_property` is never called on the widget), no keyboard equivalent for picking a dot, and no screen-reader representation of the places layer. A keyboard-only or screen-reader user can only reach stations through the sidebar after a pointer pick, or via the undocumented `R` random shortcut (window.py:358).
- **Fix:** Make the view focusable, publish `Gtk.AccessibleProperty.LABEL`/`DESCRIPTION` ("World map of radio places") and `ROLE` (e.g. canvas/group), and add key handling: arrows step to the nearest visible place in that direction, Enter calls `_on_select`, Escape clears. Keep the hover label text in an accessible description so it is announced.

#### M19. A playing station forces a full globe redraw at the display refresh rate forever

- **File:** `frequenzradio/globe.py` line 607 (ui, performance)
- **Problem:** `pulsing` is true whenever a station is playing, so `queue_render()` is called on every frame-clock tick (60–144 Hz) for as long as audio plays, even when the window is idle and nothing else changes. Each render redraws the halo, every surface layer at the current LOD (LOD2 land is the largest mesh), the line layers and two point passes, only so that the 4–8 px playing marker can pulse (POINTS_FS lines 246–250). On integrated GPUs/laptops this pins the GPU and a CPU core for the whole listening session.
- **Fix:** Throttle the pulse: keep an accumulator and call `queue_render()` at ~10–15 Hz while pulsing, or draw the pulse ring into the small overlay instead of the globe. A `self._last_pulse_render` timestamp compared against `time.monotonic()` is enough; the shader already animates from `u_time`.

#### M20. Layer prefetch reads files from disk and uploads them on the main thread

- **File:** `frequenzradio/globe.py` line 678 (ui, performance)
- **Problem:** The prefetch queue (9 entries: land/lakes/ice at LOD1+2, borders LOD1+2, rivers LOD2, built at lines 661–668) is drained one `GLib.idle_add` at a time, and each step does `np.load()` of a multi-MB npz plus `glBufferData` on the GTK main thread (line 683). The same synchronous path is used on demand by `_mesh()` from `_on_render` when the user zooms into a LOD that has not been prefetched yet (lines 785–795). A single LOD2 land upload is tens of MB, so startup steals the main loop repeatedly and the first zoom into LOD1/LOD2 can stall the frame for hundreds of milliseconds (visible freeze of drag/zoom).
- **Fix:** Load the npz in a `threading.Thread`/executor (numpy releases the GIL for the copy) and post the finished arrays to a bounded upload queue that `_on_render` drains one entry per frame (or uploads in a short-lived idle that checks `make_current()`); keep drawing the current LOD until the new mesh is resident.

#### M21. GL uploads in an idle callback call make_current() outside its contract and never clear it

- **File:** `frequenzradio/globe.py` line 682 (ui, concurrency)
- **Problem:** `_prefetch_step` runs from a `GLib.idle_add` (line 669) and calls `self.make_current()`. `Gtk.GLArea.make_current()` is documented for use inside `::realize`/`::render`; its boolean return value is ignored here, and no code in the package calls `Gdk.GLContext.clear_current()` (grep: zero occurrences). Two failure modes: (a) if `make_current()` returns False, the immediately following `glGenVertexArrays`/`glGenBuffers`/`glBufferData` in `_upload_arrays` execute with no current context (PyOpenGL raises, the exception escapes the idle and the whole prefetch chain stops); (b) on success the GLArea's context is left current on the main thread after the idle returns, so the next main-loop work runs with a foreign GL context bound — GTK only guarantees the context is current during `::render`.
- **Fix:** `if not self.make_current(): return False`, wrap the upload in `try/finally` and call `Gdk.GLContext.clear_current()` in the `finally` block. Better: upload the arrays in a worker thread and keep the GL calls in a dedicated `::render`-time upload queue.

#### M22. Corrupt or mismatched globe layer file raises inside the render path, with no UI note

- **File:** `frequenzradio/globe.py` line 692 (ui, correctness)
- **Problem:** `_mesh()` calls `geodata.load_layer()` and, on success, `_upload_arrays()` with no exception handling, and it is reached from `_on_render` (lines 785, 793). `load_layer` only checks `path.is_file()`, so a truncated or half-written `.npz` raises `ValueError`/`OSError` from `np.load`, and a file built with a different key set raises `KeyError` in `_upload_arrays` (line 701–703). This is reachable in practice: `build_globe` writes the layer files first and the manifest last, so interrupting `frequenz build-globe` after a previous successful build leaves the old `manifest.json` (→ `is_built()` True, globe.py:355) next to a corrupted layer file. The exception escapes the `::render` handler on every frame, the globe stays black, `gl_error` remains None, so `window._on_zoom_changed` (line 749) shows no note and the user gets a silent black rectangle plus a log flood.
- **Fix:** Wrap the load/upload in `try/except (OSError, ValueError, KeyError)`, add the key to `self._missing`, log once with the file name, and set a `self.data_error` string that `_on_zoom_changed` reports the same way it reports `gl_error`. Also make `build_globe` write each `.npz` via a temporary file + `os.replace`, and write the manifest before deleting stale layers.

#### M23. Missing GStreamer element aborts app startup with a traceback and no window

- **File:** `frequenzradio/player.py` line 50 (ui, correctness)
- **Problem:** `Player.__init__` raises `RuntimeError` when neither `playbin3` nor `playbin` is available (line 49–51). `MainWindow.__init__` constructs the player at window.py:69, inside `FrequenzApp._on_activate` (app.py:56), which has no error handling — PyGObject prints the traceback and no window ever appears. On a system where `gstreamer1-plugins-base` is missing (or a broken plugin registry makes `playbin` unloadable) the app dies silently from the user's point of view, although the globe, catalog and search would all work without audio.
- **Fix:** Catch the failure where the player is created: either wrap `MainWindow(app)` in `_on_activate` in `try/except Exception` and show an `Adw.AlertDialog` with the GStreamer package name, or let `Player` start in a `unavailable` state (`self._factory = None`) and have the window show a persistent toast/inline error while keeping browsing usable.

#### M24. Auto-skip timeout hijacks a station the user picked in the meantime

- **File:** `frequenzradio/window.py` line 719 (ui, concurrency)
- **Problem:** On a playback error the window schedules a 700 ms auto-skip with an anonymous lambda that calls `self.play_relative(1)` unconditionally. Interleaving: station A errors → `Player._emit_error` → `_on_player_state("error")` schedules the timeout at line 719; at t+200 ms the user clicks station B in the list → `play_station(B)` replaces `self.queue`/`self.queue_index`/`current_row` and starts a resolve; at t+700 ms the stale timeout fires → `play_relative(1)` uses B's fresh queue and plays the station *after* B, silently discarding the user's selection. Nothing cancels the source, and it also survives window teardown (`_on_close_request` does not remove it).
- **Fix:** Store the source id, capture the failed station id in the closure, and re-check before skipping: `if self.current_row is None or self.current_row["id"] != station_id: return GLib.SOURCE_REMOVE`. Remove the pending source in `play_station()`, `toggle_play()` and `_on_close_request()`.

#### M25. Window teardown closes the catalog under queued sync idles

- **File:** `frequenzradio/window.py` line 844 (ui, concurrency)
- **Problem:** `_on_close_request` calls `self.catalog.close()` while the background sync worker still has idles queued: `_sync_worker` posts `GLib.idle_add(self._reload_places)` (line 799) and `GLib.idle_add(self._on_sync_done, ...)` (line 805). Interleaving: first run starts the 15–20 minute sync at line 86; the user closes the window at 842 → `catalog.close()`; the queued idle then runs `_on_sync_done` → `self.catalog.stats()` (line 819) and `_reload_places()` → `self.catalog.places()` (line 375) on a closed connection → `sqlite3.ProgrammingError: Cannot operate on a closed database` raised inside the GLib main loop, plus `_on_sync_progress` writing subtitles into the destroyed window's heading. The cancel event set by `stop_background_work()` only reaches `sync_stations` between places, so it does not prevent this.
- **Fix:** Add a `self._closing = True` flag in `_on_close_request`, early-return in `_on_sync_progress`, `_on_sync_done`, `_on_resolved`, `_search_now` and the auto-skip callback when it is set; remove the pending debounce/auto-skip sources; and drop the `Catalog` reference after `close()` so any late callback fails loudly in one place instead of inside the main loop.

#### M26. Window, globe and player state machine have no automated tests

- **File:** `tests/test_player_titles.py` line 3 (ui, test-coverage)
- **Problem:** The only player test imports `clean_icy_title` (test_player_titles.py:3) and nothing constructs a `Player`. No pytest module imports `frequenzradio.window` or `frequenzradio.globe` at all — the sole references are `tests/globe_zoom_check.py` and `tests/e2e_gui_check.py`, both manual scripts that need a display and network. So every lifecycle path flagged above is untested: bus-message filtering against a discarded pipeline (player.py:189–191), the reconnect cap and back-off (218–230), `_on_resolved` token invalidation (605–610), the auto-skip timer (719), teardown (842–846), and the whole render/pick path in globe.py. `test_ui_tokens.py` even asserts the contrast of a token (`--fq-focus`) that no rule uses, which shows how far the tests are from the actual widgets.
- **Fix:** Inject the pipeline factory into `Player` so a fake Gst bus/pipeline can drive `_on_bus_message` in tests (stale-pipeline message ignored, reconnect attempts capped, error then auto-skip); add a `@pytest.mark.gui` module run under `xvfb-run` that builds a `MainWindow` with a temp catalog and asserts `_on_close_request` tears the player down, that closing during a sync raises nothing, and that the stale auto-skip cannot replace a newly selected station.

### Minor (59)

#### M1. Response body is read without any size limit (CWE-400/CWE-770)

- **File:** `frequenzradio/api.py` line 193 (core, security)
- **Problem:** `response.read()` buffers whatever the server sends. The expected /places body is ~1.9 MB, but a misbehaving or compromised upstream (or a TLS-terminating middlebox) can stream gigabytes and exhaust the desktop app's memory. There is no Content-Length check and no cap.
- **Fix:** Reject Content-Length above a configured maximum and read at most that many bytes (`response.read(MAX_BODY)`), raising ApiError when the cap is hit.

#### M2. 429 retries ignore Retry-After

- **File:** `frequenzradio/api.py` line 197 (core, error-handling)
- **Problem:** RETRYABLE_STATUS includes 429, but the retry path only uses fixed exponential backoff (line 204) and drops the Retry-After header. Against a rate-limited API this either retries too fast (more 429s) or too slowly, for every one of ~2000 places.
- **Fix:** Parse `exc.headers.get("Retry-After")` (delta-seconds or HTTP-date), clamp it to a sane maximum, and sleep max(backoff, retry_after).

#### M3. get_json leaks ValueError/AttributeError instead of ApiError

- **File:** `frequenzradio/api.py` line 208 (core, error-handling)
- **Problem:** `json.loads(body.decode("utf-8"))` raises JSONDecodeError (a ValueError) for an HTML/CDN error page returned with 200, and a JSON array or scalar passes through and then fails with AttributeError in parse_places/parse_place_channels. Callers handle ApiError, so these surface as raw tracebacks (the GUI only survives because window.py:598 catches Exception broadly).
- **Fix:** Wrap decode + json.loads in try/except (UnicodeDecodeError, ValueError) and raise ApiError(f"invalid JSON from {path}"); assert isinstance(payload, dict) and raise ApiError otherwise.

#### M4. Remote-supplied ids are interpolated into request URLs unquoted (CWE-22)

- **File:** `frequenzradio/api.py` line 215 (core, security)
- **Problem:** place_id comes from the payload (`raw["id"]`) and station ids come from the last path segment of the remote page URL (line 109); both are concatenated into request paths here and in Station.listen_path (line 75) with no quoting or charset validation. An id containing '/', '?', '#' or '../../' changes which endpoint is requested on radio.garden.
- **Fix:** Quote with `urllib.parse.quote(value, safe="")` and validate ids against `^[A-Za-z0-9_-]+$` when parsing; skip entries that do not match.

#### M5. Redirect target from remote data is used without scheme/host validation (CWE-939)

- **File:** `frequenzradio/api.py` line 228 (core, security)
- **Problem:** resolve_stream returns whatever Location the server sent, resolved against BASE_URL, and window.py:609 passes it straight to player.load() -> playbin. A compromised or hijacked listen endpoint can hand back file:///... or an arbitrary third-party http(s) host, which GStreamer will happily open, turning app playback into a local-file probe or an IP leak to an unrelated host.
- **Fix:** In resolve_stream, parse the joined URL and return it only if scheme in {"http", "https"} (optionally also compare the host against an allowlist); otherwise return None so the caller falls back to the listen URL.

#### M6. Rows that disappear upstream are never removed

- **File:** `frequenzradio/catalog.py` line 183 (core, correctness)
- **Problem:** save_place_stations only upserts; stations removed from a place (or the whole place removed from /places in upsert_places) linger in the DB forever. After a --full sync, search and random_station still return dead stations and the globe still shows dead places, with no way to tell them apart.
- **Fix:** Delete stations of the place whose ids are not in the fetched payload (inside the same transaction), and reconcile places against the fetched id set (or add an `active`/`seen_at` column and filter reads).

#### M7. Long batch transactions block main-thread writes in the GUI

- **File:** `frequenzradio/catalog.py` line 185 (core, concurrency)
- **Problem:** The whole batch (up to batch_size=100 places, each with all its stations plus FTS trigger writes) is one transaction. The GUI writes favorites/history from GTK signal handlers on the main thread using a different connection (window.py:458, 573) with timeout=10.0, so those writes block until the batch commits; on a lock timeout the OperationalError is raised inside the signal handler. Combined with the 0.29 s index rebuild, this is a visible hitch during every catalog update.
- **Fix:** Commit per place (or per few hundred stations), keep interactive writes off the main thread or use a short busy_timeout plus a retry for them, and avoid holding a single transaction for an entire batch.

#### M8. A place is marked synced even when zero stations were parsed

- **File:** `frequenzradio/catalog.py` line 211 (core, correctness)
- **Problem:** channels_synced=1 is set unconditionally after the loop, including when parse_place_channels returned an empty list because the remote schema changed (content/items/page renamed) or the response was truncated. The place is then permanently considered done and shows up empty, and no failure is recorded anywhere. The payload even carries `places.size`, the expected station count, which is never checked against.
- **Fix:** Pass the expected size (or the place id lookup) into save_place_stations and treat `expected > 0 and not stations` as a failure: do not set channels_synced, append to report.failures.

#### M9. Negative limit means unlimited in SQLite

- **File:** `frequenzradio/catalog.py` line 303 (core, correctness)
- **Problem:** `int(limit)` is bound directly to LIMIT. Verified: `LIMIT -1` returns every row, and the CLI accepts `frequenz search q --limit -1` (cli.py:39) with no validation, dumping the whole catalog; `--limit 0` silently returns nothing.
- **Fix:** Clamp in search(): `limit = max(0, min(int(limit), 1000))`, and/or validate with `type=positive_int` in argparse.

#### M10. No top-level error handling: offline or corrupt-DB runs print a traceback

- **File:** `frequenzradio/cli.py` line 76 (core, error-handling)
- **Problem:** ApiError from sync_places (no network/DNS is the most common first-run case), sqlite3.DatabaseError from Catalog() on a corrupt file, and OSError from catalog_path()/mkdir all escape main() as Python tracebacks. main() already returns int exit codes, so the contract exists but is bypassed for every expected failure mode.
- **Fix:** Catch (ApiError, sqlite3.Error, OSError) in main(), print one actionable line to stderr (e.g. 'cannot reach radio.garden: <reason>; check your connection'), return 1; keep -v for the traceback.

#### M11. Catalog is not closed on early return or on exception

- **File:** `frequenzradio/cli.py` line 90 (core, error-handling)
- **Problem:** `--places-only` returns here without catalog.close(); the normal path closes at line 123 but also not in a finally, so an ApiError from sync_places, a KeyboardInterrupt during the loop, or a sqlite3 error leaves the connection open and the WAL uncheckpointed. The process exits anyway, but nothing guarantees the files are tidy, and the GUI/CLI pattern is copied elsewhere.
- **Fix:** Wrap the command body in try/finally with `catalog.close()` (or use `contextlib.closing`).

#### M12. Cancelled sync exits 0

- **File:** `frequenzradio/cli.py` line 124 (core, correctness)
- **Problem:** Ctrl-C sets the cancel event (line 82), sync_stations returns report.cancelled=True, and this returns 0 when there were no individual failures. A wrapper script running `frequenz sync && ...` cannot tell an interrupted, partial catalog from a complete one. The conventional code for SIGINT is 130.
- **Fix:** `return 130 if report.cancelled else (1 if report.places_failed else 0)`.

#### M13. FREQUENZ_CATALOG is trusted as-is

- **File:** `frequenzradio/paths.py` line 21 (core, error-handling)
- **Problem:** The override is expanded but never validated: pointing it at a directory, or at a path whose parent cannot be created, makes sqlite3.connect fail later with 'unable to open database file' from every command, with no mention of the environment variable.
- **Fix:** Check `not path.is_dir()` and create the parent (or raise a clear ValueError naming FREQUENZ_CATALOG) in catalog_path().

#### M14. state_path() sits outside the try, so load() can raise despite its fallback contract

- **File:** `frequenzradio/state.py` line 30 (core, error-handling)
- **Problem:** state_path() calls data_dir(), which does mkdir(parents=True, exist_ok=True) and can raise OSError (read-only or full filesystem, XDG_DATA_HOME pointing at a file, NFS home). Verified: load() raises NotADirectoryError instead of returning defaults, and because this happens during MainWindow.__init__ (window.py:49) the app dies before showing anything rather than starting with default settings.
- **Fix:** Move `path = state_path()` inside the try block (or wrap it in its own try/except OSError returning cls()).

#### M15. State fields are accepted with arbitrary types and NaN

- **File:** `frequenzradio/state.py` line 33 (core, robustness)
- **Problem:** Only unknown keys are filtered; values are not validated. Verified: AppState(**{"volume": "loud", "dist": None, "auto_rotate": "yes"}) constructs fine, so a hand-edited or half-migrated state.json feeds a string to player.set_volume and None into the globe's camera math (blank/no-render with no error). json.loads also accepts NaN, and save() then writes `NaN`, which is not valid strict JSON for any other tool.
- **Fix:** Coerce per field on load: floats via `float(v)` + `math.isfinite`, clamp volume to 0..1 and dist/pitch to sane ranges, booleans via `isinstance(v, bool)`, and drop values that fail. Use `json.dumps(..., allow_nan=False)` on save so bad values fail loudly instead of being persisted.

#### M16. state.json is written non-atomically

- **File:** `frequenzradio/state.py` line 42 (core, correctness)
- **Problem:** write_text() truncates the existing file and rewrites it in place. A crash, SIGKILL or power loss mid-write leaves a truncated/empty state.json; load() then falls back to defaults, silently losing last_station, theme, palette and view. The file is small and rewritten on several actions, so the window is small but real.
- **Fix:** Write to a temp file in the same directory, flush + os.fsync, then os.replace(tmp, final); fsync the directory if you want durability across power loss.

#### M17. Two syncs can run against the same catalog (GUI + CLI) with no lock

- **File:** `frequenzradio/sync.py` line 55 (core, concurrency)
- **Problem:** Nothing prevents the desktop app's background sync (window.py:795) and a terminal `frequenz sync` from running at once. Both issue the full request stream and both write: SQLite serialises them, but the losing writer waits up to the 10 s busy timeout (catalog.py:124) and then raises 'database is locked' into the middle of a batch, which (see sync.py:85) aborts that run.
- **Fix:** Take an advisory lock before syncing (flock on `<data_dir>/sync.lock`, or a `sync_owner` meta row with pid+timestamp) and exit with a clear message when another sync holds it.

#### M18. Cancelled sync leaves worker threads running after it returns

- **File:** `frequenzradio/sync.py` line 90 (core, concurrency)
- **Problem:** On cancellation `pool.shutdown(wait=False, cancel_futures=True)` returns immediately, so up to `workers` requests continue after sync_stations returns. The GUI's _sync_worker then closes its Catalog and exits, the 'already updating' guard (window.py:785) sees a dead thread, and the user can start a second sync while the first run's orphans are still hitting the API. Cancellation is also only observed when a future completes, so the flag can sit unnoticed for the length of the slowest in-flight request.
- **Fix:** Have `fetch` check the cancel event before starting the request, and join with a short bounded timeout in the finally (`pool.shutdown(wait=True, cancel_futures=True)` with a deadline) so the call does not return while work is outstanding.

#### M19. Full FTS rebuild after every sync, although triggers already maintain it

- **File:** `frequenzradio/sync.py` line 93 (core, performance)
- **Problem:** rebuild_search_index() deletes and rewrites the whole FTS table on every run, even an incremental one that saved a single place; catalog.py:236 itself calls this 'a repair tool: the triggers keep it current'. Measured on a 30k-station catalog: 0.29 s per rebuild, holding the write lock in the sync thread while the GTK main thread's set_favorite/record_play writes (window.py:458/573) wait on the same lock.
- **Fix:** Remove the unconditional call (triggers keep the index current) or restrict it to `full=True` / explicit repair. If it stays, run it once after the loop only when a bulk import actually happened.

#### M20. mark_synced() records success even when places failed

- **File:** `frequenzradio/sync.py` line 95 (core, correctness)
- **Problem:** mark_synced() runs whenever the run was not cancelled, regardless of report.places_failed. A run where 39 of 40 places returned 500 still writes last_sync_at=now, so `frequenz stats` and the doctor report a fresh sync over a catalog that is mostly stale.
- **Fix:** Only call mark_synced() when report.places_failed == 0, or store a separate `last_sync_failures` meta value and display both.

#### M21. Lone surrogates are not filtered and break the sqlite bind

- **File:** `frequenzradio/text.py` line 30 (core, correctness)
- **Problem:** Only Cf and Cc are handled. json.loads accepts \ud800-style escapes, producing a Cs character that survives clean_text. Verified: binding such a title raises UnicodeEncodeError('surrogates not allowed'), which fails the station upsert and (via catalog.py:185) the whole batch, permanently, on every retry.
- **Fix:** Extend the filter to `if category == "Cs": continue` (and optionally reject U+FFFE/U+FFFF); the value then degrades to the cleaned/fallback title instead of breaking the write.

#### M22. Failure tests only cover HTTP errors, not write/parse failures or CLI exit codes

- **File:** `tests/test_sync_client.py` line 113 (core, test-coverage)
- **Problem:** The resumability test injects a 500 from the fake server, so the isolated path is exercised, but nothing covers a failing catalog write (the unisolated path at sync.py:85), a malformed /places entry (api.py:92), a corrupt catalog in doctor, cancelled-sync exit codes, or AppState with wrong-typed fields. test_api.py:15 only feeds well-formed fixtures, which is why the ValueError above ships untested.
- **Fix:** Add: (a) a fixture entry with geo ["n/a", 0] that must be skipped, (b) a Catalog stub whose save_place_stations raises for one place, asserting the run continues and the other places are saved, (c) a CLI test asserting exit 130 on cancel and 1 on ApiError, (d) a state test with volume/dist of the wrong type.

#### M23. README claims Ubuntu 24.04 support and never mentions Fedora, but it is the RPM's only documentation

- **File:** `README.md` line 28 (packaging, docs)
- **Problem:** README.md:28 says 'Ubuntu 24.04 or later', while packaging/debian/README.md:3 says 'Target: Ubuntu 26.04 LTS … Other releases are not built or tested' and :15 lists 24.04 as not verified. The README also contains no Fedora/RPM install path at all, yet it is the only file installed as %doc in the RPM (frequenz.spec:68), so a Fedora user reading the shipped documentation is told to `sudo apt install`.
- **Fix:** State the actually supported matrix (Fedora 45, Ubuntu 26.04, Flatpak) with one install command per format, and move the venv-from-source instructions under a 'development' heading. Say 24.04 is untested, or test it.

#### M24. OpenGL requirement understated: the shaders need GL 3.3 core, not 3.0

- **File:** `README.md` line 35 (packaging, docs)
- **Problem:** README.md:35 promises 'OpenGL 3.0+', but every desktop shader in frequenzradio/globe.py is `#version 330 core` (globe.py:70, 81, 138, 149, 162, 170, 188, 228) with a `#version 300 es` fallback (globe.py:316). A GL 3.0/3.1 driver cannot compile the desktop path, and the user would see the '3D globe unavailable' fallback on hardware the README said was supported.
- **Fix:** Say 'OpenGL 3.3 core (or OpenGL ES 3.0 through EGL)'. README.md:164 already says 'OpenGL 3.0/3.3'; make both lines consistent with the shaders.

#### M25. build-globe download size conflicts within the README (50 MB vs 31 MB)

- **File:** `README.md` line 46 (packaging, docs)
- **Problem:** The install block says 'about 50 MB download' (README.md:46) while the Globe section says 'about 31 MB of Natural Earth files' (README.md:80). One of the two is wrong, and this number is the user's only warning before a long first-run download.
- **Fix:** Measure the download once (`du -sh ~/.local/share/frequenz/naturalearth` after a fresh build) and use one figure in both places.

#### M26. Request rate claim does not match the CLI default

- **File:** `README.md` line 57 (packaging, docs)
- **Problem:** README.md:57 says 'throttled to roughly 10 per second across four workers'. The CLI default is `--min-interval 0.05` shared across workers (cli.py:28-29), i.e. ~20 requests/second; only the GUI worker uses 0.1 (window.py:797). A README that overstates politeness by 2x is the kind of claim that gets quoted back at you if radio.garden complains.
- **Fix:** Set the CLI default to 0.1 (matching the GUI and the docs), or document '10/s in the app, 20/s with the CLI default'.

#### M27. README documents a sync.log file that nothing writes

- **File:** `README.md` line 125 (packaging, docs)
- **Problem:** The local-data list mentions `sync.log`, but no module opens or writes it (grep for sync.log/sync_log across frequenzradio finds nothing; the only file writes are state.json, catalog.sqlite and the globe manifest). Troubleshooting advice that points at a non-existent log wastes the user's time.
- **Fix:** Either remove `sync.log` from the README, or add a logging FileHandler in cli._cmd_sync and the GUI sync worker so sync progress is actually recorded.

#### M28. README documents a station-detail endpoint request that the app never makes

- **File:** `README.md` line 130 (packaging, docs)
- **Problem:** README.md:130 says requests go to 'the station detail endpoint', and :161 lists 'station details' as catalog functionality, but RadioGardenClient.station_detail (api.py:217) and Catalog.station_detail/save_station_detail (catalog.py:372, 381) have no caller in the UI or CLI (grep across frequenzradio shows definitions only). The feature is dead code that is nevertheless covered by tests (test_sync_client.py:107, test_catalog.py:93), which inflates the coverage picture.
- **Fix:** Either wire the detail fetch into the now-playing card/about area (with caching and an offline fallback) or delete the unused API/catalog methods, their tests and the README sentence before 1.0.

#### M29. User-Agent still identifies as Frequenz/0.1

- **File:** `frequenzradio/api.py` line 30 (packaging, correctness)
- **Problem:** Both USER_AGENT constants end in `Frequenz/0.1` (api.py:30 and player.py:27) while the package is 0.2.1. The README makes a point of the identifying UA (README.md:132-133), and the server operator's only way to attribute traffic will report the wrong version — and won't change when 1.0 ships.
- **Fix:** Build the string from `__version__` in one place (e.g. `frequenzradio.text`/`api.USER_AGENT = f'... Frequenz/{__version__}'`) and import it in player.py.

#### M30. Network-error retry path and resolve_stream's no-redirect branch are untested

- **File:** `frequenzradio/api.py` line 199 (packaging, tests)
- **Problem:** The tests only exercise HTTP 429/500 through the fake server (min_interval=0.0 everywhere). Untested: the URLError/OSError retry-and-give-up path (api.py:199-201), the throttle sleep with min_interval > 0 (api.py:173-180) even though thread-safety is a documented claim, `resolve_stream` returning None when the redirect has no Location (api.py:225-229), and `get_json` on a non-JSON body (api.py:208).
- **Fix:** Add a test with a closed port to hit the URLError path, a `min_interval=0.05` test asserting the elapsed time across two calls, a redirect-without-Location handler and a text/plain payload for get_json.

#### M31. schema_version is advanced before the migration, and a downgrade silently clobbers it

- **File:** `frequenzradio/catalog.py` line 130 (packaging, correctness)
- **Problem:** `previous = get_meta(...)` then `set_meta('schema_version', SCHEMA_VERSION)` happens before `_clean_existing_metadata()`/`rebuild_search_index()`. If the migration raises (disk full, corrupt row), the DB is already marked as the new version and the repair never runs again. Conversely, any `previous != SCHEMA_VERSION` — including a newer catalog opened by an older build during a downgrade — triggers a rebuild and rewrites the version downwards. Not covered by tests (only the 2→3 and 1→3 upgrade paths are).
- **Fix:** Run the migration first and set the version afterwards in the same transaction; compare numerically (`previous is None or int(previous) < int(SCHEMA_VERSION)`), and refuse/log when previous > current. Add a test that a failing migration leaves the old version and one for a future version.

#### M32. Changelog distribution is `unstable` for an Ubuntu 26.04 package

- **File:** `packaging/debian/changelog (origin/ubuntu-deb)` line 1 (packaging, packaging-debian)
- **Problem:** Every entry targets `unstable`, the Debian suite, while packaging/debian/README.md:3 says the target is Ubuntu 26.04 LTS (Resolute Raccoon). Any .changes produced by dpkg-buildpackage will be addressed to the wrong suite, so a dput/Launchpad upload is rejected and `dch -r` reports the wrong target.
- **Fix:** Change the distribution of each entry to the 26.04 suite (`resolute`) — or keep 0.2.1 as-is and use `dch --release --distribution=resolute` for the stable cut — and add `debian/changelog` distribution to the release checklist.

#### M33. override_dh_auto_test ignores DEB_BUILD_OPTIONS=nocheck

- **File:** `packaging/debian/rules (origin/ubuntu-deb)` line 6 (packaging, packaging-debian)
- **Problem:** Because the test step is fully overridden, `DEB_BUILD_OPTIONS=nocheck` no longer skips it, unlike every dh-maintained package. Builders and backporters that pass nocheck (and environments without a writable HOME, see the test_globe_data finding) will still run pytest and fail the build.
- **Fix:** Guard the body: `ifeq (,$(filter nocheck,$(DEB_BUILD_OPTIONS)))` … `endif`, and keep desktop-file-validate inside it or move it to dh_auto_install.

#### M34. Source0 is a bare filename with no fetchable URL

- **File:** `packaging/fedora/frequenz.spec` line 15 (packaging, packaging-rpm)
- **Problem:** `Source0: %{srcname}-%{version}.tar.gz` has no URL, so rpmbuild cannot fetch it and `spectool -g` cannot regenerate it; the tarball only exists because verify-in-fedora.sh creates it from the working tree. Fedora review expects a resolvable Source or a documented `%forgemeta`/`Source0` generation step. The same applies to the private `URL:` on line 14, which is already listed as an open item.
- **Fix:** Once the repo is public, use a release-tarball URL (or %forgemeta). Until then add a comment with the exact `git archive`/verify-in-fedora.sh command that produces Source0, and publish the tarball with the release so the SRPM is reproducible.

#### M35. Fedora-only remediation in a cross-distro install script

- **File:** `scripts/install-desktop.sh` line 74 (packaging, install-script)
- **Problem:** When python3 is missing the script tells the user `sudo dnf install python3`, but the README's primary install path is Ubuntu, where the missing piece is usually python3-venv (`python3 -m venv` fails with 'ensurepip is not available'). The same script also silently assumes `pip` exists in the new venv.
- **Fix:** Detect the package manager (dnf/apt) and print the right command, and check for the venv module explicitly: after `-m venv` fails, suggest `sudo apt install python3-venv` on Debian/Ubuntu.

#### M36. --repair installs the build and test extras into the user's runtime venv

- **File:** `scripts/install-desktop.sh` line 85 (packaging, install-script)
- **Problem:** `pip install -e '.[build,test]'` pulls shapely and pytest (plus their deps) on every repair, requires network access at repair time, and leaves a test framework in the venv the desktop launcher uses. A repair for an offline or freshly upgraded machine — the exact scenario the script exists for — will fail at this step.
- **Fix:** Install `.[build]` (the globe builder is a documented feature) or plain `.` and tell the user to install `.[test]` only if they run the tests; make the pip step's failure message point at the network/pip log.

#### M37. Assertion does not test what the test name claims

- **File:** `tests/test_globe_build.py` line 63 (packaging, tests)
- **Problem:** test_line_segments_join_only_points_of_the_same_line asserts `np.allclose(np.linalg.norm(segments[:, 0, :] * [1, 1, 1], axis=1) > 0.9, True)`, i.e. only that segment start points lie on the unit sphere (the multiply by [1,1,1] is a no-op, and allclose against True is a convoluted np.all). Nothing checks the join/grouping behaviour in the name: a regression that connected a point of one LineString to a point of another would still pass.
- **Fix:** Assert the actual grouping — e.g. compare the exact expected segment endpoints for the fixture (`segments[:, :, :2]` equals the expected coordinate pairs) and assert the count per input line — and write the sphere check as `assert np.all(np.linalg.norm(...) > 0.9)`.

#### M38. Collection-time call creates the real user data dir and makes the pass/skip set machine-dependent

- **File:** `tests/test_globe_data.py` line 11 (packaging, tests)
- **Problem:** `BUILT = geodata.is_built(globe_dir())` runs at import, and paths.globe_dir() calls mkdir on $XDG_DATA_HOME/frequenz/globe. So merely collecting tests writes into the user's home (and in a clean chroot with an unwritable HOME this raises during collection, failing %check or dh_auto_test). It also makes results environment-dependent: 154 passed locally with the map built vs the 15 skips recorded in packaging/fedora/README.md:45 for a clean container — the same commit reports different numbers depending on the builder's home directory.
- **Fix:** Resolve the directory lazily inside a fixture and honour XDG_DATA_HOME (or FREQUENZ_DATA_HOME) set to tmp_path, so the suite never touches $HOME and the skip set is decided by an explicit env var/marker rather than by what the developer has built.

#### M39. Give-up test asserts the exception but not the retry count

- **File:** `tests/test_sync_client.py` line 94 (packaging, tests)
- **Problem:** test_persistent_server_error_raises_after_retries only does `with pytest.raises(ApiError)`. It would still pass if _open gave up after the first attempt, so the bounded-retry contract (max_retries=3 ⇒ 4 attempts, api.py:197-202) is not pinned. The 429 test does count attempts, the 500 path does not.
- **Fix:** Count hits on the failing path like the 429 test does and assert exactly max_retries+1 attempts; add a case for a non-retryable status (404) asserting a single attempt.

#### M40. Cancellation test cannot distinguish 'cancelled mid-run' from 'did nothing'

- **File:** `tests/test_sync_client.py` line 147 (packaging, tests)
- **Problem:** test_sync_can_be_cancelled_before_all_places_finish sets the cancel event before sync_stations is called, so the loop breaks on its first iteration and the assertions (`places_done + places_failed < places_total`) hold even if the code never checked the event inside the loop. Also unasserted anywhere: that `catalog.mark_synced()` is skipped on cancel (sync.py:94-95), the `limit` and `full=True` paths, the batch_size flush at sync.py:84, and the progress callback that only fires every 25 places (sync.py:87).
- **Fix:** Set the event from the progress callback or a server-side hook after N places, then assert a partial count and that `last_sync_at` is still unset; add a test with batch_size=1 to cover the mid-loop flush and one with limit=2 to cover the LIMIT path.

#### M41. Focus token is defined and contrast-tested but never used; custom buttons have no focus-visible rule

- **File:** `frequenzradio/data/style.css` line 29 (ui, accessibility)
- **Problem:** `--fq-focus` is defined in both themes (style.css:29 and 51) and `test_ui_tokens.py:31–37` asserts its 3:1 contrast against `app-bg` and `surface`, but no rule in the stylesheet uses it: `grep` finds zero `var(--fq-focus)` and zero `:focus`/`:focus-visible` rules in the whole 429-line file. The controls that need a ring most are the ones whose styling is overridden: `.fq-rail-item` (141–144), `.fq-row-play` (255–261) and `button.rg-play` (315–324), which explicitly sets `box-shadow: none` and a custom background. Focus visibility on those buttons therefore depends entirely on libadwaita defaults that these rules can suppress, and the token test gives false confidence.
- **Fix:** Add explicit rules, e.g. `.fq-rail-item:focus-visible, .fq-row-play:focus-visible, button.rg-play:focus-visible { outline: 2px solid var(--fq-focus); outline-offset: 2px; }` (and for the lime-filled controls use `--fq-on-accent` so the ring stays visible), plus a test asserting every interactive class in the CSS has a focus rule.

#### M42. is_built() trusts any manifest.json and never validates schema or layer files

- **File:** `frequenzradio/geodata.py` line 63 (ui, correctness)
- **Problem:** `is_built` only tests `(globe_dir / "manifest.json").is_file()` (lines 63–64). It never compares `manifest["schema"]` with `SCHEMA`, never checks that the layers listed in the manifest still exist, and never verifies the recorded sizes/checksums. A manifest written by an older build, or a directory where the user deleted the `.npz` files, is reported as ready: `GlobeView.vector_map_ready` becomes True so the "run frequenz build-globe" note never appears (window.py:751–752), while the viewer silently draws only the ocean — or raises in the render path if the files are corrupt (see the render-path finding).
- **Fix:** Parse the manifest and return False (with a reason) when `manifest.get("schema") != SCHEMA`, when any `SOURCE` layer/lod file is missing, or when a file's `stat().st_size` differs from `manifest["layers"][name]["bytes"]`; surface that reason in the globe note.

#### M43. Desktop context is requested at 3.0 but the shaders require GLSL 330

- **File:** `frequenzradio/globe.py` line 349 (ui, correctness)
- **Problem:** `set_required_version(3, 0)` (line 349) asks GTK for a 3.0 context, but the desktop shaders are `#version 330 core` (SURFACE_VS line 70, LINE_VS 138, HALO_VS 161, POINTS_VS 187); only the GLES path is 3.0 (`#version 300 es`, line 316). A driver that honours the requested version exactly gives a 3.0 context whose GLSL version is 1.30, so `_compile` fails inside `_setup_gl`, the exception is caught at line 620, and the window then reports "3D globe unavailable: no usable OpenGL context" (window.py:750) — a misleading diagnosis for a shader/version mismatch, with the real cause only in the log.
- **Fix:** Request `(3, 3)` when the context is not GLES (GTK returns a higher version when available, and the ES path already documents 3.0), and include `self.gl_error` verbatim in the note so a shader failure is not reported as a missing context.

#### M44. Double-click zoom turns auto-rotate off behind the UI's back and rewrites the saved setting

- **File:** `frequenzradio/globe.py` line 433 (ui, correctness)
- **Problem:** `focus_place` sets `self.auto_rotate = False` (line 433) whenever it is called — that is every double-click on a dot (`_zoom_to_index`, 560–564) and every random station (window.py:677). The window is never told: `set_auto_rotate()` (window.py:775) does not run, so `state.auto_rotate` keeps its old value, the Preferences switch still shows ON (preferences.py:45 reads `window.globe.auto_rotate` only when the window is built), and 10 s later `_persist_view` (window.py:834) silently writes `auto_rotate = False` to disk. The user's saved preference flips without any UI action.
- **Fix:** Do not mutate the preference in `focus_place`; instead pause rotation with a separate transient flag (`self._auto_rotate_paused_until = time.monotonic() + 6`), or add an `on_auto_rotate` callback that the window wires to `set_auto_rotate` so state, the switch and the globe stay consistent.

#### M45. Double-click on a place also tunes in, because the first release already selects

- **File:** `frequenzradio/globe.py` line 514 (ui, correctness)
- **Problem:** `Gtk.GestureClick` emits `released` with `n_press = 1` for the first click of a double-click, so `_on_click` calls `_on_select(index)` (line 519) before the second release reaches the `n_press >= 2` branch (514) that zooms. Double-clicking a dot therefore starts playback *and* zooms, contradicting the documented behaviour ("Click a dot — tune in; double-click — zoom to the place", window.py:865) and the `on_focus` callback the window wires as a no-op (window.py:100, 516–517).
- **Fix:** Defer selection: on `n_press == 1` start a ~250 ms `GLib.timeout_add` that selects only if no second press arrives; cancel it in the `n_press >= 2` branch. Drop the unused `_on_focus` path or use it for the zoom acknowledgement.

#### M46. Picking allocates a float64 copy of the place weights on every mouse-motion event

- **File:** `frequenzradio/globe.py` line 557 (ui, performance)
- **Problem:** `_pick` is called from `_on_motion` for every pointer-motion event (line 526) and passes `self.places.counts.astype(np.float64)`, allocating a fresh N-element float64 array per event (N is the full place count, thousands of entries) on top of the allocations inside `geo.project` (`np.ones((N, 1))`, `np.stack`). On a touchpad at ~125 Hz this is continuous garbage generation while the cursor merely moves over the globe.
- **Fix:** Precompute `self._pick_weights = places.counts.astype(np.float64)` once in `set_places()` and pass that array; ideally also cache the projected screen positions per (yaw, pitch, dist) so a motion that does not move the camera does not re-project at all.

#### M47. Unrealize drops mesh and program handles without deleting them; no glDelete* exists

- **File:** `frequenzradio/globe.py` line 672 (ui, performance)
- **Problem:** `_on_unrealize` throws away `self._meshes`, `_base` and the prefetch queue (lines 672–676) without deleting the GL objects, and `_setup_gl` then compiles four new programs and generates new VAOs/VBOs on every realize (628–657). There is no `glDeleteProgram`, `glDeleteVertexArrays` or `glDeleteBuffers` anywhere in the package, and `_Mesh` (304–307) stores only `vao`, `count` and `indexed`, so the VBO/EBO names created in `_upload_triangles` (709–722) are unreachable and can never be freed even in principle. As long as the GdkGLContext survives (shared context, or a re-realize on the same surface), every realize leaks four programs and the meshes that were resident.
- **Fix:** Delete the programs and buffers in `_on_unrealize` while the context is still current (`glDeleteVertexArrays`/`glDeleteBuffers`/`glDeleteProgram`), and keep the VBO/EBO numbers in `_Mesh` so a mesh can be released when it is evicted. Guard the reads with `self._gl_ready`.

#### M48. A dead station blocks the queue for ~25 s before the auto-skip

- **File:** `frequenzradio/player.py` line 33 (ui, performance)
- **Problem:** A dead stream takes a long time to fail and hand over to the next station: `SOURCE_TIMEOUT_S = 20` (line 33) is applied to souphttpsrc (line 186–187), then `_handle_failure` retries twice with 1500 ms and 3000 ms back-off (lines 222–227), and only after ~24.5 s does the player emit `error`, after which the window waits another 700 ms (window.py:719) before skipping. During all of that the bar shows CONNECTING with no cancel affordance other than pause/next. The comment at line 181 still claims "a dead station should fail in ~12 s", so the constant and its documentation have drifted apart.
- **Fix:** Lower the source timeout to ~10–12 s to match the comment, make the first reconnect immediate (0 ms) and the second short (1 s), and expose a "Skip" action in the CONNECTING toast so the user is not forced to wait for the full budget.

#### M49. Server-supplied redirect target is passed to playbin without scheme validation

- **File:** `frequenzradio/player.py` line 69 (ui, security)
- **Problem:** The stream URI handed to GStreamer is whatever the API's redirect says: `RadioGardenClient.resolve_stream` joins the server's `Location` header with the base URL (api.py:221–229) without checking the scheme or host, and `Player.load` passes it straight to `playbin3` as the `uri` property (line 69–76, `_start` line 161). `playbin` will happily open any registered protocol, including `file://` and `ftp://`, so a compromised or spoofed API response, or a hostile station redirect, can make the app open local files (or devices) through GStreamer and probe their contents through the audio path, instead of only stream HTTP(S) audio.
- **Fix:** Validate before loading: parse with `urllib.parse.urlsplit`, require `scheme in {"http", "https"}` and a non-empty host, otherwise fall back to the constructed `listen` URL; log the rejected URI. Doing the check in `Player.load` also covers future callers.

#### M50. Forced colour scheme and USER-priority CSS override the system high-contrast theme

- **File:** `frequenzradio/theme.py` line 35 (ui, accessibility)
- **Problem:** `apply_scheme` always sets `Adw.ColorScheme.FORCE_LIGHT` or `FORCE_DARK` (theme.py:35) and `_on_startup` installs the app stylesheet at `Gtk.STYLE_PROVIDER_PRIORITY_USER` (app.py:38), above the GTK/Adwaita theme priority. The app therefore ignores two system accessibility affordances: `Adw.StyleManager`'s high-contrast state (never queried anywhere in the package) and the system accent/high-contrast theme, because the hard-coded `fq-dark`/`fq-light` token blocks always win. A user who runs GNOME's High Contrast theme gets the normal-contrast palette.
- **Fix:** Read `Adw.StyleManager.get_default().get_high_contrast()` and, when set, add a `fq-high-contrast` class with token blocks that meet 7:1 for text and 4.5:1 for non-text; keep the forced scheme for the app's own look but do not override the theme at `PRIORITY_USER` for widget-level colours (scope the overrides to the window classes as the file already does).

#### M51. State is rewritten to disk every 10 s unconditionally, non-atomically

- **File:** `frequenzradio/window.py` line 79 (ui, performance)
- **Problem:** `GLib.timeout_add_seconds(10, self._persist_view)` (line 79) runs forever and every tick serialises the whole dataclass and rewrites `state.json` (lines 830–836, state.py:40–44) whether or not anything changed; `set_theme_name` (317) and `set_globe_palette` (773) also write synchronously from a click handler. The write is a plain `write_text` with no temp-file/rename, so a crash or power loss mid-write leaves truncated JSON; `AppState.load` then falls back to `AppState()` (state.py:34) and the user silently loses theme, palette and last station.
- **Fix:** Keep a `self._saved_snapshot` tuple, skip the write when nothing changed, and make `AppState.save()` atomic (`path.with_suffix('.tmp')` + `os.replace`). Consider saving on change (debounced) instead of polling.

#### M52. Malformed state.json values crash MainWindow construction

- **File:** `frequenzradio/window.py` line 103 (ui, correctness)
- **Problem:** `AppState.load` filters unknown keys but does not validate types (state.py:31–38), and the window uses the values unchecked: `self.player.set_volume(self.state.volume)` (window.py:73) evaluates `max(0.0, min(1.0, "loud"))` → TypeError for a string, and `geo.clamp_distance(self.state.dist)` (window.py:104) raises TypeError for `"dist": "3.5"`. Both happen inside `MainWindow.__init__` during `activate`, with no handler, so a hand-edited or partially migrated `state.json` makes the app fail to start with a traceback until the file is deleted. `tests/test_state.py:47` only covers invalid JSON, not valid JSON with wrong-typed values.
- **Fix:** Coerce in `AppState.load` (`volume = min(1.0, max(0.0, float(volume)))`, `dist`/`yaw`/`pitch` via `float()` with a fallback to the default) and clamp `pitch` to ±`geo.MAX_PITCH` where the globe is initialised (line 103 currently clamps only `dist`).

#### M53. Zoom and volume sliders have no accessible name or meaningful value

- **File:** `frequenzradio/window.py` line 222 (ui, accessibility)
- **Problem:** Both scales are created without any accessible name and report a raw 0..1 value with `set_draw_value(False)`: the zoom scale (lines 222–229) and the volume scale (lines 285–289). `set_tooltip_text` (line 226) is not an accessible name in GTK4, so a screen reader announces "slider, 0.5" with no indication of what it controls or what the value means (zoom has a distance/percentage meaning, volume is 0–100 %). Neither scale sets `Gtk.AccessibleValue` text or marks, and neither is reachable by a labelled control.
- **Fix:** Set explicit labels and value text: `scale.update_property([Gtk.AccessibleProperty.LABEL], ["Zoom"])`, `Gtk.AccessibleProperty.VALUE_TEXT` on each `value-changed` ("2 000 km", "50 %"), and for zoom add `Gtk.Scale.add_mark` at the six `geo.ZOOM_LEVELS` so the slider is not a bare 0–1 range.

#### M54. Play/pause button never announces whether it will play or pause

- **File:** `frequenzradio/window.py` line 268 (ui, accessibility)
- **Problem:** `_on_player_state` swaps only the icon of the primary button (line 710) while `tooltip_text` stays "Play / pause (Space)" from construction (line 268). A screen-reader user cannot tell whether pressing the button will start or stop audio, and the only other state indicator is the visual pill in `LiveCard.set_state` (widgets.py:118–121), which is a plain label with no announcement. Buffering and errors are therefore communicated only visually.
- **Fix:** In `_on_player_state`, update both the tooltip and the accessible label to the current action ("Pause", "Play", "Connecting") and push the player state into the button/card description (`update_property([Gtk.AccessibleProperty.LABEL], [...])`); keep the toast for error announcements as already done at line 721.

#### M55. Escape in the search box calls grab_focus() on a widget that can never take focus

- **File:** `frequenzradio/window.py` line 348 (ui, correctness)
- **Problem:** When focus is in the search entry, Escape clears the text and then calls `self.globe.grab_focus()` (line 348). `GlobeView` is constructed with `set_focusable(False)` (globe.py:352), so `grab_focus()` is a no-op: focus stays in the entry, the user's next Space/typing goes back into search, and the intended "return to the globe" behaviour never happens. The same applies to `"/"`/Ctrl+F which only move focus into the entry and give no way back out except Tab.
- **Fix:** Either drop the `grab_focus()` call and move focus to `self.station_list` (a focusable widget that exists), or make the globe focusable (see the accessibility finding) and keep the call.

#### M56. Shortcut map ignores Ctrl/Alt, so Ctrl+P/N/R and Ctrl+Space fire app actions

- **File:** `frequenzradio/window.py` line 351 (ui, correctness)
- **Problem:** `_on_key_pressed` only inspects the Control modifier for the search shortcut (line 340–343) and then looks the bare key name up in `actions` (351–366). Any other modifier combination therefore triggers the unmodified shortcut: Ctrl+P and Ctrl+N (print/new in most apps) jump to the previous/next station, Ctrl+R starts a random station, Ctrl+Space toggles playback, Alt+letter does the same. `Gdk.ModifierType.ALT_MASK`/`SUPER_MASK` are never checked, so the handler also steals combinations the desktop may want.
- **Fix:** Return early when `state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK)` is set and the key is not one of the explicitly handled accelerators (Ctrl+F), i.e. gate the `actions` lookup on `ctrl is False and alt is False`.

#### M57. Reloading places leaves selected/playing indexes pointing into the old array

- **File:** `frequenzradio/window.py` line 374 (ui, correctness)
- **Problem:** `_reload_places` replaces `self.places` with a brand-new `PlaceSet` (line 377) and is invoked from the sync worker via `GLib.idle_add` (line 799). `selected_index`/`playing_index` are plain positions into the old arrays and are not remapped, so after a catalog sync that changes the place ordering the marked dot points at a different place (or at nothing) until the next click, while `_update_place_marker`/`_highlight_playing_row` keep using the stale number. Relatedly, `open_place` indexes `self.places.ids[index]` (line 475) with no bounds check, so any stale index that survives a shrink raises `IndexError`.
- **Fix:** Before replacing the set, remember the ids behind the indexes (`old_id = self.places.ids[self.playing_index]`) and remap after: `self.playing_index = places.index_by_id.get(old_id)`; guard `open_place` with `if not 0 <= index < len(self.places.ids): return`.

#### M58. All row buttons share one generic accessible label, so a long list is unnavigable by ear

- **File:** `frequenzradio/window.py` line 415 (ui, accessibility)
- **Problem:** Every row's play button and favorite toggle carries the same fixed `tooltip_text` ("Play" at line 415, "Favorite" at line 429) and no station title, while the row itself is `activatable` (line 437). In a 120-row search result a screen reader therefore reads 120 identical "Play" buttons and 120 identical "Favorite" toggles, with no way to tell which station each acts on; the row and its two buttons are also three overlapping activation targets for the same row.
- **Fix:** Give each control a per-station label: `play.update_property([Gtk.AccessibleProperty.LABEL], [f"Play {row['title']}"])` and `f"Favorite {row['title']}"`, and set `Gtk.AccessibleProperty.DESCRIPTION` on the row to the place text; consider `Gtk.ListBoxRow.set_focusable(False)` so the two buttons are the only tab stops.

#### M59. Building the station list does one SQLite query per row and creates ~600 widgets per search

- **File:** `frequenzradio/window.py` line 428 (ui, performance)
- **Problem:** `_station_row` calls `self.catalog.is_favorite(station_id)` for every row it builds (line 428). `_run_search` asks for up to 120 rows (line 504), so one debounced keystroke costs 121 synchronous SQLite queries plus ~600 new widgets (5 per row: play button, two labels, toggle, separators) created and laid out on the main thread. Each query is cheap on the primary key, but the per-row round trip and the widget construction together produce a visible hitch on slower machines and it is repeated for every 220 ms debounce that ends in a new query.
- **Fix:** Fetch the favorite ids once (`SELECT station_id FROM favorites` into a set) before the loop and pass the set into `_station_row`, and cap/limit rendering (fetch 40 rows, append more on scroll) so a search never builds hundreds of widgets in one main-loop turn.

### Nit (9)

#### N1. check_same_thread=False without any lock

- **File:** `frequenzradio/catalog.py` line 124 (core, concurrency)
- **Problem:** The flag disables sqlite3's only cross-thread guard, but Catalog has no mutex. Today the GUI opens a separate connection in the sync thread (window.py:795) so no connection is shared, but sync_stations takes a Catalog and writes from whatever thread calls it, and close() can run while another thread reads — a future caller sharing one instance would interleave `with self.db:` blocks and commit another thread's half-finished transaction.
- **Fix:** Either drop the flag (one connection per thread, as the GUI already does) or add an RLock held by every public method and by close().

#### N2. Numeric options are unbounded

- **File:** `frequenzradio/cli.py` line 26 (core, robustness)
- **Problem:** `--workers 100000` builds a ThreadPoolExecutor that spawns one thread per queued place (up to ~2000 threads, each with a large stack); `--limit 0` syncs nothing and reports success; `--limit -1` means 'all' via SQLite's LIMIT semantics; a negative --min-interval silently disables throttling.
- **Fix:** Validate at parse time: workers in 1..32, limit >= 1, min-interval >= 0 (argparse type functions or explicit checks with parser.error()).

#### N3. Unquoted `.[build]` is a glob in the shell

- **File:** `README.md` line 43 (packaging, docs)
- **Problem:** `.venv/bin/pip install -e .[build]` is unquoted; `[build]` is a character class, so in a directory containing a file named e.g. `.b` the word expands and pip receives a wrong path with a confusing error. install-desktop.sh quotes the same argument (`-e '.[build,test]'`), so the two instructions disagree.
- **Fix:** Quote it: `.venv/bin/pip install -e '.[build]'` (and the same for `'.[test]'` at README.md:177).

#### N4. --remove reports success even when nothing was installed

- **File:** `scripts/install-desktop.sh` line 35 (packaging, install-script)
- **Problem:** The remove branch `rm -f` and then always prints 'Removed <file> and <file>', even on a machine where the launcher was never installed or was already removed, and it does not refresh the desktop database/icon cache after deletion (the install path does). The user gets a false confirmation and a stale menu entry can persist until the next cache rebuild.
- **Fix:** Test for existence first and print 'nothing to remove' when both are absent; after deleting, run the same `update-desktop-database`/`gtk-update-icon-cache` calls as the install path.

#### N5. Exec= guard does not reject `%`, which is a field-code character in desktop entries

- **File:** `scripts/install-desktop.sh` line 122 (packaging, install-script)
- **Problem:** The guard rejects quotes, backslashes, `$` and backticks, but a launcher path containing `%` (e.g. a checkout under a directory named `100%`) is written into `Exec="..."` verbatim; the desktop-entry spec treats `%` as a field-code introducer and desktop-file-validate/GIO can reject the key, which breaks app-menu launch with exactly the confusing 'Unable to load application information' the comment above warns about.
- **Fix:** Extend the pattern to `['"\\`$%]`, or escape `%` as `%%` before writing Exec=.

#### N6. Snapshot test hook can kill startup or hang instead of failing cleanly

- **File:** `frequenzradio/app.py` line 59 (ui, correctness)
- **Problem:** The snapshot hook parses `FREQUENZ_SNAPSHOT_AFTER` with a bare `int()` inside `_on_activate` (line 59): a non-numeric value raises `ValueError` out of the activate handler, after `self.window` was created but before `present()`, so the app starts with no window and no message. `_take_snapshot` then assumes `window.get_native()` and `get_renderer()` are non-None and that `render_texture` succeeds (lines 71–78); if any of them returns None the timeout raises before reaching `self.quit()` (line 79), so the snapshot run hangs forever instead of failing.
- **Fix:** Parse the delay defensively (`max(0, int(os.environ.get(..., "6") or 6))` inside `try/except ValueError`), and in `_take_snapshot` guard `native`/`renderer`/`texture` combination, log the reason and always `self.quit()` in a `finally`.

#### N7. Additive lime halo clips to white on the light backdrop and vanishes

- **File:** `frequenzradio/globe_palette.py` line 24 (ui, correctness)
- **Problem:** The halo is composited additively: `frag = vec4(u_bg + u_atmo * glow, 1.0)` (line 183) with `u_bg` = `LIGHT_BACKDROP` = (0.965, 0.969, 0.973) in the light theme (globe_palette.py:24) and `u_atmo` = lime (0.773, 1.0, 0.0). Any glow value above ~4 % saturates the red and green channels to 1.0, so the lime atmosphere renders as flat white on the light page and disappears, while the same glow is clearly visible on the dark backdrop. The design intent ("a lime limb glow", globe_palette.py:6) is lost in the light theme.
- **Fix:** Blend the halo instead of adding it (`mix(u_bg, u_atmo_or_darker, glow)`) or use a light-theme atmosphere colour with contrast against `LIGHT_BACKDROP` (e.g. a darker olive/green), and compute the additive term from the *distance* to white so the glow cannot clip.

#### N8. Preferences button creates a new window on every click

- **File:** `frequenzradio/preferences.py` line 25 (ui, correctness)
- **Problem:** Every call to `open_preferences` builds a new `Adw.PreferencesWindow` (preferences.py:25–27) and both callers discard the returned object (`window.py:186` in the rail, `window.py:327` in the `win.preferences` action). Clicking the gear five times stacks five modal preferences windows, each with its own signal connections to the main window; closing them all is manual.
- **Fix:** Keep one instance on the main window (`self._preferences`) and `present()` it again when it already exists (`if self._preferences is None: ...`), clearing it on close.

#### N9. Now-playing title overwrites the station location line

- **File:** `frequenzradio/window.py` line 723 (ui, correctness)
- **Problem:** `_on_player_title` writes the ICY title into `self.now_sub` (lines 723–725), which `_show_now` uses for the station's location (line 407). After the first metadata tag the location is gone for the rest of the session with that station, and the secondary line flips between "City, Country" and a song title depending on timing — there is no way to see both, and `LiveCard` never shows the ICY title at all.
- **Fix:** Add a dedicated line for the ICY title (third label in the player bar, or reuse the card's place row) and keep `now_sub` for the location; clear the title label in `_show_now`.

## Remediation status (2026-11-11)

Fixed in this pass, with regression tests where the defect was testable:

| Finding | Status |
|---|---|
| RPM hard `Requires: gstreamer1-libav` | fixed — removed; `gstreamer1-plugins-ugly-free` added |
| RPM/DEB built from different sources | partial — Debian packaging merged into this branch; artifacts must be rebuilt from the release commit (container job) |
| Malformed `/places` entry aborts sync | fixed — per-entry guard, range check; `tests/test_api_parsing.py` |
| Failed batch write aborts sync | fixed — per-place fallback, final flush cannot mask; `tests/test_sync_write_failure.py` |
| `schema_version` stamped before migration | fixed — version written after the repair commits |
| Incremental sync is a permanent no-op | fixed — station-count and dataset-version changes requeue; `tests/test_catalog_incremental.py` |
| Corrupt catalog crashes `doctor` | fixed — reported as a failure with a hint |
| Ctrl+Q bypasses teardown | fixed — quit closes the window, `close-request` runs |
| Auto-skip hijacks a newly picked station | fixed — timer re-checks the failed station id |
| Teardown closes catalog under queued idles | fixed — `_closing` guards the idle callbacks |
| Globe redraws at the display refresh rate | fixed — playing-dot pulse throttled to 15 Hz |
| GL uploads through `make_current()` in an idle | fixed — checked, `Gdk.GLContext.clear_current()` in `finally` |
| Corrupt layer raises on every frame | fixed — logged once, layer marked missing, note shown |
| Missing playbin aborts startup | fixed — alert dialog instead of a traceback |
| Globe has no keyboard/screen-reader path | **open** — needs its own accessibility pass |
| Prefetch does disk IO on the main thread | **open** — needs an async upload queue |
| No tests for player/window state machine | **partial** — API/CLI/state/sync/catalog tests added; player and window still need a fake pipeline/bus harness |
| No MP3 decoder on Fedora | fixed — `gstreamer1-plugins-ugly-free` required |
| Decoder check passes with one decoder | fixed — per-format check, MP3/AAC are failures |
| License tag omits bundled icons | fixed — `GPL-3.0-or-later AND ISC AND MIT`, `%license` |
| Debian copyright omits Lucide/Feather | fixed — separate stanza with ISC and MIT texts |
| No AppStream metadata | fixed — metainfo installed by RPM, DEB and Flatpak |
| Debian `3.0 (native)` source format | fixed — `3.0 (quilt)`, `.orig.tar.gz` naming, `0.2.1-1` revision |
| `build-globe` hint names a nonexistent package | fixed — `frequenzradio[build]` plus distro alternatives |
| About dialog hardcodes the version | fixed — `__version__`, guarded by `tests/test_version_consistency.py` |
| README documents the wrong data directory | fixed — `~/.local/share/frequenz`, guarded by a test |
| No CLI tests | fixed — `tests/test_cli.py` |

Also fixed from the minor list: HTTP body-size cap, `Retry-After`, JSON/shape errors as `ApiError`, URL quoting,
redirect scheme check, sync cancellation joins workers, `mark_synced` only on a clean run, FTS rebuild no longer
per sync, `LIMIT` clamp, state validation and atomic save, surrogate filtering, CLI exit code 130 and top-level
error handling, bounded numeric options, `FREQUENZ_CATALOG` validation, README supported matrix and OpenGL 3.3,
User-Agent from `__version__`.

Deferred to follow-ups: sync lock between GUI and CLI, pruning stations removed upstream, long batch transactions,
GL prefetch threading, globe keyboard/screen-reader access, player/window test harness, `DEB_BUILD_OPTIONS=nocheck`,
and the remaining install-script nits.
