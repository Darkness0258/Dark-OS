"""First-run Welcome: the decisions, kept out of GTK so they can be tested.

darkos-welcome.py is a short tour, not a gate. Every page can be skipped and
nothing is installed or changed unless the user presses the button for it.

It replaces the old wofi prompts in darkos-firstboot-tools (performance
profile, then BlackArch tool groups). Those prompts wrote marker files in
~/.config/darkos; this module reads and writes the same names, so someone who
already answered there is not asked again.
"""
import os

LIVE_MARKER = "/run/archiso"          # exists on the live ISO only
BUILD_FILE = "/etc/darkos-build-sha"  # written at build time
DONE_NAME = "welcome.done"

PERFORMANCE_DONE = "firstboot-performance.done"
PERFORMANCE_DECLINED = "firstboot-performance.declined"
TOOLS_DONE = "firstboot-tools.done"
TOOLS_DECLINED = "firstboot-tools.declined"
# "Pick your extras" (the starter packs). Same rule as the others: asked once, and never again after an answer.
EXTRAS_DONE = "firstboot-extras.done"
EXTRAS_DECLINED = "firstboot-extras.declined"

# power-profiles-daemon names -> what the user reads.
PROFILE_LABELS = (
    ("performance", "Performance"),
    ("balanced", "Balanced"),
    ("power-saver", "Power saver"),
)

PAGES_INSTALLED = ("welcome", "look", "power", "extras", "tools", "finish")
# The live session keeps nothing across a reboot, so a tour of settings would
# only mislead. The live page offers the one thing that matters there.
PAGES_LIVE = ("welcome",)

TOOL_GROUPS_BIN = "/usr/local/bin/darkos-tool-groups"
VOID_BIN = "/usr/local/bin/the-void.sh"
INSTALLER_BIN = "/usr/local/bin/darkos-installer"


def config_dir(env=None):
    """~/.config/darkos, honouring XDG_CONFIG_HOME like the rest of the shell."""
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".config")
    return os.path.join(base, "darkos")


def is_live(live_marker=LIVE_MARKER):
    return os.path.isdir(live_marker)


def pages_for(live):
    return PAGES_LIVE if live else PAGES_INSTALLED


def is_done(cfg=None):
    return os.path.exists(os.path.join(cfg or config_dir(), DONE_NAME))


def should_show(first_run, live, done):
    """Autostart (`--first-run`) shows once; opening it from the Apps overlay
    always shows it. The live session is shown every boot, because it is the
    install entry point and its home directory never persists a marker."""
    if not first_run:
        return True
    if live:
        return True
    return not done


def build_id(path=BUILD_FILE):
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = f.read().strip()
    except OSError:
        return ""
    return value[:12] if value else ""


def write_marker(name, cfg=None):
    """Create an empty marker file. Returns False when the disk refuses."""
    cfg = cfg or config_dir()
    try:
        os.makedirs(cfg, exist_ok=True)
        with open(os.path.join(cfg, name), "a", encoding="utf-8"):
            pass
        return True
    except OSError:
        return False


def marker_exists(name, cfg=None):
    return os.path.exists(os.path.join(cfg or config_dir(), name))


def performance_pending(cfg=None):
    return not (marker_exists(PERFORMANCE_DONE, cfg) or marker_exists(PERFORMANCE_DECLINED, cfg))


def tools_pending(cfg=None):
    return not (marker_exists(TOOLS_DONE, cfg) or marker_exists(TOOLS_DECLINED, cfg))


def extras_pending(cfg=None):
    return not (marker_exists(EXTRAS_DONE, cfg) or marker_exists(EXTRAS_DECLINED, cfg))


def extras_argv(entries, cfg=None):
    """Terminal command that installs the ticked apps and writes the done marker only if every one installed.

    Raises ValueError for an empty pick, so a click with nothing ticked can never open a terminal.
    """
    from darkos_shell import store_actions
    cfg = cfg or config_dir()
    return store_actions.install_argv(entries, cfg, os.path.join(cfg, EXTRAS_DONE))


def parse_profiles(powerprofilesctl_list_output):
    """Profile ids the daemon actually offers, in display order.

    `powerprofilesctl list` prints blocks like `* balanced:` / `  performance:`.
    Only real profiles are offered; a machine whose daemon lists none gets no
    control rather than a button that cannot work.
    """
    offered = set()
    for line in (powerprofilesctl_list_output or "").splitlines():
        token = line.strip().lstrip("*").strip().rstrip(":")
        if line.strip().endswith(":") and token in dict(PROFILE_LABELS):
            offered.add(token)
    return [(pid, label) for pid, label in PROFILE_LABELS if pid in offered]


def active_profile(powerprofilesctl_list_output):
    """The profile marked with `*`, or None."""
    for line in (powerprofilesctl_list_output or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("*") and stripped.endswith(":"):
            token = stripped.lstrip("*").strip().rstrip(":")
            if token in dict(PROFILE_LABELS):
                return token
    return None


def tools_argv(marker_dir=None, cfg=None):
    """Command that opens the BlackArch tool-group picker in the Void.

    Same shape the first-boot script used: sudo runs the picker inside a
    visible terminal (so the password prompt and the install output are on
    screen), and the `done` marker is created only if the picker succeeded.
    """
    cfg = cfg or marker_dir or config_dir()
    return [
        VOID_BIN, "-e", "/bin/sh", "-c",
        'sudo "$1" && mkdir -p "$2" && touch "$3"',
        "darkos-welcome", TOOL_GROUPS_BIN, cfg, os.path.join(cfg, TOOLS_DONE),
    ]
