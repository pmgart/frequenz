# FREQUENZ

A native, local and **ad-free** desktop client for Radio Garden: turn the globe, tune in to live
stations and search the catalog. Built with GTK 4 and libadwaita, GStreamer for audio and an
OpenGL globe. Browsing, search and favorites run from a local SQLite catalog. Only the audio stream
itself needs the network.

> Unofficial. Not affiliated with Radio Garden. Station names, place data and streams belong to
> Radio Garden and the broadcasters. Personal use only; do not redistribute the catalog.

## Features

- **Globe**: a 3D globe drawn from Natural Earth vector data (land, lakes, glaciers, borders and rivers),
  lit by the real sun for the current time. About 12,900 places are sized by station count. Six zoom
  levels run from the whole globe to 100 km above the surface, with inertial drag, hover labels, click
  to tune in and double-click to zoom.
- **Stations**: place lists, search (prefix and diacritic-insensitive), favorites, history and a
  random station.
- **Player**: GStreamer `playbin3` with live ICY titles ("now playing"), automatic reconnect,
  volume, previous and next within the current list.
- **Local first**: the catalog is downloaded once (`frequenz sync`) and stored in
  `~/.local/share/frequenzradio/`.
- **No ads**: no ad SDKs, consent frameworks, promo banners or pre-roll ad media. See
  [What "no ads" means here](#what-no-ads-means-here).

## Requirements

Ubuntu 24.04 or later with GNOME on Wayland (tested on Ubuntu 26.04 with an NVIDIA RTX 4060 Ti).

```bash
sudo apt install python3-gi python3-venv gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gstreamer-1.0 \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav
```

- OpenGL 3.0+ (desktop GL or GLES 3.0 through EGL). Works with Mesa and NVIDIA drivers.
- PipeWire or PulseAudio for audio output (autoaudiosink).

## Install and first run

```bash
cd Frequenz
python3 -m venv --system-site-packages .venv   # system site packages give access to PyGObject
.venv/bin/pip install -e .[build]             # [build] adds shapely, needed once to build the map
.venv/bin/frequenz doctor                    # checks GTK, libadwaita, GStreamer and OpenGL
.venv/bin/frequenz sync                      # one-time catalog download (see below)
.venv/bin/frequenz build-globe               # one-time vector map for the globe (about 50 MB download)
scripts/install-desktop.sh                      # optional: app-menu launcher and icon
.venv/bin/frequenz                           # start the app
```

The first start also downloads the catalog automatically if it is missing. Without the vector map the
globe still starts, shows its dots, and says in the corner that the map is not built.

### Catalog sync

`frequenz sync` fetches the place list (one request) and then the station list of every place
(about 12,900 requests). Requests are throttled to roughly 10 per second across four workers,
retried with back-off on 429 and 5xx responses, and resumable: stop with Ctrl+C at any time and
run it again to fetch only the missing places.

```bash
frequenz sync                      # fill in missing places (default)
frequenz sync --places-only        # refresh the place list only
frequenz sync --full               # re-fetch every place (after a long gap)
frequenz sync --limit 50           # small test run
frequenz stats
frequenz search "jazz" --limit 10
```

The GUI also has **Update station catalog** in the main menu. It runs in the background.

## Globe and map data

The globe is drawn from [Natural Earth](https://www.naturalearthdata.com) 1:10 m vector data, which is
public domain. It shows land, lakes, glaciated areas, country borders and rivers. The ocean is one
colour: Natural Earth's 10 m depth bands are not used (see below). Positions use geodetic coordinates
on the WGS84 ellipsoid, so the poles are flattened by about 1/300 as on Earth. The day side follows the
real sun for the current time.

`frequenz build-globe` builds the map once. It downloads about 31 MB of Natural Earth files into
`~/.local/share/frequenzradio/naturalearth/` and records their SHA-256 checksums in `manifest.json`. It
then writes about 36 MB of triangle arrays to `~/.local/share/frequenzradio/globe/`. The build takes about
half a minute on four processes and needs the `build` extra (shapely). Viewing needs only numpy.

Zoom levels, from far to close, with the altitude above the surface:

| Level | Altitude | Detail |
|---|---|---|
| Far | about 31,900 km | whole globe, coastlines simplified to about 13 km |
| Globe (start) | about 15,900 km | whole globe, coastlines simplified to about 13 km |
| Close globe | about 6,400 km | coastlines simplified to about 2 km, country borders |
| Region | 2,000 km | full 10 m data, borders and rivers |
| Country | 500 km | full 10 m data, borders and rivers |
| City | 100 km | full 10 m data, borders and rivers |

`+` and `−` move one level, and the mouse wheel zooms smoothly. The readout in the corner shows the level
and the altitude.

The ocean is one colour because Natural Earth's 10 m depth bands (200, 1,000, 2,000 and 3,000 m) contain
straight lines that the seafloor does not have. Measured on the outline of each merged band, there were 9
(200 m), 16 (1,000 m), 43 (2,000 m) and 52 (3,000 m) straight runs longer than 5°, the longest 91°. The
globe would show these as false steps in the shading, so the bands are left out. Showing depth needs a
cleaner source, for example contours from the GEBCO grid. The globe has no labels, roads or city lights.

## Keyboard and mouse

| Key / action | What it does |
|---|---|
| Click a dot | Tune in to a station from that place and list its stations |
| Double-click a dot | Zoom to that place |
| Drag / scroll | Turn the globe / zoom smoothly |
| Space | Play or pause |
| ← / → (or P / N) | Previous or next station in the current list |
| F | Add or remove the playing station from favorites |
| R | Random station |
| / or Ctrl+F | Search |
| + / − | Zoom one level in / out (see [Globe and map data](#globe-and-map-data)) |
| 0 | Reset view |
| Escape | Clear the list and selection |
| Ctrl+Q | Quit |

## Data, privacy and the service

- **Local data**: `~/.local/share/frequenzradio/catalog.sqlite` (catalog, favorites, history),
  `state.json` (window and last station) and `sync.log`. Set `FREQUENZ_CATALOG` to use another
  database file.
- **Names**: station and place names are cleaned when they are read. Invisible characters (such
  as zero-width spaces and directional marks) are removed and spacing is normalized. Names
  stored by earlier versions were cleaned once, when the catalog was first opened.
- **Requests** go to `https://radio.garden`: the public catalog endpoints, the station detail
  endpoint and the `listen` endpoint that redirects to each stream. There is no account, login or
  telemetry. Requests send a browser-style User-Agent that names this client, because the public
  site returned HTTP 403 to curl's default User-Agent during testing.
- **Streams** come straight from the broadcasters after the redirect.
- **Attribution and use**: the station data is Radio Garden's and the streams are the broadcasters'.
  Keep the catalog for personal use.
- **Map data**: Natural Earth, public domain (https://www.naturalearthdata.com/about/terms-of-use/).

## What "no ads" means here

The web app and the Android app show advertising. This client does not:

- It contains no advertising, analytics or consent SDKs. The catalog and the globe are built from
  the public data only.
- Stations that Radio Garden marks as pre-roll (`preroll: true`, about 4.8 % (1,864 stations), nearly
  all on zeno.fm) play their **direct stream**. The pre-roll ad appears to be added by the Radio Garden
  web player rather than by the station (inferred: the `listen` endpoint returns the plain stream). The `listen` endpoint for these stations redirects straight to the
  broadcaster's stream (verified), so the app never requests ad media.
- The "remove ads" purchase, premium entitlements, and the "get the native app" promotions in the
  web app are not implemented.
- Boosted places (`boost: true`, 243 places) are drawn slightly larger on the globe. This is a
  display flag from the API, not an advertisement.

Details and evidence are in [docs/REVERSE_ENGINEERING.md](docs/REVERSE_ENGINEERING.md).

## Architecture

| Module | Responsibility |
|---|---|
| `frequenzradio/api.py` | Read-only HTTP client, retry and throttle, parsers for places, stations and redirects |
| `frequenzradio/catalog.py` | SQLite schema (WAL), FTS5 search, favorites, history, station details |
| `frequenzradio/sync.py` | Resumable, cancellable catalog crawl with failure isolation |
| `frequenzradio/geo.py` | Ellipsoid geometry (WGS84): coordinates, camera, projection, picking, zoom levels, daylight |
| `frequenzradio/globe.py` | OpenGL 3.0/3.3 globe in a `Gtk.GLArea` (desktop GL or GLES): vector layers, atmosphere, places |
| `frequenzradio/geodata.py` | Loads the triangulated map arrays (numpy only) |
| `frequenzradio/globe_build.py` | Builds the vector map from Natural Earth 1:10m (needs shapely) |
| `frequenzradio/player.py` | GStreamer `playbin3` wrapper: ICY titles, reconnects, per-session pipelines |
| `frequenzradio/window.py`, `app.py` | GTK 4 / libadwaita window, sidebar, player bar, actions |
| `frequenzradio/cli.py`, `doctor.py` | Command line: GUI, `sync`, `stats`, `search`, `build-globe`, `doctor` |

The globe draws vector layers (no map tiles): one triangle mesh per layer and detail level. Places are
GPU point sprites with the web app's size classes, and picking runs on the CPU.

## Tests

```bash
.venv/bin/pip install -e .[test]
.venv/bin/python -m pytest -q          # 78 tests; 12 check the built map against known places and skip until build-globe ran
.venv/bin/python tests/e2e_gui_check.py  # manual: runs the real window and plays real streams
.venv/bin/python tests/globe_zoom_check.py  # manual: flies through the zoom levels and saves screenshots
```

`tests/e2e_gui_check.py` needs a display, network access and a synced catalog. It plays streams,
moves to the next station, pauses and resumes, toggles a favorite, searches, plays a random
station and checks globe picking. Screenshots are written to `/tmp/frequenz-e2e`.

`tests/globe_zoom_check.py` needs a display and the built map. It flies to each zoom level, takes a
screenshot, checks the detail level, the zoom buttons and the wheel, and reports render times and GL errors.
Screenshots are written to `/tmp/frequenz-globe`.

For a quick visual check, `FREQUENZ_SNAPSHOT=/tmp/rg.png .venv/bin/frequenz` writes the window
to a PNG after six seconds and quits (`FREQUENZ_SNAPSHOT_AFTER` changes the delay).

To rebuild the vector map after changing the build code, run `.venv/bin/frequenz build-globe`. It
reuses the downloaded files.

## macOS

A native Mac app for Apple Silicon Macs running macOS 27 or newer. The same GTK 4
code runs on both platforms; the Mac work lives on the `macos-app` branch.

Install `FREQUENZ-<version>-arm64.dmg` from the releases, open it and drag
FREQUENZ to Applications. The build is ad-hoc signed but not notarised, so the
first launch needs System Settings › Privacy & Security › Open Anyway. On a Mac
the data folder is `~/Library/Application Support/frequenz` and the shortcuts
show ⌘ instead of Ctrl. The first launch downloads the station catalog and shows
its progress in the right panel.

From a checkout:

```
scripts/macos-setup.sh
.venv/bin/frequenz
```

`packaging/macos/build-app.sh` builds a self-contained `dist/FREQUENZ.app` with
Python, GTK, libadwaita, GStreamer, the GIR typelibs, the Adwaita icons, Inter
and the globe map inside it; `packaging/macos/make-dmg.sh` turns it into the
`.dmg`. Developer notes: `docs/macos/HANDOFF.md`.

## Known limitations

- The catalog is a snapshot. Stations come and go, so run `frequenz sync` now and then.
- Some streams take 10–12 seconds before the first audio. That is the broadcaster's latency.
- No MPRIS or media-key integration yet. Shortcuts work while the window has focus.
- Only Wayland with GNOME was tested. X11 should work through EGL or GLX but has not been checked.
- The globe has no labels, roads or city lights. The closest zoom level is about 100 km above the surface.
  The ocean is one colour; the depth bands are not drawn (see "Globe and map data").

## Uninstall

```bash
scripts/install-desktop.sh --remove
rm -rf .venv
rm -rf ~/.local/share/frequenz      # catalog, favorites and history
```

## License

Copyright © 2026 LAPS AB. Written by Pablo Magana.

FREQUENZ is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY. See [LICENSE](LICENSE).

The license covers this code. It does not cover the station data: place and station names, stream addresses and related metadata belong to radio.garden and the broadcasters (see "Data, privacy and the service").
