# Start the DarkOS desktop after an installed user logs in on TTY1.
# useradd copies this file from /etc/skel into every newly-created home.
if [ -f "$HOME/.bashrc" ]; then
    . "$HOME/.bashrc"
fi

if [ -z "${WAYLAND_DISPLAY:-}" ] && [ -z "${DISPLAY:-}" ] && [ "$(tty 2>/dev/null)" = "/dev/tty1" ]; then
    exec dbus-run-session -- start-hyprland
fi
