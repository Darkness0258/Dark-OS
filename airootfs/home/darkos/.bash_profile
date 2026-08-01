# Auto-start Hyprland on TTY1 login
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    # getty autologin doesn't set up a login-manager session, so
    # XDG_RUNTIME_DIR (and WAYLAND_DISPLAY) may be missing. start-hyprland
    # needs XDG_RUNTIME_DIR to talk to the Wayland socket. Create it.
    if [ -z "${XDG_RUNTIME_DIR:-}" ] || [ ! -d "${XDG_RUNTIME_DIR}" ]; then
        export XDG_RUNTIME_DIR="/run/user/$(id -u)"
        mkdir -p "$XDG_RUNTIME_DIR"
        chmod 700 "$XDG_RUNTIME_DIR"
    fi
    exec start-hyprland
fi
