#!/usr/bin/env bash
# Build the FREQUENZ RPM and run its checks in a clean Fedora container.
#
#   packaging/fedora/verify-in-fedora.sh [docker|podman] [image]
#
# The source tarball is made from the working tree (tracked files plus new files that git does not
# ignore). Commit first to test exactly what is committed. The RPMs are copied to $FREQUENZ_RPM_OUT
# (default: ~/frequenz-rpm-out).
set -euo pipefail

ENGINE="${1:-docker}"
IMAGE="${2:-fedora:latest}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -n 1)"
OUT="${FREQUENZ_RPM_OUT:-$HOME/frequenz-rpm-out}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$OUT"
(cd "$ROOT" && git ls-files -z -co --exclude-standard |
    tar --null -T - --transform "s,^,frequenzradio-$VERSION/," -czf "$WORK/frequenzradio-$VERSION.tar.gz")
echo "source: frequenzradio-$VERSION.tar.gz ($(tar -tzf "$WORK/frequenzradio-$VERSION.tar.gz" | wc -l) entries)"

"$ENGINE" run --rm \
    -e "VERSION=$VERSION" \
    -v "$WORK:/work:ro" \
    -v "$OUT:/out" \
    "$IMAGE" bash -euo pipefail -c '
echo "== $(cat /etc/fedora-release)"
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
cp /root/rpmbuild/RPMS/noarch/*.rpm /root/rpmbuild/SRPMS/*.rpm /out/
echo "== install the RPM together with its runtime dependencies"
dnf -y install /root/rpmbuild/RPMS/noarch/frequenz-*.rpm
rpm -q frequenz
desktop-file-validate /usr/share/applications/se.laps.Frequenz.desktop && echo "desktop file: valid"
echo "== frequenz doctor (the container has no display, so display and GL checks may fail)"
frequenz doctor || true
'
echo "RPMs in $OUT:"
ls -1 "$OUT"
