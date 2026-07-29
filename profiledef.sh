#!/usr/bin/env bash

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
declare -A file_permissions=(
  ["/etc/sudoers.d/darkos"]="0:0:440"
  ["/home/darkos"]="1000:1000:750"
  ["/home/darkos/.bash_profile"]="1000:1000:644"
)
