# Copyright 2026 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

inherit meson

MY_COMMIT="e69d6f72122a99aa3668e182a4df8755ada81c17"

DESCRIPTION="XDG Desktop Portal backend for the Umbriel compositor"
HOMEPAGE="https://github.com/noctalia-dev/xdg-desktop-portal-umbriel"
SRC_URI="https://github.com/noctalia-dev/xdg-desktop-portal-umbriel/archive/${MY_COMMIT}.tar.gz -> ${P}.tar.gz"
S="${WORKDIR}/${PN}-${MY_COMMIT}"

LICENSE="MIT"
SLOT="0"
KEYWORDS="~amd64"
IUSE="+picker"

DEPEND="
	>=dev-cpp/sdbus-c++-2.0:=
	dev-cpp/nlohmann_json
	dev-cpp/tomlplusplus
	dev-libs/wayland
	media-libs/mesa[opengl]
	media-video/pipewire
	x11-libs/cairo
	x11-libs/libdrm
	picker? ( >=gui-libs/gtk-4.12:4 )
"

RDEPEND="
	>=dev-cpp/sdbus-c++-2.0:=
	dev-libs/wayland
	media-libs/mesa[opengl]
	media-video/pipewire
	sys-apps/xdg-desktop-portal
	x11-libs/cairo
	x11-libs/libdrm
	picker? ( >=gui-libs/gtk-4.12:4 )
"

BDEPEND="
	>=dev-build/meson-1.3
	dev-build/ninja
	>=dev-libs/wayland-protocols-1.39
	dev-util/wayland-scanner
	virtual/pkgconfig
	picker? ( dev-util/glib-utils )
"

src_configure() {
	local emesonargs=(
		-Dtests=false
		$(meson_feature picker)
	)

	meson_src_configure
}
