# Copyright 2026 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

inherit meson

MY_COMMIT="32b8ee4ff0675c3f819c13b3f4b8651c1b887a43"

DESCRIPTION="XDG Desktop Portal backend for the Umbriel compositor"
HOMEPAGE="https://github.com/noctalia-dev/xdg-desktop-portal-umbriel"
SRC_URI="https://github.com/noctalia-dev/xdg-desktop-portal-umbriel/archive/${MY_COMMIT}.tar.gz -> ${P}.tar.gz"
S="${WORKDIR}/${PN}-${MY_COMMIT}"

LICENSE="MIT"
SLOT="0"
KEYWORDS="~amd64"
IUSE="+picker"

COMMON_DEPEND="
	>=dev-cpp/sdbus-c++-2.0:=
	dev-libs/wayland
	media-libs/mesa[opengl]
	media-video/pipewire
	x11-libs/cairo
	x11-libs/libdrm
	picker? (
		dev-libs/glib:2
		media-libs/fontconfig
		media-libs/freetype:2
		media-libs/harfbuzz:=
		media-libs/libglvnd
		media-libs/mesa[wayland]
		x11-libs/libxkbcommon
		>=x11-libs/pango-1.50
	)
"

DEPEND="
	${COMMON_DEPEND}
	dev-cpp/nlohmann_json
	dev-cpp/tomlplusplus
	picker? (
		>=dev-libs/stb-20240201
	)
"

RDEPEND="
	${COMMON_DEPEND}
	sys-apps/xdg-desktop-portal
"

BDEPEND="
	>=dev-build/meson-1.3
	dev-build/ninja
	>=dev-libs/wayland-protocols-1.39
	dev-util/wayland-scanner
	virtual/pkgconfig
"

src_configure() {
	local emesonargs=(
		-Dtests=false
		$(meson_use picker)
	)

	meson_src_configure
}
