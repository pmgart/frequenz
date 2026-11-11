# Packaging

FREQUENZ ships from one tree in three formats. The application code, the desktop file,
the AppStream metadata and the icons are shared; each directory only adds the wrapper
for its package manager.

| Directory | Target | Build |
|-----------|--------|-------|
| `fedora/` | Fedora 45 (RPM) | `packaging/fedora/verify-in-fedora.sh` (builds in a container) |
| `debian/` | Ubuntu 26.04 (deb) | `packaging/debian/verify-in-ubuntu.sh` (builds in a container) |
| `flatpak/` | Any Flatpak host (Flathub) | `flatpak-builder --user --install --force-clean build-flatpak packaging/flatpak/se.laps.Frequenz.yml` |

## Shared files

Everything the packages install comes from the Python package:

- `frequenzradio/data/se.laps.Frequenz.desktop`
- `frequenzradio/data/se.laps.Frequenz.metainfo.xml`
- `frequenzradio/data/icons/hicolor/<size>x<size>/apps/se.laps.Frequenz.png` (16 to 512)
- `packaging/icon/` holds the 1024 px master the hicolor sizes are rendered from.

The application ID is `se.laps.Frequenz` everywhere: desktop file, AppStream component,
icon names, Flatpak app ID and the RPM/DEB package name `frequenz`.

## Flatpak

The manifest targets `org.gnome.Platform` 51 and installs numpy, PyOpenGL and shapely
as vendored wheels (`python3-deps.json`), so the build needs no network for Python
packages. Regenerate that file when the dependencies change:

```bash
flatpak_pip_generator --runtime=org.gnome.Sdk//51 \
    --prefer-wheels=numpy,shapely --output python3-deps \
    numpy PyOpenGL shapely
```

Run it from `packaging/flatpak/` so the JSON lands next to the manifest.

### What a Flatpak user still has to do

The catalog and the vector map are downloaded per user, also inside the sandbox:

```bash
flatpak run --command=frequenz se.laps.Frequenz sync
flatpak run --command=frequenz se.laps.Frequenz build-globe
```
