#!/usr/bin/env python3
"""DarkOS Gaming Hub.

This app is deliberately a launcher and status surface, not a replacement for
Steam, Lutris, Bottles, Wine, Proton, or Waydroid.  It queries the real local
commands in a background thread, reports their output honestly, and starts a
hosted launcher or explicit compatibility UI only when its executable is
available.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, run_app  # noqa: E402

APP_ID = "org.darkos.Gaming"
WM_CLASS = "darkos-gaming"
PROBE_TIMEOUT_SECONDS = 5
BOTTLES_FLATPAK_ID = "com.usebottles.bottles"
WAYDROID_GUIDANCE = (
    "Waydroid needs initialized Android images and a running Wayland session. "
    "For first-time setup, run `sudo waydroid init` in The Void. "
    "Then start the container with `sudo systemctl start waydroid-container` "
    "and the session with `waydroid session start`. Refresh status afterwards."
)


@dataclass(frozen=True)
class LauncherSpec:
    """Describes one hosted game launcher exposed by the hub."""

    key: str
    name: str
    command: str
    icon_name: str


@dataclass(frozen=True)
class ToolStatus:
    """Represents an availability check without making UI code parse output."""

    name: str
    command: str
    executable: str | None
    available: bool
    probe_ok: bool
    summary: str
    details: str
    launch_arguments: tuple[str, ...] = ()


@dataclass(frozen=True)
class IntegrationAction:
    """Describes a locally guarded compatibility action exposed by the hub."""

    key: str
    label: str
    command: str
    arguments: tuple[str, ...]


LAUNCHERS: tuple[LauncherSpec, ...] = (
    LauncherSpec("steam", "Steam", "steam", "steam"),
    LauncherSpec("lutris", "Lutris", "lutris", "lutris"),
    LauncherSpec("bottles", "Bottles", "bottles", "wine"),
)
LAUNCHER_BY_KEY = {launcher.key: launcher for launcher in LAUNCHERS}

INTEGRATION_ACTIONS: tuple[IntegrationAction, ...] = (
    IntegrationAction("winecfg", "Wine configuration", "winecfg", ()),
    IntegrationAction("winetricks", "Open Winetricks", "winetricks", ()),
    IntegrationAction("waydroid-ui", "Open Waydroid", "waydroid", ("show-full-ui",)),
)
INTEGRATION_ACTION_BY_KEY = {action.key: action for action in INTEGRATION_ACTIONS}


def _compact_output(output: str, limit: int = 260) -> str:
    """Return command output as a short label-safe status string.

    Args:
        output: Raw stdout and stderr from a local command.
        limit: Maximum number of display characters to retain.

    Returns:
        A single-line summary suitable for a Gtk.Label.
    """
    lines = [" ".join(line.split()) for line in output.splitlines() if line.strip()]
    summary = " · ".join(lines[:3]) or "no output"
    return summary if len(summary) <= limit else f"{summary[: limit - 1].rstrip()}…"


def _run_probe(executable: str, arguments: tuple[str, ...]) -> tuple[bool, str]:
    """Run a short read-only tool probe and return its real result.

    Args:
        executable: Resolved executable path to invoke without a shell.
        arguments: Version or status arguments for the executable.

    Returns:
        A success flag and a concise description of stdout, stderr, or failure.
    """
    try:
        completed = subprocess.run(
            [executable, *arguments],
            capture_output=True,
            check=False,
            errors="replace",
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f"did not respond within {PROBE_TIMEOUT_SECONDS} seconds"
    except OSError as error:
        return False, str(error) or type(error).__name__

    output = _compact_output(f"{completed.stdout}\n{completed.stderr}")
    if completed.returncode == 0:
        return True, output
    return False, f"exit code {completed.returncode}: {output}"


def _probe_version(name: str, command: str, arguments: tuple[str, ...]) -> ToolStatus:
    """Check a launcher's actual PATH availability and version command.

    Args:
        name: User-facing name for the command.
        command: Command resolved through the current session PATH.
        arguments: Non-interactive version arguments for the command.

    Returns:
        A status that distinguishes missing commands from failed version probes.
    """
    executable = shutil.which(command)
    if executable is None:
        return ToolStatus(
            name=name,
            command=command,
            executable=None,
            available=False,
            probe_ok=False,
            summary="Not installed — command is not on PATH.",
            details=f"DarkOS could not find `{command}` in this session's PATH.",
        )

    probe_ok, output = _run_probe(executable, arguments)
    details = f"Command: {executable}\nProbe: {command} {' '.join(arguments)}\n{output}"
    if probe_ok:
        return ToolStatus(
            name=name,
            command=command,
            executable=executable,
            available=True,
            probe_ok=True,
            summary=f"Available — {output}",
            details=details,
        )
    return ToolStatus(
        name=name,
        command=command,
        executable=executable,
        available=True,
        probe_ok=False,
        summary=f"Command found, but version check failed — {output}",
        details=details,
    )


def _probe_launcher(launcher: LauncherSpec) -> ToolStatus:
    """Read installation metadata without running a launcher or its updater."""
    executable = shutil.which(launcher.command)
    if executable is not None:
        package_manager = shutil.which("pacman")
        metadata_ok, metadata = (
            _run_probe(package_manager, ("-Q", launcher.command))
            if package_manager is not None
            else (False, "Package metadata is unavailable.")
        )
        return ToolStatus(
            launcher.name, launcher.command, executable, True, True,
            f"Available — {metadata}" if metadata_ok else "Available — executable found.",
            f"Command: {executable}\n{metadata}\nThe launcher was not started for this check.",
        )

    if launcher.key == "bottles":
        flatpak = shutil.which("flatpak")
        if flatpak is not None:
            found, version = _run_probe(flatpak, ("info", "--show-version", BOTTLES_FLATPAK_ID))
            if found:
                return ToolStatus(
                    launcher.name, "flatpak", flatpak, True, True,
                    f"Available via Flatpak — {version}",
                    f"Installed Flatpak: {BOTTLES_FLATPAK_ID}\nVersion: {version}",
                    ("run", BOTTLES_FLATPAK_ID),
                )
        detail = (
            f"Neither a native Bottles command nor the installed Flatpak {BOTTLES_FLATPAK_ID} "
            "was found. Bottles is optional; install it from its official Flatpak package "
            "and then refresh. No download is started by this hub."
        )
    else:
        detail = f"DarkOS could not find `{launcher.command}` in this session's PATH."
    return ToolStatus(
        launcher.name, launcher.command, None, False, False,
        "Not installed — no local launcher found.", detail,
    )


def _find_steam_proton() -> Path | None:
    """Find a locally installed Steam-managed Proton script without scanning disks.

    Steam installs Proton beneath a small number of conventional library paths.
    Only immediate children of those directories are inspected, keeping a status
    refresh quick and avoiding an expensive or privacy-surprising home scan.

    Returns:
        An executable Proton script when one is found, otherwise None.
    """
    home = Path.home()
    roots: tuple[tuple[Path, bool], ...] = (
        (home / ".local/share/Steam/steamapps/common", True),
        (home / ".steam/steam/steamapps/common", True),
        (home / ".var/app/com.valvesoftware.Steam/data/Steam/steamapps/common", True),
        (home / ".local/share/Steam/compatibilitytools.d", False),
        (home / ".steam/root/compatibilitytools.d", False),
        (Path("/usr/share/steam/compatibilitytools.d"), False),
    )
    checked_roots: set[Path] = set()

    for root, require_proton_name in roots:
        try:
            resolved_root = root.resolve()
        except OSError:
            resolved_root = root
        if resolved_root in checked_roots:
            continue
        checked_roots.add(resolved_root)

        try:
            children = tuple(root.iterdir())
        except OSError:
            continue
        for child in children:
            if require_proton_name and not child.name.casefold().startswith("proton"):
                continue
            candidate = child / "proton"
            try:
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return candidate
            except OSError:
                continue
    return None


def _steam_proton_version(proton_script: Path) -> str:
    """Read Steam's accompanying Proton version file when it is present.

    Running a Steam-managed ``proton`` script solely for ``--version`` can try
    to initialise a compatibility prefix.  The adjacent version file is the
    non-mutating source Steam provides for this purpose.

    Args:
        proton_script: The executable ``proton`` file found in a Steam library.

    Returns:
        A concise version string or a truthful fallback based on the directory.
    """
    version_file = proton_script.parent / "version"
    try:
        with version_file.open("r", encoding="utf-8", errors="replace") as handle:
            version = _compact_output(handle.read(512), limit=180)
    except OSError:
        version = "version file not available"
    return version if version != "no output" else proton_script.parent.name


def _probe_proton() -> ToolStatus:
    """Report either a standalone Proton command or Steam-managed Proton state."""
    standalone = shutil.which("proton")
    if standalone is not None:
        proton_script = Path(standalone)
        version = _steam_proton_version(proton_script)
        return ToolStatus(
            name="Proton", command="proton", executable=standalone,
            available=True, probe_ok=True,
            summary=f"Proton command available — {version}",
            details=f"Command: {standalone}\nProton was not executed for this status check.",
        )

    proton_script = _find_steam_proton()
    if proton_script is None:
        return ToolStatus(
            name="Proton",
            command="proton",
            executable=None,
            available=False,
            probe_ok=False,
            summary="Not found on PATH or in standard Steam libraries.",
            details=(
                "No standalone `proton` command or Steam-managed Proton script was found "
                "in the standard Steam library locations."
            ),
        )

    version = _steam_proton_version(proton_script)
    return ToolStatus(
        name="Proton",
        command="proton",
        executable=str(proton_script),
        available=True,
        probe_ok=True,
        summary=f"Steam-managed Proton available — {version}",
        details=(
            f"Steam-managed Proton script: {proton_script}\n"
            f"Version source: {proton_script.parent / 'version'}\n{version}"
        ),
    )


def _probe_waydroid() -> ToolStatus:
    """Check Waydroid's real CLI and its current service/session status."""
    executable = shutil.which("waydroid")
    if executable is None:
        return ToolStatus(
            name="Waydroid",
            command="waydroid",
            executable=None,
            available=False,
            probe_ok=False,
            summary="Not installed — command is not on PATH.",
            details="DarkOS could not find `waydroid` in this session's PATH.",
        )

    probe_ok, output = _run_probe(executable, ("status",))
    details = f"Command: {executable}\nProbe: waydroid status\n{output}\n\n{WAYDROID_GUIDANCE}"
    if probe_ok:
        return ToolStatus(
            name="Waydroid",
            command="waydroid",
            executable=executable,
            available=True,
            probe_ok=True,
            summary=f"Installed — {output}",
            details=details,
        )
    return ToolStatus(
        name="Waydroid",
        command="waydroid",
        executable=executable,
        available=True,
        probe_ok=False,
        summary=f"Command found, but status check failed — {output}",
        details=details,
    )


def _collect_statuses() -> dict[str, ToolStatus]:
    """Collect all launcher and compatibility status checks off the GTK thread."""
    statuses = {
        launcher.key: _probe_launcher(launcher)
        for launcher in LAUNCHERS
    }
    statuses["wine"] = _probe_version("Wine", "wine", ("--version",))
    statuses["proton"] = _probe_proton()
    statuses["waydroid"] = _probe_waydroid()
    return statuses


def _collect_action_paths() -> dict[str, str | None]:
    """Resolve action commands off the GTK thread without running their GUIs."""
    return {action.key: shutil.which(action.command) for action in INTEGRATION_ACTIONS}


def _run_waydroid_action(executable: str) -> tuple[bool, str]:
    """Open an already-running session and retain Waydroid's real diagnostics.

    Requiring an existing session prevents show-full-ui from implicitly starting
    its long-running session manager. Initialization remains an explicit terminal
    operation, and this bounded request can finish without starting root helpers.
    """
    status_ok, status = _run_probe(executable, ("status",))
    session_running = re.search(r"Session:\s*RUNNING\b", status, re.IGNORECASE)
    container_running = re.search(r"Container:\s*(?:RUNNING|FROZEN)\b", status, re.IGNORECASE)
    if not status_ok or not session_running or not container_running:
        return False, f"Waydroid is not ready to open.\n{status}\n\n{WAYDROID_GUIDANCE}"
    success, output = _run_probe(executable, ("show-full-ui",))
    # Some Waydroid error paths only log a message and still return zero.
    logged_error = any(
        marker in output.casefold()
        for marker in ("failed", "error", "not initialized", "session is stopped")
    )
    return success and not logged_error, output


class GamingWindow(Gtk.ApplicationWindow):
    """GTK window for launching game platforms and reviewing compatibility state."""

    def __init__(self, app: Gtk.Application) -> None:
        """Create the Gaming Hub and start its non-blocking status refresh."""
        super().__init__(application=app, title="Gaming Hub")
        self.set_default_size(780, 590)
        add_class(self, "app-window")

        self._generation = 0
        self._closed = False
        self._refreshing = False
        self._status_labels: dict[str, Gtk.Label] = {}
        self._status_icons: dict[str, Gtk.Image] = {}
        self._launch_buttons: dict[str, Gtk.Button] = {}
        self._action_buttons: dict[str, Gtk.Button] = {}
        self._statuses: dict[str, ToolStatus] = {}
        self._waydroid_pending = False

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.add(scroll)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_border_width(16)
        scroll.add(root)

        root.pack_start(
            Gtk.Label(label="<b>Gaming Hub</b>", xalign=0, use_markup=True),
            False,
            False,
            0,
        )
        root.pack_start(
            Gtk.Label(
                label=(
                    "Launch your installed game platforms and inspect the compatibility "
                    "layers they rely on. DarkOS checks the local commands; it does not "
                    "install or configure them automatically."
                ),
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            0,
        )

        platform_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        platform_header.pack_start(
            Gtk.Label(label="<b>Game platforms</b>", xalign=0, use_markup=True),
            True,
            True,
            0,
        )
        self._refresh_button = Gtk.Button(label="Refresh status")
        add_class(self._refresh_button, "icon-button")
        self._refresh_button.connect("clicked", self._on_refresh)
        platform_header.pack_start(self._refresh_button, False, False, 0)
        root.pack_start(platform_header, False, False, 4)

        for launcher in LAUNCHERS:
            root.pack_start(self._build_launcher_row(launcher), False, False, 0)

        self._summary_label = Gtk.Label(
            label="Checking installed launchers and compatibility tools…",
            xalign=0,
            wrap=True,
        )
        add_class(self._summary_label, "path-crumb")
        root.pack_start(self._summary_label, False, False, 0)

        root.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
        root.pack_start(
            Gtk.Label(label="<b>Compatibility</b>", xalign=0, use_markup=True),
            False,
            False,
            0,
        )
        root.pack_start(
            Gtk.Label(
                label=(
                    "Wine supports Windows applications, Proton supports Windows games "
                    "inside Steam, and Waydroid supplies Android app compatibility. "
                    "Proton is status-only here; manage Proton versions in Steam."
                ),
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            0,
        )
        for key, name, icon_name in (
            ("wine", "Wine", "wine"),
            ("proton", "Proton", "applications-games-symbolic"),
            ("waydroid", "Waydroid", "smartphone-symbolic"),
        ):
            root.pack_start(self._build_status_row(key, name, icon_name), False, False, 0)

        root.pack_start(
            Gtk.Label(label="<b>Compatibility actions</b>", xalign=0, use_markup=True),
            False,
            False,
            4,
        )
        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for action in INTEGRATION_ACTIONS:
            action_row.pack_start(self._build_action_button(action), False, False, 0)
        root.pack_start(action_row, False, False, 0)
        root.pack_start(
            Gtk.Label(label=WAYDROID_GUIDANCE, xalign=0, wrap=True), False, False, 0,
        )
        self._action_feedback_label = Gtk.Label(
            label="Checking compatibility action commands…",
            xalign=0,
            wrap=True,
        )
        add_class(self._action_feedback_label, "path-crumb")
        root.pack_start(self._action_feedback_label, False, False, 0)

        root.pack_start(
            Gtk.Label(
                label=(
                    "If a command is missing, install it through your preferred package "
                    "source, then refresh. A command that exists but cannot report its "
                    "version or service state stays launchable and shows the real failure."
                ),
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            4,
        )

        self.connect("destroy", self._on_destroy)
        self._start_status_refresh()

    def _build_launcher_row(self, launcher: LauncherSpec) -> Gtk.Box:
        """Build one launcher row with availability state and a guarded launch button."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        add_class(row, "sidebar-row")

        icon = Gtk.Image.new_from_icon_name(launcher.icon_name, Gtk.IconSize.LARGE_TOOLBAR)
        row.pack_start(icon, False, False, 0)

        text_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_column.set_hexpand(True)
        text_column.pack_start(
            Gtk.Label(label=f"<b>{launcher.name}</b>", xalign=0, use_markup=True),
            False,
            False,
            0,
        )
        status_label = Gtk.Label(label="Checking…", xalign=0, wrap=True)
        status_label.set_max_width_chars(80)
        text_column.pack_start(status_label, False, False, 0)
        row.pack_start(text_column, True, True, 0)

        launch_button = Gtk.Button(label="Launch")
        add_class(launch_button, "action-button")
        launch_button.set_sensitive(False)
        launch_button.set_tooltip_text(f"Checking whether {launcher.name} is available")
        launch_button.connect("clicked", lambda _button, key=launcher.key: self._launch(key))
        row.pack_start(launch_button, False, False, 0)

        self._status_labels[launcher.key] = status_label
        self._launch_buttons[launcher.key] = launch_button
        return row

    def _build_status_row(self, key: str, name: str, icon_name: str) -> Gtk.Box:
        """Build a read-only compatibility status row."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        add_class(row, "sidebar-row")

        status_icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.LARGE_TOOLBAR)
        row.pack_start(status_icon, False, False, 0)

        text_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_column.set_hexpand(True)
        text_column.pack_start(
            Gtk.Label(label=f"<b>{name}</b>", xalign=0, use_markup=True),
            False,
            False,
            0,
        )
        status_label = Gtk.Label(label="Checking…", xalign=0, wrap=True)
        status_label.set_max_width_chars(80)
        text_column.pack_start(status_label, False, False, 0)
        row.pack_start(text_column, True, True, 0)

        self._status_labels[key] = status_label
        self._status_icons[key] = status_icon
        return row

    def _build_action_button(self, action: IntegrationAction) -> Gtk.Button:
        """Build an action button that remains disabled until its command is found."""
        button = Gtk.Button(label=action.label)
        add_class(button, "action-button")
        button.set_sensitive(False)
        button.set_tooltip_text(f"Checking whether {action.command} is available")
        button.connect("clicked", lambda _button, key=action.key: self._launch_action(key))
        self._action_buttons[action.key] = button
        return button

    def _on_destroy(self, *_unused: object) -> None:
        """Mark the window closed so a late probe callback changes no GTK state."""
        self._closed = True

    def _on_refresh(self, *_unused: object) -> None:
        """Refresh all real command state when the user requests it."""
        self._start_status_refresh()

    def _start_status_refresh(self) -> None:
        """Start a background status probe so slow tools never freeze the UI."""
        if self._closed or self._refreshing:
            return
        self._refreshing = True
        self._generation += 1
        generation = self._generation
        self._refresh_button.set_sensitive(False)
        self._summary_label.set_text("Checking installed launchers and compatibility tools…")
        for launch_button in self._launch_buttons.values():
            launch_button.set_sensitive(False)
            launch_button.set_tooltip_text("Refreshing command availability…")
        for action_button in self._action_buttons.values():
            action_button.set_sensitive(False)
            action_button.set_tooltip_text("Refreshing command availability…")
        if not self._waydroid_pending:
            self._action_feedback_label.set_text("Checking compatibility action commands…")
        threading.Thread(
            target=self._status_worker,
            args=(generation,),
            name="darkos-gaming-status",
            daemon=True,
        ).start()

    def _status_worker(self, generation: int) -> None:
        """Collect tool results outside GTK, including an unexpected-error fallback."""
        try:
            statuses = _collect_statuses()
            action_paths = _collect_action_paths()
        except Exception as error:  # Keep a tool probe from crashing the launcher UI.
            detail = str(error) or type(error).__name__
            statuses = {
                key: ToolStatus(
                    name=key.title(),
                    command=key,
                    executable=None,
                    available=False,
                    probe_ok=False,
                    summary=f"Status check failed — {detail}",
                    details=detail,
                )
                for key in (*LAUNCHER_BY_KEY, "wine", "proton", "waydroid")
            }
            action_paths = {action.key: None for action in INTEGRATION_ACTIONS}
        GLib.idle_add(self._apply_statuses, generation, statuses, action_paths)

    def _apply_statuses(
        self,
        generation: int,
        statuses: dict[str, ToolStatus],
        action_paths: dict[str, str | None],
    ) -> bool:
        """Apply a completed probe on GTK's main thread.

        Args:
            generation: Refresh generation associated with ``statuses``.
            statuses: Fresh status values collected by the worker thread.
            action_paths: Resolved commands for guarded compatibility actions.

        Returns:
            False so GLib removes this one-shot idle callback.
        """
        if self._closed or generation != self._generation:
            return False

        self._statuses = statuses
        self._refreshing = False
        available_count = 0
        for key, status in statuses.items():
            status_label = self._status_labels.get(key)
            if status_label is not None:
                status_label.set_text(status.summary)
                status_label.set_tooltip_text(status.details)

            status_icon = self._status_icons.get(key)
            if status_icon is not None:
                icon_name = "emblem-ok-symbolic" if status.probe_ok else "dialog-warning-symbolic"
                status_icon.set_from_icon_name(icon_name, Gtk.IconSize.LARGE_TOOLBAR)

            launch_button = self._launch_buttons.get(key)
            if launch_button is not None:
                launch_button.set_sensitive(status.available)
                if status.available:
                    launch_button.set_tooltip_text(f"Launch {status.name}")
                else:
                    launch_button.set_tooltip_text(
                        f"{status.name} is not installed. Install it, then refresh status."
                    )

            if status.available:
                available_count += 1

        available_actions: list[str] = []
        missing_actions: list[str] = []
        for action in INTEGRATION_ACTIONS:
            action_button = self._action_buttons[action.key]
            executable = action_paths.get(action.key)
            action_button.set_sensitive(
                executable is not None and not (action.key == "waydroid-ui" and self._waydroid_pending)
            )
            if executable is None:
                action_button.set_tooltip_text(
                    f"{action.command} is not installed. Install it, then refresh status."
                )
                missing_actions.append(action.command)
            else:
                action_button.set_tooltip_text(f"Start {action.label} ({executable})")
                available_actions.append(action.label)

        action_summary = (
            f"Available actions: {', '.join(available_actions)}."
            if available_actions
            else "No compatibility action commands are available."
        )
        if missing_actions:
            action_summary += f" Missing commands: {', '.join(missing_actions)}."
        if not self._waydroid_pending:
            self._action_feedback_label.set_text(action_summary)
        self._refresh_button.set_sensitive(True)
        self._summary_label.set_text(
            "Status checked: "
            f"{available_count} of {len(statuses)} commands or managed tools available."
        )
        return False

    def _launch(self, key: str) -> None:
        """Launch an installed hosted platform, or display a useful failure dialog."""
        launcher = LAUNCHER_BY_KEY[key]
        status = self._statuses.get(key)
        if status is None or status.executable is None:
            self._show_message(f"{launcher.name} is unavailable. Refresh status and try again.", error=True)
            return
        if not self._start_command(launcher.name, status.executable, status.launch_arguments):
            self._start_status_refresh()
            return
        self._summary_label.set_text(
            f"Launch requested for {launcher.name}. If it does not open, "
            "refresh status for its real command state."
        )

    def _launch_action(self, key: str) -> None:
        """Run a guarded Wine, Winetricks, or Waydroid integration action."""
        action = INTEGRATION_ACTION_BY_KEY[key]
        if key == "waydroid-ui":
            if self._waydroid_pending:
                return
            executable = shutil.which(action.command)
            if executable is None:
                self._show_message("Waydroid is no longer available. Refresh status.", error=True)
                return
            self._waydroid_pending = True
            self._action_buttons[key].set_sensitive(False)
            self._action_feedback_label.set_text("Checking the Waydroid session and opening its UI…")
            threading.Thread(
                target=self._waydroid_worker, args=(executable,),
                name="darkos-gaming-waydroid", daemon=True,
            ).start()
            return
        if not self._start_command(action.label, action.command, action.arguments):
            self._start_status_refresh()
            return
        self._action_feedback_label.set_text(
            f"Launch requested for {action.label}. Follow its own UI for progress or errors."
        )

    def _waydroid_worker(self, executable: str) -> None:
        """Check and open Waydroid without blocking GTK or discarding errors."""
        try:
            success, output = _run_waydroid_action(executable)
        except Exception as error:
            success, output = False, str(error) or type(error).__name__
        GLib.idle_add(self._finish_waydroid_action, success, output)

    def _finish_waydroid_action(self, success: bool, output: str) -> bool:
        """Display a finished request only while this window remains alive."""
        if self._closed:
            return False
        self._waydroid_pending = False
        self._action_buttons["waydroid-ui"].set_sensitive(not self._refreshing)
        self._action_feedback_label.set_text(
            f"Waydroid UI request finished: {output}" if success else f"Waydroid could not open: {output}"
        )
        if not success:
            self._show_message(output, error=True)
        return False

    def _start_command(self, label: str, command: str, arguments: tuple[str, ...]) -> bool:
        """Start a resolved command without a shell and report a launch failure.

        Args:
            label: User-facing action name shown in errors.
            command: Command expected on the active session PATH.
            arguments: Fixed, non-user-supplied arguments for the command.

        Returns:
            True when the process was requested successfully, otherwise False.
        """
        executable = shutil.which(command)
        if executable is None:
            self._show_message(
                f"{label} is no longer available on PATH. "
                "Install it or refresh the status.",
                error=True,
            )
            return False
        try:
            subprocess.Popen(
                [executable, *arguments],
                close_fds=True,
                start_new_session=True,
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
            )
        except OSError as error:
            self._show_message(
                f"Could not start {label}: {str(error) or type(error).__name__}\n\n"
                "Check that the launcher is installed and that your desktop session can start it.",
                error=True,
            )
            return False
        return True

    def _show_message(self, message: str, error: bool = False) -> None:
        """Show a bounded user-facing error or informational dialog."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=message[:2000],
        )
        dialog.run()
        dialog.destroy()


def build_window(app: Gtk.Application) -> GamingWindow:
    """Build the application's main window for ``run_app``."""
    return GamingWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
