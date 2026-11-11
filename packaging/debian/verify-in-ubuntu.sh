#!/usr/bin/env bash
# Build the FREQUENZ .deb and check it in a clean Ubuntu 26.04 container.
#
#   packaging/debian/verify-in-ubuntu.sh [docker|podman] [image]
#
# The source tarball is made from the working tree (tracked files plus new files that git does not
# ignore). Commit first. Outputs go to $FREQUENZ_DEB_OUT (default: ~/frequenz-deb-out): the .deb, the
# source tarball (the GPL requires the source to go with any binary you share) and SHA256SUMS.
set -euo pipefail

ENGINE="${1:-docker}"
IMAGE="${2:-ubuntu:26.04}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -n 1)"
OUT="${FREQUENZ_DEB_OUT:-$HOME/frequenz-deb-out}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# Rootless podman maps container root to the invoking host user; only docker needs the chown.
CHOWN_OUT=1
if [ "$ENGINE" = "podman" ]; then CHOWN_OUT=0; fi
DNS_ARGS=()
if [ -n "${FREQUENZ_DNS:-}" ]; then DNS_ARGS=(--dns "$FREQUENZ_DNS"); fi

mkdir -p "$OUT"
rm -f "$OUT"/frequenz_* "$OUT"/frequenz-*.tar.gz "$OUT"/SHA256SUMS
(cd "$ROOT" && git ls-files -z -co --exclude-standard |
    tar --null -T - --transform "s,^,frequenz-$VERSION/," -czf "$WORK/frequenz_$VERSION.orig.tar.gz")
cp "$WORK/frequenz_$VERSION.orig.tar.gz" "$OUT/"
echo "source: frequenz_$VERSION.orig.tar.gz ($(tar -tzf "$WORK/frequenz_$VERSION.orig.tar.gz" | wc -l) entries)"

"$ENGINE" run --rm "${DNS_ARGS[@]}" \
    -e "VERSION=$VERSION" \
    -e "HOST_UID=$(id -u)" \
    -e "HOST_GID=$(id -g)" \
    -e "CHOWN_OUT=$CHOWN_OUT" \
    -v "$WORK:/work:ro,z" \
    -v "$OUT:/out:z" \
    "$IMAGE" bash -euo pipefail -c '
export DEBIAN_FRONTEND=noninteractive
echo "== $(. /etc/os-release && echo "$PRETTY_NAME")"
if [ "$CHOWN_OUT" = "1" ]; then trap "chown -R $HOST_UID:$HOST_GID /out || true" EXIT; fi
apt-get update -qq
apt-get install -y -qq --no-install-recommends devscripts equivs dpkg-dev > /dev/null
mkdir -p /build && tar -xzf "/work/frequenz_$VERSION.orig.tar.gz" -C /build
cd "/build/frequenz-$VERSION"
cp -r packaging/debian debian
echo "== build dependencies"
mk-build-deps -i -r -t "apt-get -y -qq --no-install-recommends" debian/control > /tmp/mkdeps.log 2>&1 || { tail -n 40 /tmp/mkdeps.log; exit 1; }
echo "== dpkg-buildpackage (the build also runs the tests and the desktop-file check)"
dpkg-buildpackage -us -uc -b > /tmp/build.log 2>&1 || { tail -n 80 /tmp/build.log; exit 1; }
grep -E "passed|failed" /tmp/build.log | tail -n 1
cp /build/frequenz_*.deb /out/
echo "== install the .deb with its dependencies"
apt-get install -y -qq --no-install-recommends /out/frequenz_*.deb > /tmp/install.log 2>&1 || { tail -n 40 /tmp/install.log; exit 1; }
dpkg -s frequenz | grep -E "^(Package|Version|Architecture):"
if dpkg -c /out/frequenz_*.deb | grep -E -q "[.](sqlite|apk)$"; then echo "FAIL: catalog or APK inside the package"; exit 1; fi
grep -q "LAPS AB" /usr/share/doc/frequenz/copyright && echo "package checked: copyright names LAPS AB, no catalog or APK"
desktop-file-validate /usr/share/applications/se.laps.Frequenz.desktop && echo "desktop file: valid"
echo "== frequenz doctor (no display in the container, so the display and catalog lines are expected to warn)"
frequenz doctor || true
echo "== window start-up under Xvfb"
apt-get install -y -qq xvfb xauth > /dev/null
FREQUENZ_SNAPSHOT=/out/frequenz-window.png FREQUENZ_SNAPSHOT_AFTER=6 timeout 120 xvfb-run -a sh -c "frequenz > /tmp/window.log 2>&1"
test -s /out/frequenz-window.png
if grep -q Traceback /tmp/window.log; then echo "FAIL: traceback during start-up"; cat /tmp/window.log; exit 1; fi
echo "window start-up: exit 0, snapshot written, no traceback"
if grep -q "3D globe disabled" /tmp/window.log; then echo "OpenGL: no usable context under Xvfb, so the fallback was shown (expected here)"; else echo "OpenGL: context available, no fallback"; fi
'
(cd "$OUT" && sha256sum frequenz_*.deb "frequenz_$VERSION.orig.tar.gz" > SHA256SUMS)
echo "outputs in $OUT:"
ls -1 "$OUT" | grep -v "[.]png$" || true
