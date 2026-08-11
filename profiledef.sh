#!/usr/bin/env bash
# shellcheck shell=bash disable=SC2034

iso_name="darkos"
iso_label="DARKOS"
iso_publisher="DarkOS"
iso_application="DarkOS Arch + Hyprland live/install image"
iso_version="$(date +%Y.%m.%d)"
install_dir="arch"
buildmodes=('iso')
bootmodes=('uefi.systemd-boot')
arch="x86_64"
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
# mkarchiso pre-declares this associative array and sources profiledef.sh from
# inside a function. Using `declare -A` here would create a function-local
# variable which disappears when profile loading returns, leaving mkarchiso's
# global permission map empty and resetting every copied script to 0644.
file_permissions=(
  ["/etc/gshadow"]="0:0:600"
  ["/etc/shadow"]="0:0:600"
  ["/etc/sudoers.d"]="0:0:750"
  ["/etc/sudoers.d/darkos"]="0:0:440"
  ["/home/darkos"]="1000:1000:750"
  ["/home/darkos/.bash_profile"]="1000:1000:644"
  ["/root"]="0:0:750"
  ["/root/.automated_script.sh"]="0:0:755"
  ["/root/.gnupg"]="0:0:700"
  ["/etc/darkos-build-sha"]="0:0:644"
  ["/etc/greetd/config.toml"]="0:0:644"
  ["/etc/greetd/regreet.toml"]="0:0:644"
  ["/etc/greetd/regreet.css"]="0:0:644"
  ["/etc/plymouth/plymouthd.conf"]="0:0:644"
  ["/etc/xdg/hypr/hypridle.conf"]="0:0:644"
  ["/etc/xdg/hypr/hyprlock.conf"]="0:0:644"
  ["/usr/share/plymouth/themes/darkos/darkos.png"]="0:0:644"
  ["/usr/share/plymouth/themes/darkos/darkos.plymouth"]="0:0:644"
  ["/usr/share/plymouth/themes/darkos/darkos.script"]="0:0:644"
  ["/usr/share/wayland-sessions/darkos.desktop"]="0:0:644"
  ["/usr/local/bin/choose-mirror"]="0:0:755"
  ["/usr/local/bin/Installation_guide"]="0:0:755"
  ["/usr/local/bin/livecd-sound"]="0:0:755"
  ["/usr/local/bin/darkos-grub-install.sh"]="0:0:755"
  ["/usr/local/bin/the-void.sh"]="0:0:755"
  ["/usr/local/bin/darkos-tty1-login"]="0:0:755"
  ["/usr/local/bin/darkos-tool-groups"]="0:0:755"
  ["/usr/local/bin/darkos-diagnose.sh"]="0:0:755"
  ["/usr/local/bin/darkos-shell.py"]="0:0:755"
  ["/usr/local/bin/darkos-installer"]="0:0:755"
  ["/usr/local/bin/darkos-lock"]="0:0:755"
  ["/usr/local/bin/start-hyprland"]="0:0:755"
  ["/usr/local/bin/darkos-firstboot-tools"]="0:0:755"
)
