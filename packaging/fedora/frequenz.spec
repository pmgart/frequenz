# FREQUENZ RPM spec for Fedora.
# Build and check it in a clean Fedora container: packaging/fedora/verify-in-fedora.sh
#
# Open items before a Fedora review submission:
#   - no AppStream metainfo file yet: KDE Discover will not list the app until one exists

%global srcname frequenzradio

Name:           frequenz
Version:        0.1.0
Release:        1%{?dist}
Summary:        Native, local and ad-free radio globe for Linux
License:        GPL-3.0-or-later
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

Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       gstreamer1
Requires:       gstreamer1-plugins-base
Requires:       gstreamer1-plugins-good
Requires:       gstreamer1-plugins-bad-free
Requires:       gstreamer1-libav
Requires:       hicolor-icon-theme
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
install -Dpm0644 %{srcname}/data/icons/hicolor/scalable/apps/se.laps.Frequenz.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/se.laps.Frequenz.svg

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/se.laps.Frequenz.desktop
%pytest -q

%files -f %{pyproject_files}
%doc README.md
%{_bindir}/frequenz
%{_datadir}/applications/se.laps.Frequenz.desktop
%{_datadir}/icons/hicolor/scalable/apps/se.laps.Frequenz.svg

%changelog
* Thu Nov 05 2026 Pablo Magana <pablo@laps.se> - 0.1.0-1
- Initial package
