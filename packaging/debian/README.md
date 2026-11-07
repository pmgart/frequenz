# FREQUENZ on Ubuntu (.deb)

Target: **Ubuntu 26.04 LTS** (Python 3.14, GTK 4.22, libadwaita 1.9, GStreamer 1.28). Other releases are not built or tested.

- `control`, `rules`, `changelog`, `copyright`, `source/format`: one `all` package named `frequenz`, built with `dh` and the pyproject build system. The build runs the test suite and the desktop-file check.
- `verify-in-ubuntu.sh`: builds the .deb in a clean `ubuntu:26.04` container, installs it with its dependencies, runs `frequenz doctor` and a start-up under a virtual display. It writes the .deb, the source tarball and `SHA256SUMS` to `~/frequenz-deb-out`.

```
packaging/debian/verify-in-ubuntu.sh docker ubuntu:26.04
sudo apt install ./frequenz_0.2.0_all.deb
```

The source tarball goes with any binary you share, because the GPL requires the source to accompany it.

Not verified: a real Ubuntu desktop session, GPU rendering of the globe, audio playback, and Ubuntu 24.04.
