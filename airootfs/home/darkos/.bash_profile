# Auto-start Hyprland on TTY1 login
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    # getty autologin doesn't run the full pam_systemd session setup, so
    # XDG_RUNTIME_DIR and DBUS_SESSION_BUS_ADDRESS may be missing.
    # start-hyprland needs XDG_RUNTIME_DIR for the Wayland socket, and
    # Hyprland/polkit/portals need D-Bus. Create both if absent.
    if [ -z "${XDG_RUNTIME_DIR:-}" ] || [ ! -d "${XDG_RUNTIME_DIR}" ]; then
        export XDG_RUNTIME_DIR="/run/user/$(id -u)"
        mkdir -p "$XDG_RUNTIME_DIR"
        chmod 700 "$XDG_RUNTIME_DIR"
    fi
    if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -S "${XDG_RUNTIME_DIR}/bus" ]; then
        export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
    fi
    exec start-hyprland
fi
