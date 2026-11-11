#!/usr/bin/env bash
# Build the FREQUENZ RPM and run its checks in a clean Fedora container.
#
#   packaging/fedora/verify-in-fedora.sh [docker|podman] [image]
#
# The source tarball is made from the working tree (tracked files plus new files that git does not
# ignore). Commit first, so the RPM matches a commit. The RPMs, the source RPM and SHA256SUMS are
# written to $FREQUENZ_RPM_OUT (default: ~/frequenz-rpm-out). Earlier results there are removed first.
set -euo pipefail

ENGINE="${1:-docker}"
IMAGE="${2:-fedora:latest}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -n 1)"
OUT="${FREQUENZ_RPM_OUT:-$HOME/frequenz-rpm-out}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# Rootless podman maps container root to the invoking host user, so the outputs are
# already owned correctly; only docker needs the explicit chown.
CHOWN_OUT=1
if [ "$ENGINE" = "podman" ]; then CHOWN_OUT=0; fi
DNS_ARGS=()
if [ -n "${FREQUENZ_DNS:-}" ]; then DNS_ARGS=(--dns "$FREQUENZ_DNS"); fi

mkdir -p "$OUT"
rm -f "$OUT"/frequenz-*
(cd "$ROOT" && git ls-files -z -co --exclude-standard |
    tar --null -T - --transform "s,^,frequenzradio-$VERSION/," -czf "$WORK/frequenzradio-$VERSION.tar.gz")
echo "source: frequenzradio-$VERSION.tar.gz ($(tar -tzf "$WORK/frequenzradio-$VERSION.tar.gz" | wc -l) entries)"

"$ENGINE" run --rm "${DNS_ARGS[@]}" \
    -e "VERSION=$VERSION" \
    -e "HOST_UID=$(id -u)" \
    -e "HOST_GID=$(id -g)" \
    -e "CHOWN_OUT=$CHOWN_OUT" \
    -v "$WORK:/work:ro,z" \
    -v "$OUT:/out:z" \
    "$IMAGE" bash -euo pipefail -c '
echo "== $(cat /etc/fedora-release)"
if [ "$CHOWN_OUT" = "1" ]; then trap "chown -R $HOST_UID:$HOST_GID /out || true" EXIT; fi
dnf -y -q install rpm-build dnf-plugins-core dnf5-plugins pyproject-rpm-macros python3-devel desktop-file-utils
mkdir -p /root/rpmbuild/SOURCES /root/rpmbuild/SPECS /tmp/src
cp "/work/frequenzradio-$VERSION.tar.gz" /root/rpmbuild/SOURCES/
tar -xzf "/work/frequenzradio-$VERSION.tar.gz" -C /tmp/src
cp "/tmp/src/frequenzradio-$VERSION/packaging/fedora/frequenz.spec" /root/rpmbuild/SPECS/
echo "== build dependencies: static BuildRequires, then the pyproject ones from a dry run"
dnf -y builddep /root/rpmbuild/SPECS/frequenz.spec
dnf -y -q install python3-setuptools python3-wheel
rpmbuild -br /root/rpmbuild/SPECS/frequenz.spec > /tmp/buildreqs.log 2>&1 || tail -n 5 /tmp/buildreqs.log
dnf -y builddep /root/rpmbuild/SRPMS/frequenz-*.buildreqs.nosrc.rpm
echo "== rpmbuild (the %check section runs desktop-file-validate and pytest)"
rpmbuild -ba /root/rpmbuild/SPECS/frequenz.spec
cp /root/rpmbuild/RPMS/noarch/frequenz-*.noarch.rpm /root/rpmbuild/SRPMS/frequenz-*.src.rpm /out/
echo "== install the RPM together with its runtime dependencies"
dnf -y install /root/rpmbuild/RPMS/noarch/frequenz-*.noarch.rpm
rpm -q frequenz
test "$(rpm -q --qf "%{LICENSE}" frequenz)" = "GPL-3.0-or-later AND ISC AND MIT"
rpm -qL frequenz | grep -q "LICENSE" || { echo "FAIL: LICENSE file is not in the package"; exit 1; }
if rpm -qlp /root/rpmbuild/RPMS/noarch/frequenz-*.noarch.rpm | grep -E -q "[.](sqlite|apk)$"; then echo "FAIL: catalog or APK inside the package"; exit 1; fi
echo "package checked: license GPL-3.0-or-later AND ISC AND MIT, LICENSE file present, no catalog or APK"
desktop-file-validate /usr/share/applications/se.laps.Frequenz.desktop && echo "desktop file: valid"
echo "== frequenz doctor (no display in the container, so the display and catalog lines are expected to warn)"
frequenz doctor || true
echo "== window start-up under Xvfb (no catalog or map here, so the window starts empty)"
dnf -y -q install xorg-x11-server-Xvfb xorg-x11-xauth
FREQUENZ_SNAPSHOT=/out/frequenz-window.png FREQUENZ_SNAPSHOT_AFTER=6 timeout 120 xvfb-run -a sh -c "frequenz > /tmp/window.log 2>&1"
test -s /out/frequenz-window.png
if grep -q Traceback /tmp/window.log; then echo "FAIL: traceback during start-up"; cat /tmp/window.log; exit 1; fi
echo "window start-up: exit 0, snapshot written, no traceback"
if grep -q "3D globe disabled" /tmp/window.log; then echo "OpenGL: no usable context under Xvfb, so the fallback was shown (expected here)"; else echo "OpenGL: context available, no fallback"; fi
echo "== same window with software OpenGL (informational)"
GDK_DEBUG=gl-software FREQUENZ_SNAPSHOT=/out/frequenz-window-software-gl.png FREQUENZ_SNAPSHOT_AFTER=6 timeout 120 xvfb-run -a sh -c "frequenz > /tmp/window-sw.log 2>&1" && echo "software OpenGL run: exit 0" || echo "software OpenGL run: failed (see /tmp/window-sw.log)"
test -s /out/frequenz-window-software-gl.png && echo "software OpenGL snapshot written" || true
if grep -q "3D globe disabled" /tmp/window-sw.log; then echo "software OpenGL: fallback shown"; else echo "software OpenGL: no fallback message"; fi
'
(cd "$OUT" && sha256sum frequenz-*.noarch.rpm frequenz-*.src.rpm > SHA256SUMS)
echo "RPMs and checksums in $OUT:"
ls -1 "$OUT" | grep -v "[.]png$" || true
