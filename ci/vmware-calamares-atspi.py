#!/usr/bin/env python3
"""Fail-closed AT-SPI probe/driver for the DarkOS Calamares VMware test.

This helper intentionally contains no Calamares control names.  First run
``inspect`` against the rebuilt ISO, review the resulting tree, and then fill
an explicit JSON plan.  ``run-stage`` requires every selector to match one and
only one accessible object.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402


SCHEMA = 1
SENTINELS = {
    "openrouter_key": "sk-or-v1-darkos-vm-install-sentinel-20260825",
    "groq_key": "gsk_darkos_vm_install_sentinel_20260825",
    "full_name": "DarkOS VMware E2E",
    "username": "darkosvm",
    "hostname": "darkos-vm-e2e",
    "password": "DarkOS-VMware-E2E-Only-2026!",
}
SECRET_REFS = {"openrouter_key", "groq_key", "password"}
SECRET_ENV = {
    "DARKOS_OPENROUTER_API_KEY": SENTINELS["openrouter_key"],
    "DARKOS_GROQ_API_KEY": SENTINELS["groq_key"],
}
GENERIC_API_ENV_NAMES = ("OPENROUTER_API_KEY", "GROQ_API_KEY")
MODULE_PACKAGE = "darkos-calamares-apikeys"
MODULE_VERSION = "1.0.0-1"
PLUGIN_DIRECTORY = Path("/usr/lib/calamares/modules/darkosapikeys")
STOCK_VMTOOLSD_PAM = (
    b"#%PAM-1.0\n"
    b"auth        include     system-services\n"
    b"account     include     system-services\n"
    b"password    include     system-services\n"
    b"session     include     system-services\n"
)


class TestFailure(RuntimeError):
    pass


def redact(value: object) -> str:
    text = str(value)
    for secret in SENTINELS.values():
        text = text.replace(secret, "<redacted-sentinel>")
    return text


def log(message: object) -> None:
    print(redact(message), flush=True)


def safe_call(default: Any, function: Any, *args: Any) -> Any:
    try:
        return function(*args)
    except Exception:
        return default


def children(node: Any) -> Iterable[Any]:
    count = safe_call(0, node.get_child_count)
    for index in range(max(0, int(count))):
        child = safe_call(None, node.get_child_at_index, index)
        if child is not None:
            yield child


def states(node: Any) -> list[str]:
    state_set = safe_call(None, node.get_state_set)
    if state_set is None:
        return []
    result: list[str] = []
    # PyGObject GEnums are not consistently iterable across Arch package
    # versions, so probe only stable states useful to exact selectors.
    for name in (
        "ACTIVE", "BUSY", "CHECKED", "EDITABLE", "ENABLED", "EXPANDED",
        "EXPANDABLE", "FOCUSABLE", "FOCUSED", "SELECTED", "SENSITIVE",
        "SHOWING", "VISIBLE",
    ):
        state = getattr(Atspi.StateType, name, None)
        if state is not None and safe_call(False, state_set.contains, state):
            result.append(name.casefold())
    return sorted(result)


def attributes(node: Any) -> dict[str, str]:
    raw = safe_call({}, node.get_attributes)
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    result: dict[str, str] = {}
    for item in raw or []:
        key, separator, value = str(item).partition(":")
        if separator:
            result[str(key)] = str(value)
    return result


def action_names(node: Any) -> list[str]:
    iface = safe_call(None, node.get_action_iface)
    if iface is None:
        return []
    count = int(safe_call(0, Atspi.Action.get_n_actions, iface))
    return [
        redact(safe_call("", Atspi.Action.get_action_name, iface, index))
        for index in range(max(0, count))
    ]


def node_record(node: Any, app_name: str, window_name: str, path: list[int]) -> dict[str, Any]:
    raw_attrs = attributes(node)
    raw_role = str(safe_call("", node.get_role_name))
    raw_name = str(safe_call("", node.get_name))
    raw_description = str(safe_call("", node.get_description))
    password_like = "password" in raw_role.casefold() or any(
        key.casefold() in {"password", "protected", "secret"}
        and value.casefold() not in {"", "0", "false", "no"}
        for key, value in raw_attrs.items()
    )
    text_iface = safe_call(None, node.get_text_iface)
    text_count = int(safe_call(-1, Atspi.Text.get_character_count, text_iface)) if text_iface else -1
    # Query protected text only to detect a leak; never serialize it. Qt should
    # return masking glyphs for a password QLineEdit, not the underlying key.
    accessible_text = (
        str(safe_call("", Atspi.Text.get_text, text_iface, 0, text_count))
        if text_iface is not None and text_count >= 0
        else ""
    )
    secret_exposed = any(
        secret in value
        for secret in SENTINELS.values()
        for value in (
            raw_role,
            raw_name,
            raw_description,
            accessible_text,
            *raw_attrs.keys(),
            *raw_attrs.values(),
        )
    )
    editable = safe_call(None, node.get_editable_text_iface) is not None
    return {
        "path": path,
        "application": redact(app_name),
        "window": redact(window_name),
        "role": redact(raw_role),
        "name": redact(raw_name),
        "description": redact(raw_description),
        "states": states(node),
        "actions": action_names(node),
        "attributes": {redact(key): redact(value) for key, value in raw_attrs.items()},
        "editable": editable,
        "password_like": password_like,
        "text_character_count": text_count,
        "secret_exposed": secret_exposed,
    }


def snapshot(app_contains: str, max_depth: int = 32) -> list[tuple[Any, dict[str, Any]]]:
    desktop = Atspi.get_desktop(0)
    result: list[tuple[Any, dict[str, Any]]] = []

    def walk(node: Any, app_name: str, window_name: str, path: list[int], depth: int) -> None:
        if depth > max_depth:
            raise TestFailure(f"AT-SPI tree exceeded maximum depth {max_depth}")
        record = node_record(node, app_name, window_name, path)
        result.append((node, record))
        for index, child in enumerate(children(node)):
            walk(child, app_name, window_name, path + [index], depth + 1)

    for app_index, app in enumerate(children(desktop)):
        app_name = str(safe_call("", app.get_name))
        if app_contains.casefold() not in app_name.casefold():
            continue
        for window_index, window in enumerate(children(app)):
            window_name = str(safe_call("", window.get_name))
            walk(window, app_name, window_name, [app_index, window_index], 0)
    return result


def wait_for_snapshot(app_contains: str, timeout: float) -> list[tuple[Any, dict[str, Any]]]:
    deadline = time.monotonic() + timeout
    last: list[tuple[Any, dict[str, Any]]] = []
    while time.monotonic() < deadline:
        last = snapshot(app_contains)
        if last:
            return last
        time.sleep(0.25)
    raise TestFailure(
        f"no AT-SPI application containing {app_contains!r} appeared within {timeout:g}s"
    )


def write_inspection(args: argparse.Namespace) -> None:
    pairs = wait_for_snapshot(args.app_contains, args.timeout)
    document = {
        "schema": SCHEMA,
        "generated_unix": int(time.time()),
        "app_contains": args.app_contains,
        "controls": [record for _, record in pairs],
    }
    serialized = json.dumps(document, indent=2, sort_keys=True)
    if any(value in serialized for value in SENTINELS.values()):
        raise TestFailure("inspection output unexpectedly contains a sentinel value")
    output = Path(args.output)
    output.write_text(serialized + "\n", encoding="utf-8")
    os.chmod(output, 0o600)
    log(f"wrote {len(pairs)} redacted AT-SPI records to {output}")


def load_plan(path: str) -> dict[str, Any]:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("schema") != SCHEMA:
        raise TestFailure(f"plan schema must be {SCHEMA}")
    if not isinstance(plan.get("stages"), dict):
        raise TestFailure("plan must contain an object named 'stages'")
    return plan


SELECTOR_FIELDS = {"application", "window", "role", "name", "description"}


def matches(record: dict[str, Any], selector: dict[str, Any]) -> bool:
    unknown = set(selector) - SELECTOR_FIELDS - {"states"}
    if unknown:
        raise TestFailure(f"unsupported selector fields: {sorted(unknown)}")
    if not selector:
        raise TestFailure("empty selectors are forbidden")
    for field in SELECTOR_FIELDS:
        if field in selector and record.get(field, "").casefold() != str(selector[field]).casefold():
            return False
    wanted_states = selector.get("states", [])
    if not isinstance(wanted_states, list):
        raise TestFailure("selector states must be an array")
    actual_states = {str(item).casefold() for item in record.get("states", [])}
    return all(str(item).casefold() in actual_states for item in wanted_states)


def unique_control(args: argparse.Namespace, selector: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    deadline = time.monotonic() + args.timeout
    last_count = 0
    while time.monotonic() < deadline:
        found = [pair for pair in snapshot(args.app_contains) if matches(pair[1], selector)]
        last_count = len(found)
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            break
        time.sleep(0.25)
    identity = {key: redact(value) for key, value in selector.items()}
    raise TestFailure(f"selector must match exactly one control; matched {last_count}: {identity}")


def click(node: Any, requested_action: str | None) -> None:
    iface = safe_call(None, node.get_action_iface)
    if iface is None:
        raise TestFailure("selected control has no action interface")
    names = [str(name) for name in action_names(node)]
    if requested_action:
        candidates = [i for i, name in enumerate(names) if name.casefold() == requested_action.casefold()]
    else:
        candidates = [i for i, name in enumerate(names) if name.casefold() in {"click", "press", "activate"}]
    if len(candidates) != 1:
        raise TestFailure(f"click action is not unique; available actions: {names}")
    if not safe_call(False, Atspi.Action.do_action, iface, candidates[0]):
        raise TestFailure("AT-SPI action returned failure")


def set_text(node: Any, value_ref: str) -> None:
    if value_ref not in SENTINELS:
        raise TestFailure(f"unknown value_ref {value_ref!r}")
    iface = safe_call(None, node.get_editable_text_iface)
    if iface is None:
        raise TestFailure("selected control is not editable")
    value = SENTINELS[value_ref]
    if not safe_call(False, Atspi.EditableText.set_text_contents, iface, value):
        raise TestFailure("AT-SPI set_text_contents returned failure")
    text_iface = safe_call(None, node.get_text_iface)
    character_count = safe_call(-1, Atspi.Text.get_character_count, text_iface) if text_iface else -1
    if character_count not in {-1, len(value)}:
        raise TestFailure("editable control did not retain the expected character count")


def assert_masked(record: dict[str, Any], value_ref: str) -> None:
    if value_ref not in SECRET_REFS:
        raise TestFailure("assert_masked requires a secret value_ref")
    if not record.get("password_like"):
        raise TestFailure("secret field is not exposed as password/protected through AT-SPI")
    if record.get("secret_exposed"):
        raise TestFailure("secret appears in accessible metadata")


def run_stage(args: argparse.Namespace) -> None:
    plan = load_plan(args.plan)
    steps = plan["stages"].get(args.stage)
    if not isinstance(steps, list) or not steps:
        raise TestFailure(f"stage {args.stage!r} is absent or empty")
    for number, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise TestFailure(f"stage step {number} must be an object")
        operation = step.get("op")
        selector = step.get("selector")
        if operation not in {"wait", "click", "set_text", "assert_masked"}:
            raise TestFailure(f"unsupported operation {operation!r} at step {number}")
        if not isinstance(selector, dict):
            raise TestFailure(f"step {number} requires an exact selector object")
        node, record = unique_control(args, selector)
        if operation == "click":
            click(node, step.get("action"))
        elif operation == "set_text":
            set_text(node, str(step.get("value_ref", "")))
        elif operation == "assert_masked":
            assert_masked(record, str(step.get("value_ref", "")))
        log(f"stage {args.stage}: step {number} {operation} passed for {record['role']!r}/{record['name']!r}")


def read_environ(pid: int) -> set[bytes]:
    return set(Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"))


def process_matches(uid: int, needles: tuple[str, ...]) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        folded = command.casefold()
        if any(needle.casefold() in folded for needle in needles):
            result.append((int(entry.name), command))
    return result


def verify_environment_file(path: Path, uid: int, gid: int) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise TestFailure(f"{path} is not a regular, non-symlink file")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise TestFailure(f"{path} mode is {stat.S_IMODE(info.st_mode):04o}, expected 0600")
    if (info.st_uid, info.st_gid) != (uid, gid):
        raise TestFailure(f"{path} ownership is {info.st_uid}:{info.st_gid}, expected {uid}:{gid}")
    expected = "".join(
        f"export {name}='{value}'\n" for name, value in SECRET_ENV.items()
    ).encode("utf-8")
    if path.read_bytes() != expected:
        raise TestFailure(f"{path} is not the writer's exact canonical two-line credential file")


def assert_no_api_sentinel(sink: str, contents: bytes) -> None:
    for number, sentinel in enumerate(SECRET_ENV.values(), 1):
        if sentinel.encode() in contents:
            raise TestFailure(f"{sink} contains API-key sentinel {number}")


def root_calamares_pids() -> list[int]:
    result: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid == 0 and (entry / "comm").read_text().strip() == "calamares":
                result.append(int(entry.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return result


def verify_live_preflight(args: argparse.Namespace) -> None:
    del args
    if not Path("/run/archiso").exists() or os.geteuid() != 0:
        raise TestFailure("live plugin preflight must run as root in the live ISO")

    package = subprocess.run(
        ["pacman", "-Q", MODULE_PACKAGE],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    if package.returncode != 0 or package.stdout.strip() != f"{MODULE_PACKAGE} {MODULE_VERSION}":
        raise TestFailure(f"the live ISO does not contain exact {MODULE_PACKAGE} {MODULE_VERSION}")

    descriptor = PLUGIN_DIRECTORY / "module.desc"
    plugin = PLUGIN_DIRECTORY / "libcalamares_viewmodule_darkosapikeys.so"
    descriptor_lines = set(descriptor.read_text(encoding="utf-8").splitlines())
    for required in {
        'type: "viewmodule"',
        'name: "darkosapikeys"',
        'interface: "qtplugin"',
        'load: "libcalamares_viewmodule_darkosapikeys.so"',
        "noconfig: true",
    }:
        if required not in descriptor_lines:
            raise TestFailure(f"the live module descriptor is missing a required identity field: {required}")
    plugin_info = plugin.lstat()
    if not stat.S_ISREG(plugin_info.st_mode) or plugin.is_symlink() or not os.access(plugin, os.X_OK):
        raise TestFailure("the live Calamares plugin is not a regular executable shared object")
    if (plugin_info.st_uid, plugin_info.st_gid) != (0, 0):
        raise TestFailure("the live Calamares plugin is not owned by root:root")

    try:
        import yaml

        settings = yaml.safe_load(Path("/etc/calamares/settings.conf").read_text(encoding="utf-8"))
    except Exception as error:
        raise TestFailure("could not parse the live Calamares settings") from error
    instances = settings.get("instances") if isinstance(settings, dict) else None
    matching_instances = [
        item
        for item in instances or []
        if isinstance(item, dict) and item.get("id") == "api-keys"
    ]
    if matching_instances != [{"id": "api-keys", "module": "darkosapikeys"}]:
        raise TestFailure("the API-key module instance is absent, duplicated, or configured incorrectly")
    sequence = settings.get("sequence")
    if not isinstance(sequence, list) or len(sequence) < 2:
        raise TestFailure("the Calamares sequence is unavailable")
    show = sequence[0].get("show") if isinstance(sequence[0], dict) else None
    execute = sequence[1].get("exec") if isinstance(sequence[1], dict) else None
    if not isinstance(show, list) or not isinstance(execute, list):
        raise TestFailure("the Calamares show/exec sequence is unavailable")
    instance_key = "darkosapikeys@api-keys"
    if show.count(instance_key) != 1 or not (
        show.index("users") < show.index(instance_key) < show.index("summary")
    ):
        raise TestFailure("the API-key page is not exactly between users and summary")
    if execute.count(instance_key) != 1 or not (
        execute.index("users") < execute.index(instance_key) < execute.index("packages")
    ):
        raise TestFailure("the API-key job is not exactly between users and package removal")

    pids = root_calamares_pids()
    if len(pids) != 1:
        raise TestFailure(f"expected one root-owned Calamares process; found {len(pids)}")
    maps = Path(f"/proc/{pids[0]}/maps").read_text(encoding="utf-8", errors="replace")
    if str(plugin) not in maps:
        raise TestFailure("the running Calamares process has not loaded the DarkOS plugin")

    log(f"live package: {MODULE_PACKAGE} {MODULE_VERSION}")
    log("live plugin: descriptor, root ownership, executable mode, and process load passed")
    log("live sequence: page after users; private job after users and before package removal")


def verify_live_logs(args: argparse.Namespace) -> None:
    del args
    if not Path("/run/archiso").exists():
        raise TestFailure("Calamares log verification must run in the live ISO")
    if os.geteuid() != 0:
        raise TestFailure("Calamares log verification must run as root")

    calamares_pids = root_calamares_pids()
    if len(calamares_pids) != 1:
        raise TestFailure(f"expected one root-owned Calamares process; found {len(calamares_pids)}")

    fd_directory = Path(f"/proc/{calamares_pids[0]}/fd")
    session_files: dict[tuple[int, int], Path] = {}
    for fd_path in fd_directory.iterdir():
        try:
            target = os.readlink(fd_path)
            file_info = fd_path.stat()
        except (FileNotFoundError, OSError, PermissionError):
            continue
        if Path(target.removesuffix(" (deleted)")).name == "session.log":
            session_files.setdefault((file_info.st_dev, file_info.st_ino), fd_path)
    if len(session_files) != 1:
        raise TestFailure(f"expected one unique open Calamares session.log; found {len(session_files)}")
    session_contents = next(iter(session_files.values())).read_bytes()
    if b"=== START CALAMARES 3.4.2" not in session_contents:
        raise TestFailure("the open Calamares session log lacks its 3.4.2 start marker")
    assert_no_api_sentinel("Calamares session log", session_contents)

    sync = subprocess.run(
        ["journalctl", "--sync"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if sync.returncode != 0:
        raise TestFailure("journalctl --sync failed")
    journal = subprocess.run(
        ["journalctl", "-b", "--no-pager", "--output=export"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if journal.returncode != 0:
        raise TestFailure("could not read the synchronized boot journal")
    assert_no_api_sentinel("current boot journal", journal.stdout)

    scanned_var_logs = 0
    log_root = Path("/var/log")
    for path in sorted(log_root.rglob("*")):
        try:
            info = path.lstat()
        except OSError as error:
            raise TestFailure(f"could not inspect a /var/log sink: {error.__class__.__name__}") from error
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            continue
        relative = path.relative_to(log_root)
        if "journal" in relative.parts or path.suffix == ".journal":
            continue
        try:
            contents = path.read_bytes()
        except OSError as error:
            raise TestFailure(f"could not read /var/log/{relative}: {error.__class__.__name__}") from error
        assert_no_api_sentinel(f"/var/log/{relative}", contents)
        scanned_var_logs += 1

    scanned_harness_logs = 0
    for path in sorted(Path("/tmp").glob("darkos-vmware-installed-*.log")):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            raise TestFailure(f"harness log is not a regular non-symlink file: {path.name}")
        assert_no_api_sentinel(f"/tmp/{path.name}", path.read_bytes())
        scanned_harness_logs += 1

    log("Calamares session.log: version marker present; both API-key sentinels absent")
    log("current boot journal: both API-key sentinels absent")
    log(f"non-journal /var/log files scanned: {scanned_var_logs}")
    log(f"VMware harness logs scanned: {scanned_harness_logs}")


def verify_installed(args: argparse.Namespace) -> None:
    if Path("/run/archiso").exists():
        raise TestFailure("verification is running in the live ISO, not the installed system")
    uid, gid = os.getuid(), os.getgid()
    if uid == 0:
        raise TestFailure("installed verification must run as the logged-in desktop user")
    home = Path.home()
    darkos_dir = home / ".config" / "darkos"
    darkos_info = darkos_dir.lstat()
    if not stat.S_ISDIR(darkos_info.st_mode) or darkos_dir.is_symlink():
        raise TestFailure(f"{darkos_dir} is not a regular, non-symlink directory")
    if stat.S_IMODE(darkos_info.st_mode) != 0o700:
        raise TestFailure(
            f"{darkos_dir} mode is {stat.S_IMODE(darkos_info.st_mode):04o}, expected 0700"
        )
    if (darkos_info.st_uid, darkos_info.st_gid) != (uid, gid):
        raise TestFailure(
            f"{darkos_dir} ownership is {darkos_info.st_uid}:{darkos_info.st_gid}, expected {uid}:{gid}"
        )
    env_path = darkos_dir / "env"
    verify_environment_file(env_path, uid, gid)
    system_environment = Path("/etc/environment")
    if system_environment.exists():
        raw = system_environment.read_bytes()
        forbidden_names = (*SECRET_ENV.keys(), *GENERIC_API_ENV_NAMES)
        if any(name.encode() in raw for name in forbidden_names) or any(
            value.encode() in raw for value in SECRET_ENV.values()
        ):
            raise TestFailure("API-key material leaked into /etc/environment")

    pam_path = Path("/etc/pam.d/vmtoolsd")
    pam_info = pam_path.lstat()
    if not stat.S_ISREG(pam_info.st_mode) or pam_path.is_symlink():
        raise TestFailure("installed vmtoolsd PAM policy is not a regular non-symlink file")
    if stat.S_IMODE(pam_info.st_mode) != 0o644 or (pam_info.st_uid, pam_info.st_gid) != (0, 0):
        raise TestFailure("installed vmtoolsd PAM policy is not root:root mode 0644")
    if pam_path.read_bytes() != STOCK_VMTOOLSD_PAM:
        raise TestFailure("installed vmtoolsd PAM policy is not the stock system-services stack")
    pam_template = Path("/usr/share/darkos/installed-pam/vmtoolsd")
    if pam_template.exists() or pam_template.is_symlink():
        raise TestFailure("the installed-only PAM restoration template was not cleaned up")

    pacman = shutil.which("pacman")
    if not pacman:
        raise TestFailure("pacman is unavailable on the installed system")
    for package in ("calamares", "darkos-calamares-apikeys"):
        query = subprocess.run(
            [pacman, "-Q", package],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if query.returncode == 0:
            raise TestFailure(f"installer-only package remains installed: {package}")
        if query.returncode != 1:
            raise TestFailure(f"could not confirm package removal: {package}")
    plugin_dir = Path("/usr/lib/calamares/modules/darkosapikeys")
    if plugin_dir.exists() or plugin_dir.is_symlink():
        raise TestFailure(f"installer-only module path remains installed: {plugin_dir}")

    targets = {
        "hyprland": ("Hyprland",),
        "darkos-shell": ("darkos-shell.py", "darkos_shell"),
    }
    for label, needles in targets.items():
        matches_ = process_matches(uid, needles)
        if len(matches_) != 1:
            raise TestFailure(f"expected exactly one {label} process for uid {uid}; found {len(matches_)}")
        pid, _ = matches_[0]
        environ = read_environ(pid)
        for name, value in SECRET_ENV.items():
            expected = f"{name}={value}".encode()
            if expected not in environ:
                raise TestFailure(f"{label} pid {pid} lacks the exact {name} sentinel")
        log(f"{label} pid {pid}: both API-key names are present with exact sentinels")
    log(f"installed private directory: mode 0700, owner {uid}:{gid}")
    log(f"installed env file: regular, mode 0600, owner {uid}:{gid}")
    log("installed vmtoolsd PAM: stock system-services stack, root:root mode 0644")
    log("Calamares and darkos-calamares-apikeys are absent from the installed system")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--app-contains", default="calamares")
    result.add_argument("--timeout", type=float, default=20.0)
    sub = result.add_subparsers(dest="command", required=True)
    inspect_parser = sub.add_parser("inspect")
    inspect_parser.add_argument("--output", required=True)
    inspect_parser.set_defaults(function=write_inspection)
    stage_parser = sub.add_parser("run-stage")
    stage_parser.add_argument("--plan", required=True)
    stage_parser.add_argument("--stage", required=True)
    stage_parser.set_defaults(function=run_stage)
    verify_parser = sub.add_parser("verify-installed")
    verify_parser.set_defaults(function=verify_installed)
    live_preflight_parser = sub.add_parser("verify-live-preflight")
    live_preflight_parser.set_defaults(function=verify_live_preflight)
    live_logs_parser = sub.add_parser("verify-live-logs")
    live_logs_parser.set_defaults(function=verify_live_logs)
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        args.function(args)
        return 0
    except Exception as error:
        print(f"FAIL: {redact(error)}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
