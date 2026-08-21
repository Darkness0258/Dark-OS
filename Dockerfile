FROM archlinux:latest

LABEL org.opencontainers.image.title="DarkOS ISO Builder"
LABEL org.opencontainers.image.description="Privileged ArchISO build environment for DarkOS"

RUN pacman -Sy --noconfirm archlinux-keyring && \
    (echo y | pacman -Syu --needed --noconfirm \
    alsa-utils arch-install-scripts archiso autoconf automake base-devel bison \
    boost-libs btrfs-progs cmake cpio curl db5.3 debugedit desktop-file-utils \
    diffutils dosfstools duktape efibootmgr efivar elfutils erofs-utils \
    extra-cmake-modules fakeroot flex fontconfig freetype2 gc gcc gdb \
    git grub guile jsoncpp kcoreaddons ki18n kpmcore kwidgetsaddons libburn \
    libcups libdaemon libdeflate libdrm libedit libevdev libglvnd libgudev \
    libice libinput libisl libisofs libjpeg-turbo libmpc libpciaccess libpng \
    libproxy libpwquality libsm libtool liburing libuv libwacom libx11 \
    libxau libxcb libxdmcp libxext libxkbcommon libxkbcommon-x11 libxshmfence \
    libxxf86vm libyaml litehtml llvm-libs lm_sensors lua54 lzo m4 make \
    md4c mesa mkinitcpio mkinitcpio-busybox mpdecimal mtools ninja noto-fonts \
    pacman-contrib patch perl perl-error perl-mailtools perl-timedate pipewire \
    pipewire-pulse pkgconf polkit polkit-qt6 pv python python-cairo python-gobject \
    python-yaml qt6-base qt6-declarative qt6-svg qt6-tools qt6-translations \
    rhash rsync shared-mime-info smartmontools source-highlight spirv-tools \
    squashfs-tools sudo texinfo tslib wayland which xcb-proto xcb-util \
    xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil \
    xcb-util-wm xdg-utils xkeyboard-config xorgproto xxhash yaml-cpp zlib-ng)

WORKDIR /workspace

ENTRYPOINT ["/usr/bin/bash", "/workspace/ci/docker-build-iso.sh"]

