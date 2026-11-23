"""What the Store does to the system, kept out of GTK so it can be tested.

Three kinds of thing live here:

* the shell scripts that run in the visible terminal (install and remove), built
  from constant text plus positional arguments, never from interpolated strings;
* the safe deletion of an app's own data, restricted to folders the catalogue
  names, inside the person's home, and never followed through a symlink;
* parsers for what pacman and Flatpak print (sizes, permissions, autostart).

Nothing here runs on import and nothing runs a command except through the `run`
callable the caller passes in. The module is GTK-free on purpose: the terminal
runs `python3 .../darkos_shell/store_actions.py forget <app-id>` after a
removal, and that must not drag a toolkit in just to delete a folder.
"""
import configparser
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from darkos_shell import store_catalog
except ImportError:  # run directly as a script from inside the darkos_shell folder
    import store_catalog

VOID_BIN = "/usr/local/bin/the-void.sh"
GATE_BIN = "/usr/local/bin/darkos-store-gated-install.py"
SELF_PATH = "/usr/local/bin/darkos_shell/store_actions.py"

ENTRY_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PACMAN_NAME = re.compile(r"^[a-z0-9@_+][a-z0-9@._+-]*$")
FLATPAK_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_-]*){2,}$")


# --- names that reach a command line -----------------------------------------------------------------------------

def check_entry(entry):
    """Raise ValueError unless every name of this entry is safe to put on a command line."""
    if not ENTRY_ID.match(entry.id or ""):
        raise ValueError(f"bad app id: {entry.id!r}")
    if entry.source not in store_catalog.SOURCES:
        raise ValueError(f"{entry.id}: unknown source {entry.source!r}")
    if not entry.packages:
        raise ValueError(f"{entry.id}: no packages")
    pattern = PACMAN_NAME if entry.source == store_catalog.SOURCE_PACMAN else FLATPAK_ID
    for name in entry.packages:
        if not pattern.match(name or ""):
            raise ValueError(f"{entry.id}: bad {entry.source} name {name!r}")
    if entry.source == store_catalog.SOURCE_FLATPAK and len(entry.packages) != 1:
        raise ValueError(f"{entry.id}: a Flatpak entry is exactly one application id")


# --- scripts that run in the visible terminal --------------------------------------------------------------------

# Arguments: $1 config dir ("" for none), $2 marker file ("" for none), $3 how many pacman packages follow, then the
# pacman packages, then the Flatpak application ids. Every pacman package goes through Shield's gate, one by one; the
# marker is written only if nothing failed.
_INSTALL_SCRIPT = f"""\
cfg="$1"; marker="$2"; n="$3"; shift 3
failed=""
i=0
while [ "$i" -lt "$n" ]; do
  pkg="$1"; shift; i=$((i+1))
  sudo python3 {GATE_BIN} -- "$pkg" || failed="$failed $pkg"
done
if [ "$#" -gt 0 ]; then
  if flatpak remote-add --user --if-not-exists {store_catalog.FLATHUB_REMOTE} {store_catalog.FLATHUB_URL}; then
    for ref in "$@"; do
      flatpak install --user --noninteractive -y {store_catalog.FLATHUB_REMOTE} "$ref" || failed="$failed $ref"
    done
  else
    failed="$failed {store_catalog.FLATHUB_REMOTE}"
  fi
fi
if [ -z "$failed" ]; then
  result=0
  if [ -n "$marker" ]; then mkdir -p "$cfg" && touch "$marker"; fi
  printf '\\nEverything you picked is installed.\\n'
else
  result=1
  printf '\\nThese did not install:%s\\n' "$failed"
fi
printf 'Press Enter to close this window.\\n'
read -r reply
exit "$result"
"""

# Arguments: $1 "1" to also delete the app's data, $2 the app id, then the installed pacman packages to remove.
# The data is deleted only after pacman reports success, so a refused removal never costs anyone their data.
_REMOVE_PACMAN_SCRIPT = f"""\
forget="$1"; id="$2"; shift 2
sudo pacman -Rns -- "$@"
result=$?
if [ "$result" -eq 0 ] && [ "$forget" = "1" ]; then
  python3 {SELF_PATH} forget "$id" || result=1
fi
if [ "$result" -eq 0 ]; then printf '\\nRemoved.\\n'; else printf '\\nNot removed (exit %s).\\n' "$result"; fi
printf 'Press Enter to close this window.\\n'
read -r reply
exit "$result"
"""

# Arguments: $1 "1" to also delete the app's data, $2 the Flatpak application id.
_REMOVE_FLATPAK_SCRIPT = """\
if [ "$1" = "1" ]; then
  flatpak uninstall --user --noninteractive -y --delete-data -- "$2"
else
  flatpak uninstall --user --noninteractive -y -- "$2"
fi
result=$?
if [ "$result" -eq 0 ]; then printf '\\nRemoved.\\n'; else printf '\\nNot removed (exit %s).\\n' "$result"; fi
printf 'Press Enter to close this window.\\n'
read -r reply
exit "$result"
"""


def install_argv(entries, config_dir="", marker=""):
    """Terminal command that installs these entries: pacman ones through Shield's gate, Flatpak ones from Flathub.

    `marker`, when given, is a file created (inside `config_dir`) only if every item installed.
    """
    for entry in entries:
        check_entry(entry)
    pacman, flatpak = store_catalog.packages_of(entries)
    if not pacman and not flatpak:
        raise ValueError("nothing to install")
    return [VOID_BIN, "-e", "/bin/sh", "-c", _INSTALL_SCRIPT, "darkos-store",
            config_dir, marker, str(len(pacman)), *pacman, *flatpak]


def remove_argv(entry, installed_packages=(), forget_data=False):
    """Terminal command that removes one entry, optionally deleting its app data afterwards.

    For a pacman entry only the packages in `installed_packages` are passed to pacman (naming a package that is not
    installed makes pacman refuse the whole command).
    """
    check_entry(entry)
    flag = "1" if forget_data else "0"
    if entry.source == store_catalog.SOURCE_FLATPAK:
        return [VOID_BIN, "-e", "/bin/sh", "-c", _REMOVE_FLATPAK_SCRIPT, "darkos-store", flag, entry.packages[0]]
    names = [name for name in entry.packages if name in set(installed_packages)]
    if not names:
        raise ValueError(f"{entry.id} is not installed")
    return [VOID_BIN, "-e", "/bin/sh", "-c", _REMOVE_PACMAN_SCRIPT, "darkos-store", flag, entry.id, *names]


# --- what is installed -------------------------------------------------------------------------------------------

def parse_name_list(output):
    """One name per line (`pacman -Qq`, `flatpak list --app --columns=application`) -> set."""
    return {line.strip() for line in (output or "").splitlines() if line.strip()}


def entry_state(entry, pacman_installed, flatpak_installed):
    """"installed", "partial" (some packages of a multi-package entry) or "absent"."""
    have = flatpak_installed if entry.source == store_catalog.SOURCE_FLATPAK else pacman_installed
    present = [name in have for name in entry.packages]
    if all(present):
        return "installed"
    return "partial" if any(present) else "absent"


# --- sizes -------------------------------------------------------------------------------------------------------

_UNITS = {"b": 1, "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4,
          "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4}


def parse_size(text):
    """"12.34 MiB" (pacman, binary) or "107.8 MB" (Flatpak, decimal) -> bytes, or None if it is not a size.

    "< 1 kB" is read as its bound (1000), since that is all that is known.
    """
    match = re.match(r"^\s*(?:<\s*)?([0-9]+(?:[.,][0-9]+)?)\s*([A-Za-z]+)\s*$", text or "")
    if not match:
        return None
    unit = _UNITS.get(match.group(2).lower())
    if unit is None:
        return None
    return int(round(float(match.group(1).replace(",", ".")) * unit))


def _field(output, label):
    for line in (output or "").splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == label:
            return value.strip()
    return None


def parse_pacman_si(output):
    """`LC_ALL=C pacman -Si pkg` -> {"download": bytes|None, "installed": bytes|None} for that one package."""
    return {"download": parse_size(_field(output, "Download Size")),
            "installed": parse_size(_field(output, "Installed Size"))}


def parse_print_sizes(output):
    """`pacman -Sp --print-format %s a b` -> (number of packages to download, total bytes).

    Anything that is not a plain integer line (warnings, "error: target not found") is ignored, so the caller must
    look at the exit status before trusting an empty result.
    """
    sizes = [int(line) for line in (output or "").splitlines() if line.strip().isdigit()]
    return len(sizes), sum(sizes)


def parse_flatpak_remote_info(output):
    """`LC_ALL=C flatpak remote-info remote ref` -> {"download": bytes|None, "installed": bytes|None}."""
    return {"download": parse_size(_field(output, "Download")),
            "installed": parse_size(_field(output, "Installed"))}


def human_size(num_bytes):
    """Bytes as the person reads them; None is "Unknown", never a made-up number."""
    if num_bytes is None:
        return "Unknown"
    value = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return "Unknown"


# --- permissions (Flatpak) and autostart -------------------------------------------------------------------------

@dataclass(frozen=True)
class Permission:
    text: str
    broad: bool = False   # worth a second look: wide file access, every device, key agents, whole buses


_SHARED = {"network": ("Uses the network", False)}
_SOCKETS = {"pulseaudio": ("Plays and records sound", False), "cups": ("Can print", False),
            "ssh-auth": ("Uses your SSH keys", True), "gpg-agent": ("Uses your GPG keys", True),
            "pcsc": ("Reads smart cards", True), "system-bus": ("Full system message bus", True),
            "session-bus": ("Full session message bus", True)}
_QUIET_SOCKETS = {"x11", "wayland", "fallback-x11", "inherit-wayland-socket"}   # just "shows a window"
_DEVICES = {"all": ("Every device", True), "dri": ("Graphics acceleration", False),
            "kvm": ("Virtualisation", False), "input": ("Input devices and game controllers", False)}
_QUIET_DEVICES = {"shm"}
_FILESYSTEMS = {"host": ("Every file on this computer", True), "host-os": ("System files (read-only)", False),
                "host-etc": ("System settings files (read-only)", False), "home": ("Your whole home folder", True),
                "xdg-download": ("Downloads folder", False), "xdg-documents": ("Documents folder", False),
                "xdg-pictures": ("Pictures folder", False), "xdg-music": ("Music folder", False),
                "xdg-videos": ("Videos folder", False), "xdg-desktop": ("Desktop folder", False)}


def parse_permissions(metadata_text):
    """Flatpak metadata (`flatpak remote-info --show-metadata`) -> list of Permission, in a stable order.

    Reads only the [Context] section. Anything it has no plain wording for is listed as the raw token rather than
    dropped, so the list never hides a permission it does not understand. Returns [] for empty or unreadable input.
    """
    parser = configparser.RawConfigParser(strict=False, delimiters=("=",), interpolation=None)
    parser.optionxform = str
    try:
        parser.read_string(metadata_text or "")
    except configparser.Error:
        return []
    if not parser.has_section("Context"):
        return []

    def tokens(key):
        return [t for t in parser.get("Context", key, fallback="").split(";") if t]

    found = []

    def add(text, broad=False):
        if not any(item.text == text for item in found):
            found.append(Permission(text, broad))

    for token in tokens("shared"):
        if token in _SHARED:
            add(*_SHARED[token])
    for token in tokens("sockets"):
        if token in _SOCKETS:
            add(*_SOCKETS[token])
        elif token not in _QUIET_SOCKETS and not token.startswith("!"):
            add(f"Socket: {token}")
    for token in tokens("devices"):
        if token in _DEVICES:
            add(*_DEVICES[token])
        elif token not in _QUIET_DEVICES and not token.startswith("!"):
            add(f"Device: {token}")
    for token in tokens("filesystems"):
        if token.startswith("!"):
            continue
        path, _, mode = token.partition(":")
        suffix = {"ro": " (read-only)", "create": " (can create it)"}.get(mode, "")
        if path in _FILESYSTEMS:
            text, broad = _FILESYSTEMS[path]
            add(text + (suffix if "read-only" not in text else ""), broad and mode != "ro")
        else:
            add(f"Folder {path}{suffix}")
    return found


def autostart_entries(pacman_ql_output=None, home=None, flatpak_id=None):
    """Autostart entries an installed app has, as a list of paths.

    pacman: lines of `pacman -Ql pkg` that sit under /etc/xdg/autostart/. Flatpak: ~/.config/autostart/<id>.desktop
    if it exists (that is where the background portal puts it). An empty list means none were found; it says
    nothing about an app that is not installed.
    """
    found = []
    for line in (pacman_ql_output or "").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].startswith("/etc/xdg/autostart/") and parts[1].endswith(".desktop"):
            found.append(parts[1].strip())
    if flatpak_id and home:
        candidate = Path(home) / ".config" / "autostart" / f"{flatpak_id}.desktop"
        if candidate.exists():
            found.append(str(candidate))
    return found


# --- app data ----------------------------------------------------------------------------------------------------

def safe_data_path(home, relative):
    """home/relative if it is a plain relative path whose parent really lies inside home, else None.

    The folder itself may be a symlink (it is then removed as a link, never followed); what must not happen is the
    path escaping `home` through "..", an absolute path, or a parent folder that is a symlink pointing elsewhere.
    """
    if not isinstance(relative, str) or not relative or relative.startswith("/"):
        return None
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    real_home = os.path.realpath(home)
    target = Path(home) / relative
    real_parent = os.path.realpath(target.parent)
    if real_parent != real_home and not real_parent.startswith(real_home + os.sep):
        return None
    return target


def path_size(path, limit=200_000):
    """(bytes, complete) for a file or folder: real sizes, symlinks counted as themselves, stops after `limit` files."""
    path = Path(path)
    try:
        if path.is_symlink() or path.is_file():
            return path.lstat().st_size, True
    except OSError:
        return 0, True
    total, seen = 0, 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in files + [d for d in dirs if os.path.islink(os.path.join(root, d))]:
            seen += 1
            if seen > limit:
                return total, False
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total, True


def data_dirs(entry, home):
    """What would be deleted: [(path, bytes, complete)] for the catalogue's folders that exist right now."""
    found = []
    for relative in entry.data_paths:
        path = safe_data_path(home, relative)
        if path is not None and os.path.lexists(path):
            size, complete = path_size(path)
            found.append((path, size, complete))
    return found


def forget_data(entry, home, log=print):
    """Delete the app data data_dirs() lists. Returns the paths deleted; failures are logged, not raised."""
    removed = []
    for path, _size, _complete in data_dirs(entry, home):
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)
            removed.append(path)
            log(f"Deleted {path}")
        except OSError as error:
            log(f"Could not delete {path}: {error}")
    return removed


# --- running commands (injectable) -------------------------------------------------------------------------------

def run_command(argv, timeout=30):
    """(returncode, stdout) of a read-only command, in the C locale so the field names are the ones parsed above."""
    env = dict(os.environ, LC_ALL="C")
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, check=False)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return done.returncode, done.stdout


def installed_sets(run=run_command):
    """(pacman package names, Flatpak application ids) that are installed. Either is empty if the tool is missing."""
    code, out = run(["pacman", "-Qq"])
    pacman = parse_name_list(out) if code == 0 else set()
    code, out = run(["flatpak", "list", "--app", "--columns=application"])
    flatpak = parse_name_list(out) if code == 0 else set()
    return pacman, flatpak


def pacman_sizes(packages, run=run_command):
    """{"download": bytes|None, "count": int|None, "installed": bytes|None} for installing these packages.

    download/count come from the real transaction plan (`pacman -Sp`: what would be fetched, dependencies
    included); installed is the on-disk size of the named packages themselves. None means it could not be read.
    """
    result = {"download": None, "count": None, "installed": None}
    code, out = run(["pacman", "-Sp", "--print-format", "%s", "--", *packages])
    if code == 0:
        result["count"], result["download"] = parse_print_sizes(out)
    on_disk, known = 0, True
    for name in packages:
        code, out = run(["pacman", "-Si", "--", name])
        size = parse_pacman_si(out)["installed"] if code == 0 else None
        if size is None:
            known = False
        else:
            on_disk += size
    result["installed"] = on_disk if known else None
    return result


def flatpak_details(app_id, run=run_command):
    """{"download", "installed", "permissions"} from Flathub; sizes None and permissions None if it cannot be read
    (for example because Flathub has not been added yet)."""
    remote = store_catalog.FLATHUB_REMOTE
    code, out = run(["flatpak", "remote-info", "--user", remote, app_id])
    sizes = parse_flatpak_remote_info(out) if code == 0 else {"download": None, "installed": None}
    code, out = run(["flatpak", "remote-info", "--user", "--show-metadata", remote, app_id])
    permissions = parse_permissions(out) if code == 0 and out.strip() else None
    return {"download": sizes["download"], "installed": sizes["installed"], "permissions": permissions}


def pacman_files(packages, run=run_command):
    """`pacman -Ql` output for installed packages (used to look for autostart entries), or ""."""
    code, out = run(["pacman", "-Ql", "--", *packages])
    return out if code == 0 else ""


# --- command line: python3 store_actions.py forget <app-id> --------------------------------------------------------

def main(argv):
    if len(argv) == 3 and argv[1] == "forget":
        entry = store_catalog.get(argv[2]) if ENTRY_ID.match(argv[2]) else None
        if entry is None:
            print(f"Unknown app: {argv[2]}", file=sys.stderr)
            return 2
        home = Path(os.path.expanduser("~"))
        wanted = data_dirs(entry, home)
        if not wanted:
            print(f"No {entry.name} data found in your home folder.")
            return 0
        removed = forget_data(entry, home)
        return 0 if len(removed) == len(wanted) else 1
    print("usage: store_actions.py forget <app-id>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
