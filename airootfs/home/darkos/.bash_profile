# Auto-start Hyprland on TTY1 login
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    # getty autologin doesn't run the full pam_systemd session setup, so
    # XDG_RUNTIME_DIR may be missing — start-hyprland needs it for the
    # Wayland socket. Create it.
    if [ -z "${XDG_RUNTIME_DIR:-}" ] || [ ! -d "${XDG_RUNTIME_DIR}" ]; then
        export XDG_RUNTIME_DIR="/run/user/$(id -u)"
        mkdir -p "$XDG_RUNTIME_DIR"
        chmod 700 "$XDG_RUNTIME_DIR"
    fi
    # No login manager -> no session bus. dbus-run-session starts a fresh
    # bus for this session so Hyprland/polkit/portals/tray all get one.
    # NOTE: no exec here — if Hyprland crashes, the shell survives so the
    # error is visible instead of the session silently dying and getty
    # respawning forever.
    dbus-run-session -- start-hyprland 2>&1 | tee /tmp/hyprland-start.log
    echo ""
    echo "=== Hyprland exited with code ${PIPESTATUS[0]} ==="
    echo "Log: /tmp/hyprland-start.log"
    echo "Press Ctrl+D to log out, or run 'dbus-run-session -- start-hyprland' to retry."
fi
