# Copyright 2026 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

inherit meson

MY_COMMIT="185b559ca6bb2be7af0a28e2c75455d6f926552b"

DESCRIPTION="A Wayland compositor built on wlroots"
HOMEPAGE="https://github.com/noctalia-dev/umbriel https://docs.noctalia.dev/umbriel/"
SRC_URI="https://github.com/noctalia-dev/umbriel/archive/${MY_COMMIT}.tar.gz -> ${PN}-${MY_COMMIT}.tar.gz"
S="${WORKDIR}/${PN}-${MY_COMMIT}"

LICENSE="MIT"
SLOT="0"
KEYWORDS="~amd64"
IUSE="jemalloc screencast"

DEPEND="
	>=dev-cpp/nlohmann_json-3.11.3
	dev-cpp/tomlplusplus
	>=dev-libs/libinput-1.23
	>=dev-libs/wayland-1.24
	>=gui-libs/wlroots-0.20.1:0.20[X]
	<gui-libs/wlroots-0.21.0:0.20
	media-libs/libdisplay-info
	media-libs/mesa[opengl]
	jemalloc? ( dev-libs/jemalloc )
	>=x11-libs/libdrm-2.4.129
	x11-libs/libxcb
	x11-libs/pango
	x11-libs/cairo
	x11-libs/pixman
	x11-libs/xcb-util-wm
	x11-libs/libxkbcommon
"

RDEPEND="
	${DEPEND}
	x11-base/xwayland
	screencast? ( gui-libs/xdg-desktop-portal-umbriel )
"

BDEPEND="
	>=dev-build/meson-1.3
	dev-build/ninja
	>=dev-libs/wayland-protocols-1.47
	dev-util/wayland-scanner
	virtual/pkgconfig
"

src_configure() {
	local emesonargs=(
		-Dtests=disabled
		$(meson_feature jemalloc)
	)

	meson_src_configure
}
