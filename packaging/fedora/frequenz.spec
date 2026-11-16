# FREQUENZ RPM spec for Fedora.
# Build and check it in a clean Fedora container: packaging/fedora/verify-in-fedora.sh

%global srcname frequenzradio

Name:           frequenz
Version:        0.3.0
Release:        1%{?dist}
Summary:        Native, local and ad-free radio globe for Linux
License:        GPL-3.0-or-later AND ISC AND MIT
URL:            https://github.com/pmgart/frequenz
Source0:        %{srcname}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  desktop-file-utils
# The tests import the GTK, libadwaita and GStreamer bindings through PyGObject.
BuildRequires:  python3-gobject
BuildRequires:  gtk4
BuildRequires:  libadwaita
BuildRequires:  gstreamer1
BuildRequires:  gstreamer1-plugins-base
BuildRequires:  appstream

Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       gstreamer1
Requires:       gstreamer1-plugins-base
Requires:       gstreamer1-plugins-good
Requires:       gstreamer1-plugins-bad-free
Requires:       gstreamer1-plugins-ugly-free
Requires:       hicolor-icon-theme
Requires:       rsms-inter-fonts
Recommends:     python3-shapely

%description
FREQUENZ shows the public place and station list of radio.garden on an OpenGL
globe, plays live streams with GStreamer and keeps a local SQLite catalog for
instant search. It is an unofficial client: station data belongs to radio.garden
and the broadcasters. There are no ads and no premium paths.

%prep
%autosetup -n %{srcname}-%{version}

%generate_buildrequires
%pyproject_buildrequires -r -x build,test

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files %{srcname}
install -Dpm0644 %{srcname}/data/se.laps.Frequenz.desktop \
    %{buildroot}%{_datadir}/applications/se.laps.Frequenz.desktop
install -Dpm0644 %{srcname}/data/se.laps.Frequenz.metainfo.xml \
    %{buildroot}%{_datadir}/metainfo/se.laps.Frequenz.metainfo.xml
for size in 16 24 32 48 64 128 256 512; do
    install -Dpm0644 %{srcname}/data/icons/hicolor/${size}x${size}/apps/se.laps.Frequenz.png \
        %{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps/se.laps.Frequenz.png
done

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/se.laps.Frequenz.desktop
appstreamcli validate --no-net %{srcname}/data/se.laps.Frequenz.metainfo.xml
%pytest -q

%files -f %{pyproject_files}
%doc README.md
%license %{srcname}/data/icons/symbolic/LICENSE-lucide.txt
%{_bindir}/frequenz
%{_datadir}/applications/se.laps.Frequenz.desktop
%{_datadir}/metainfo/se.laps.Frequenz.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/se.laps.Frequenz.png

%changelog
* Wed Nov 11 2026 Pablo Magana <pablo@laps.se> - 0.3.0-1
- New application icon (hicolor PNGs 16-512) and AppStream metadata, so the app
  is listed in GNOME Software and KDE Discover.
- Flatpak packaging; Fedora, Debian and Flatpak ship from one tree.
- Code-review fixes: sync robustness, clean teardown, globe redraw and GL handling,
  CLI error reporting and exit codes.
- Require gstreamer1-plugins-ugly-free for MP3; drop the RPM Fusion dependency.
- Ship the Lucide/Feather icon licence as %license.

* Sat Nov 07 2026 Pablo Magana <pablo@laps.se> - 0.2.1-1
- Fix: the map-pin icon on the now-playing card is visible. It took the window's text colour,
  which made it disappear on the card.

* Sat Nov 07 2026 Pablo Magana <pablo@laps.se> - 0.2.0-1
- New interface from the approved design: header with the light and dark switch, left rail,
  now-playing card, station list and player bar. Classic globe colours are an option in Preferences.
- Requires rsms-inter-fonts for the Inter typeface.

* Fri Nov 06 2026 Pablo Magana <pablo@laps.se> - 0.1.1-1
- Same program source as the Ubuntu package: version 0.1.1, copyright holder LAPS AB.

* Thu Nov 05 2026 Pablo Magana <pablo@laps.se> - 0.1.0-1
- Initial package
