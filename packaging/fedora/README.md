# FREQUENZ on Fedora

This branch adds Fedora packaging to FREQUENZ and records what was checked in a Fedora container.
`main` has no packaging files. The two fixes listed below are on this branch only; they are general
fixes and should be merged into `main` as well.

## What is here

- `frequenz.spec`: RPM spec. Noarch, built with the pyproject macros. It installs the `frequenz` command,
  the desktop file and the icon, and runs the test suite in `%check`.
- `verify-in-fedora.sh`: builds the RPM, installs it and runs the checks in a clean `fedora:latest`
  container (Docker or Podman). It uses the working tree, so commit first.

```
packaging/fedora/verify-in-fedora.sh docker fedora:latest
sudo dnf install ~/frequenz-rpm-out/frequenz-0.1.0-1.fc45.noarch.rpm
```

The RPMs are copied to `~/frequenz-rpm-out` (override with `FREQUENZ_RPM_OUT`).

## Runtime dependencies

| Requires | Why |
|---|---|
| `python3-gobject`, `gtk4`, `libadwaita`, `gstreamer1` | GTK 4 and libadwaita UI, GStreamer through PyGObject |
| `gstreamer1-plugins-base`, `-good`, `gstreamer1-plugins-bad-free`, `gstreamer1-libav` | `playbin3`, HTTP sources, MP3, AAC, Opus, Vorbis and FLAC decoders |
| `hicolor-icon-theme` | application icon |
| `python3dist(pyopengl)`, `python3dist(numpy)` | generated from the Python metadata |
| `Recommends: python3-shapely` | only for `frequenz build-globe` |

## Verified: Fedora 45 container, 2026-11-05

| Check | Result |
|---|---|
| Static and generated BuildRequires resolve | ok |
| `rpmbuild -ba` (noarch RPM and source RPM) | ok |
| `%check`: `desktop-file-validate`, then pytest | ok; 63 passed, 15 skipped |
| Install with runtime dependencies (`dnf install`) | ok |
| `desktop-file-validate` on the installed file | ok |
| `frequenz doctor`: GTK 4.24.1, libadwaita 1.10, GStreamer 1.28.8 | ok |
| `doctor`: `playbin3`, `souphttpsrc`, `decodebin`, `autoaudiosink`, MP3/AAC/Opus/Vorbis/FLAC decoders | ok |
| `doctor`: display | FAIL "unknown session". Expected: the container has no display |
| `doctor`: catalog and vector map | warn, not present. Expected in a fresh container |
| Window start-up under Xvfb, default OpenGL path | ok: snapshot written, exit 0 |
| Window start-up under Xvfb, `GDK_DEBUG=gl-software` (informational) | exit 0, snapshot written, but no GL context either |

The 15 skipped tests are the vector-map checks in `tests/test_globe_data.py`. They skip because the map is not built.
A local run with an empty data folder gives the same 63 passed and 15 skipped.

## Fixes found by the container test

1. **No usable OpenGL context crashed the app.** Without 3D acceleration (a VM, or Xvfb without DRI3),
   the first GL call in `GlobeView._on_realize` raised. The app now logs `3D globe disabled`, shows
   "3D globe unavailable" in the zoom label, and keeps running: the station list, search and player still work.
2. **Quitting during the first catalog download hung the process** until the download finished (15 to 20 minutes).
   The download's worker threads are not daemons, and nothing set the cancel event. The app now cancels the
   download on shutdown.

## Not verified

- **A Fedora KDE Plasma (Wayland) session.** The container has no desktop session. The launcher, the window
  decorations and the icon are not checked there.
- **The globe rendered with OpenGL on Fedora.** The Xvfb container gets no GL context, even with software OpenGL,
  so only the fallback path ran. A real Fedora session is needed.
- **The on-screen fallback text.** The Xvfb window is small and the two bottom labels overlap, so the text was not
  confirmed visually. The warning in the log and the code path were confirmed.
- **`frequenz sync` and `frequenz build-globe` to completion on Fedora.** The catalog download started in the
  container but was not run to the end.
- **Audio playback.** The container has no audio device.

## Open items before a Fedora review submission

- Choose a license. The repository has no LICENSE file yet, and the spec's `License:` field is a placeholder.
- Add an AppStream metainfo file, so KDE Discover can list the app.
- Decide whether the project goes public. The `URL:` in the spec points to the private repository.
