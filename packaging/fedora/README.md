# FREQUENZ on Fedora

This branch is `main` plus Fedora packaging. It also records what was checked in a Fedora container.
Both fixes listed below are on `main` as well.

## What is here

- `frequenz.spec`: RPM spec. Noarch, built with the pyproject macros. It installs the `frequenz` command,
  the desktop file and the icon, and runs the test suite in `%check`. Licence: GPL-3.0-or-later.
- `verify-in-fedora.sh`: builds the RPM, installs it and runs the checks in a clean `fedora:latest`
  container (Docker or Podman). It uses the working tree, so commit first. It fails if the package has no
  licence tag or LICENSE file, or if it contains a catalog or an APK.

```
packaging/fedora/verify-in-fedora.sh docker fedora:latest
sudo dnf install ./frequenz-0.2.0-1.fc45.noarch.rpm
```

The RPMs, the source RPM and `SHA256SUMS` are written to `~/frequenz-rpm-out` (override with `FREQUENZ_RPM_OUT`).

## Release

`v0.2.0` is a pre-release on the private repository. It has the Fedora 45 and Ubuntu 26.04 packages, built from the same program source (commit `319f84d` on `main`): the Fedora 45 RPM and source RPM, the Ubuntu .deb and the source tarball, with `SHA256SUMS`. `v0.1.1` is superseded.

The package is for Fedora 45 only. It installs into Fedora 45's Python 3.15 path and will not run on other
releases. For another release, run the script with that image, for example `fedora:44`.

## Runtime dependencies

| Requires | Why |
|---|---|
| `python3-gobject`, `gtk4`, `libadwaita`, `gstreamer1` | GTK 4 and libadwaita UI, GStreamer through PyGObject |
| `gstreamer1-plugins-base`, `-good`, `gstreamer1-plugins-bad-free`, `gstreamer1-libav` | `playbin3`, HTTP sources, MP3, AAC, Opus, Vorbis and FLAC decoders |
| `hicolor-icon-theme` | application icon |
| `rsms-inter-fonts` | Inter, the typeface of the interface |
| `python3dist(pyopengl)`, `python3dist(numpy)` | generated from the Python metadata |
| `Recommends: python3-shapely` | only for `frequenz build-globe` |

## Verified for 0.1.1: Fedora 45 container, built from 4252fd8

| Check | Result |
|---|---|
| Static and generated BuildRequires resolve | ok |
| `rpmbuild -ba` (noarch RPM and source RPM) | ok |
| `%check`: `desktop-file-validate`, then pytest | ok; 63 passed, 15 skipped |
| Install with runtime dependencies (`dnf install`) | ok |
| Package contents: licence `GPL-3.0-or-later`, LICENSE file present, no catalog or APK | ok |
| `desktop-file-validate` on the installed file | ok |
| `frequenz doctor`: GTK 4.24.1, libadwaita 1.10, GStreamer 1.28.8 | ok |
| `doctor`: `playbin3`, `souphttpsrc`, `decodebin`, `autoaudiosink`, MP3/AAC/Opus/Vorbis/FLAC decoders | ok |
| `doctor`: display | FAIL "unknown session". Expected: the container has no display |
| `doctor`: catalog and vector map | warn, not present. Expected in a fresh container |
| Window start-up under Xvfb, default OpenGL path | ok: exit 0, snapshot written, no traceback; the fallback message is shown because there is no OpenGL context |
| Window start-up under Xvfb, `GDK_DEBUG=gl-software` (informational) | exit 0, snapshot written; fallback message shown as well |

The 15 skipped tests are the vector-map checks in `tests/test_globe_data.py`. They skip because the map is not built.
A local run with an empty data folder gives the same 63 passed and 15 skipped.

## Fixes found by the container test (both now on `main`)

1. **No usable OpenGL context raised an uncaught exception.** Without 3D acceleration (a VM, or Xvfb without
   DRI3), the first GL call in `GlobeView._on_realize` raised. PyGObject printed the traceback; the window kept
   running, but the globe never drew. The app now logs `3D globe disabled`, shows "3D globe unavailable" in the
   zoom label, and keeps running: the station list, search and player still work.
2. **The process did not exit while the catalog download ran.** The download's worker threads are not daemons,
   and nothing set the cancel event. In the container run the process was still alive after its snapshot and
   was killed by the 120 s timeout. The app now cancels the download on shutdown. How long the full download takes
   was never measured; earlier throughput of 1 to 6 places per second puts it at about 36 minutes to 3.5 hours.

Two earlier commit messages on this branch (8508c75 and 10eddf4) say "crashed the app" and "15 to 20 minutes".
The first is wrong and the second was never measured. The corrected messages are on `main`.

## Not verified

- **A Fedora KDE Plasma (Wayland) session.** The container has no desktop session. The launcher, the window
  decorations and the icon are not checked there.
- **The globe rendered with OpenGL on Fedora.** The Xvfb container has no GL context, even with software OpenGL,
  so only the fallback path ran. The first real test will be on a laptop with a GPU.
- **The on-screen fallback text.** The Xvfb window is small and the two bottom labels overlap, so the text was not
  confirmed visually. The warning in the log and the code path were confirmed.
- **`frequenz sync` and `frequenz build-globe` to completion on Fedora.** The catalog download started in the
  container but was not run to the end.
- **Audio playback.** The container has no audio device.
- **Fedora releases other than 45.**

## Open items before a Fedora review submission

- Add an AppStream metainfo file, so KDE Discover can list the app.
- Run `rpmlint` on the spec and the RPM. It has not been run yet.
- Copyright holder: LAPS AB, written by Pablo Magana (README and package metadata on `main`). The v0.1.0 RPM on the release predates this, so its README and metadata do not name the holder.
- Decide whether the project goes public. The `URL:` in the spec points to the private repository.
