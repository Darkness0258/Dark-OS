#!/usr/bin/env python3
"""DarkOS window effects: switcher, search, snap, overview, accessibility zoom.

One executable so the build's four-stage script registration stays a single
entry. Every feature below has a pure-function core that CI can import
without GTK or a compositor; GTK/wofi are presentation only.

    --switcher
        Alt+Tab. Ordered by Hyprland focusHistoryID (the previously focused
        window is selected first, Windows-style). GTK card strip with app
        icons and optional grim thumbnails; falls back to wofi --dmenu.

    --search
        Universal launcher (SUPER+E): apps (.desktop), recent/home files,
        and Settings tabs in one list.

    --snap {left,right,top,bottom,top-left,top-right,bottom-left,bottom-right,maximize}
        Pixel-exact snap using hyprctl monitors/activewindow, same method
        as the original half-screen snap.

    --snap-picker
        Visual 2x2 + halves layout picker.

    --overview
        Workspace overview: windows grouped by Hyprland workspace.

    --zoom {in,out,reset,on,off,toggle}
        Hyprland cursor zoom (the real magnifier). SUPER+= / - / 0.

    --a11y-apply
        Session-start: read settings.json and apply saved magnifier state.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse


SKIP_SWITCHER_CLASSES = {
    "darkos-switcher",
    "darkos-search",
    "darkos-overview",
    "darkos-snap-picker",
    "wofi",
}

SNAP_SIDES = (
    "left", "right", "top", "bottom",
    "top-left", "top-right", "bottom-left", "bottom-right",
    "maximize",
)

ZOOM_MIN = 1.0
ZOOM_MAX = 4.0
ZOOM_STEP = 0.25
ZOOM_ON = 2.0

SETTINGS_CATALOG = (
    ("system", "System", "About this PC, CPU, memory, kernel"),
    ("performance", "Performance", "Power profile, performance, balanced, power saver"),
    ("config", "Config", "Hyprland and session configuration"),
    ("devices", "Devices", "Disks, peripherals"),
    ("users", "Users", "Accounts and login"),
    ("services", "Services", "systemd services"),
    ("startup", "Startup", "Autostart applications"),
    ("storage", "Storage", "Disk usage, snapshots"),
    ("fonts", "Fonts", "GTK font"),
    ("icons", "Icons", "Icon theme"),
    ("themes", "Themes", "Accent color, appearance"),
    ("wallpaper", "Wallpaper", "Desktop background"),
    ("motion", "Motion", "Reduce motion, animations"),
    ("designer", "Designer", "Corner radius"),
    ("permissions", "Permissions", "App permissions"),
    ("accessibility", "Accessibility", "Magnifier, high contrast, captions, sticky keys"),
)

SKIP_FILE_DIRS = {
    ".git", "node_modules", "__pycache__", ".cache", ".local", ".npm",
    ".cargo", ".rustup", "proc", "sys", "dev", ".Trash", "lost+found",
}

DESKTOP_DIRS = (
    "/usr/share/applications",
    "/usr/local/share/applications",
    os.path.expanduser("~/.local/share/applications"),
)


def _hyprctl_json(subcommand):
    try:
        output = subprocess.run(
            ["hyprctl", subcommand, "-j"],
            capture_output=True, text=True, timeout=2,
        ).stdout
        return json.loads(output)
    except Exception:
        return None


def _hyprctl_getoption(name):
    try:
        output = subprocess.run(
            ["hyprctl", "getoption", name, "-j"],
            capture_output=True, text=True, timeout=2,
        ).stdout
        return json.loads(output)
    except Exception:
        return None


def _dispatch(*args):
    try:
        subprocess.run(["hyprctl", "dispatch", *args], timeout=2, capture_output=True)
    except Exception:
        pass


def _keyword(key, value):
    try:
        result = subprocess.run(
            ["hyprctl", "keyword", key, str(value)],
            capture_output=True, text=True, timeout=2,
        )
        return result.returncode == 0
    except Exception:
        return False


def visible_clients(clients):
    """Windows the switcher/overview should show."""
    visible = []
    for client in clients or []:
        if not client.get("title") or not client.get("address"):
            continue
        if client.get("hidden") or client.get("mapped") is False:
            continue
        klass = str(client.get("class") or "")
        if klass in SKIP_SWITCHER_CLASSES:
            continue
        workspace = client.get("workspace") or {}
        if str(workspace.get("name") or "").startswith("special"):
            continue
        visible.append(client)
    return visible


def ordered_switcher_clients(clients):
    """Previously-focused window first (the one Alt+Tab should land on)."""
    visible = visible_clients(clients)
    visible.sort(key=lambda c: c.get("focusHistoryID", 9999))
    if len(visible) > 1:
        return visible[1:] + visible[:1]
    return visible


def switcher_label(client):
    title = str(client.get("title") or "").strip()
    klass = str(client.get("class") or "").strip()
    if klass:
        return f"{title}  —  {klass}"
    return title


def grim_geometry(client):
    at = client.get("at") or [0, 0]
    size = client.get("size") or [0, 0]
    try:
        x, y = int(at[0]), int(at[1])
        w, h = int(size[0]), int(size[1])
    except (TypeError, ValueError, IndexError):
        return None
    if w < 32 or h < 32:
        return None
    return f"{x},{y} {w}x{h}"


def capture_thumbnail(client, dest_path, runner=subprocess.run):
    geom = grim_geometry(client)
    if not geom:
        return None
    try:
        result = runner(
            ["grim", "-g", geom, dest_path],
            capture_output=True, timeout=2,
        )
    except Exception:
        return None
    if result.returncode != 0 or not os.path.isfile(dest_path):
        return None
    return dest_path


def monitor_logical_rect(monitor):
    scale = monitor.get("scale") or 1.0
    try:
        scale = float(scale) or 1.0
    except (TypeError, ValueError):
        scale = 1.0
    return {
        "x": round(monitor.get("x", 0) / scale),
        "y": round(monitor.get("y", 0) / scale),
        "w": round(monitor.get("width", 1920) / scale),
        "h": round(monitor.get("height", 1080) / scale),
    }


def snap_rect(mon_x, mon_y, mon_w, mon_h, side):
    if side not in SNAP_SIDES:
        return None
    half_w = mon_w // 2
    half_h = mon_h // 2
    if side == "left":
        return mon_x, mon_y, half_w, mon_h
    if side == "right":
        return mon_x + half_w, mon_y, half_w, mon_h
    if side == "top":
        return mon_x, mon_y, mon_w, half_h
    if side == "bottom":
        return mon_x, mon_y + half_h, mon_w, half_h
    if side == "top-left":
        return mon_x, mon_y, half_w, half_h
    if side == "top-right":
        return mon_x + half_w, mon_y, half_w, half_h
    if side == "bottom-left":
        return mon_x, mon_y + half_h, half_w, half_h
    if side == "bottom-right":
        return mon_x + half_w, mon_y + half_h, half_w, half_h
    return mon_x, mon_y, mon_w, mon_h


def next_zoom(current, action):
    try:
        current = float(current)
    except (TypeError, ValueError):
        current = ZOOM_MIN
    if action == "in":
        return min(ZOOM_MAX, round(current + ZOOM_STEP, 2))
    if action == "out":
        return max(ZOOM_MIN, round(current - ZOOM_STEP, 2))
    if action in ("reset", "off"):
        return ZOOM_MIN
    if action == "on":
        return ZOOM_ON if current <= ZOOM_MIN else current
    if action == "toggle":
        return ZOOM_MIN if current > ZOOM_MIN else ZOOM_ON
    return current


def strip_exec_field(exec_cmd):
    parts = []
    for token in exec_cmd.split():
        if token.startswith("%"):
            continue
        parts.append(token)
    return parts


def parse_desktop_file(text):
    in_entry = False
    fields = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_entry = line == "[Desktop Entry]"
            continue
        if not in_entry or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if "[" in key:
            continue
        fields[key] = value.strip()
    if fields.get("Type") != "Application":
        return None
    if fields.get("NoDisplay", "").lower() == "true":
        return None
    if fields.get("Hidden", "").lower() == "true":
        return None
    name = fields.get("Name")
    exec_cmd = fields.get("Exec")
    if not name or not exec_cmd:
        return None
    argv = strip_exec_field(exec_cmd)
    if not argv:
        return None
    return {
        "kind": "app",
        "name": name,
        "exec": argv,
        "icon": fields.get("Icon", ""),
        "comment": fields.get("Comment", ""),
        "terminal": fields.get("Terminal", "").lower() == "true",
    }


def load_desktop_apps(directories=DESKTOP_DIRS, reader=None):
    reader = reader or (lambda path: open(path, encoding="utf-8", errors="replace").read())
    apps = []
    seen = set()
    for directory in directories:
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if not name.endswith(".desktop"):
                continue
            path = os.path.join(directory, name)
            try:
                parsed = parse_desktop_file(reader(path))
            except OSError:
                continue
            if parsed and parsed["name"] not in seen:
                seen.add(parsed["name"])
                apps.append(parsed)
    apps.sort(key=lambda item: item["name"].lower())
    return apps


def match_score(query, *fields):
    q = (query or "").strip().lower()
    if not q:
        return 1
    best = 0
    tokens = q.split()
    for field in fields:
        text = (field or "").lower()
        if not text:
            continue
        if text == q:
            best = max(best, 100)
        elif text.startswith(q):
            best = max(best, 80)
        elif q in text:
            best = max(best, 50)
        elif tokens and all(token in text for token in tokens):
            best = max(best, 30)
    return best


def parse_recently_used(xbel_text, limit=12):
    paths = []
    seen = set()
    for href in re.findall(r'href="(file://[^"]+)"', xbel_text or ""):
        parsed = urllib.parse.urlparse(href)
        path = urllib.parse.unquote(parsed.path)
        if os.name == "nt" and path.startswith("/"):
            path = path.lstrip("/")
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
        if len(paths) >= limit:
            break
    return paths


def iter_home_files(roots, query, max_depth=3, limit=20, max_visits=400):
    q = (query or "").strip().lower()
    if not q:
        return []
    hits = []
    visits = 0
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            rel = os.path.relpath(dirpath, root)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            dirnames[:] = [
                name for name in dirnames
                if name not in SKIP_FILE_DIRS and not name.startswith(".")
            ]
            if depth > max_depth:
                dirnames[:] = []
                continue
            for name in filenames:
                visits += 1
                if visits > max_visits or len(hits) >= limit:
                    return hits
                if name.startswith("."):
                    continue
                if q not in name.lower():
                    continue
                hits.append(os.path.join(dirpath, name))
    return hits


def settings_results(query):
    results = []
    for tab, name, keywords in SETTINGS_CATALOG:
        score = match_score(query, name, keywords, tab)
        if score:
            results.append({
                "kind": "setting",
                "name": name,
                "tab": tab,
                "comment": keywords,
                "score": score,
            })
    results.sort(key=lambda item: (-item["score"], item["name"]))
    return results


def file_results(query, home=None, recent_paths=None, extra_paths=None):
    home = home if home is not None else os.path.expanduser("~")
    results = []
    seen = set()
    for path in list(recent_paths or []) + list(extra_paths or []):
        if not path or path in seen:
            continue
        seen.add(path)
        score = match_score(query, os.path.basename(path), path)
        if score:
            results.append({
                "kind": "file",
                "name": os.path.basename(path),
                "path": path,
                "comment": path,
                "score": score + (10 if path in (recent_paths or []) else 0),
            })
    if (query or "").strip():
        roots = [
            os.path.join(home, folder)
            for folder in ("Documents", "Downloads", "Desktop", "Pictures", "Videos", "Music")
        ]
        roots.append(home)
        for path in iter_home_files(roots, query):
            if path in seen:
                continue
            seen.add(path)
            results.append({
                "kind": "file",
                "name": os.path.basename(path),
                "path": path,
                "comment": path,
                "score": match_score(query, os.path.basename(path), path),
            })
    results.sort(key=lambda item: (-item["score"], item["name"].lower()))
    return results[:20]


def search_items(query, apps, files, settings):
    ranked = []
    for app in apps:
        score = match_score(query, app.get("name"), app.get("comment"), " ".join(app.get("exec") or []))
        if score:
            item = dict(app)
            item["score"] = score
            ranked.append(item)
    ranked.extend(files)
    ranked.extend(settings)
    ranked.sort(key=lambda item: (-item.get("score", 0), item.get("kind", ""), item.get("name", "").lower()))
    return ranked[:30]


def result_label(item):
    kind = (item.get("kind") or "item").title()
    name = item.get("name") or ""
    extra = item.get("comment") or item.get("path") or item.get("tab") or ""
    if extra and extra != name:
        return f"[{kind}] {name}  —  {extra}"
    return f"[{kind}] {name}"


def group_clients_by_workspace(clients):
    groups = {}
    for client in visible_clients(clients):
        workspace = client.get("workspace") or {}
        key = workspace.get("id", 0)
        groups.setdefault(key, []).append(client)
    return dict(sorted(groups.items(), key=lambda pair: pair[0]))


def _have_display():
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def _wofi_pick(prompt, lines, timeout=30):
    if not lines:
        return None
    try:
        result = subprocess.run(
            ["wofi", "--dmenu", "--prompt", prompt],
            input="\n".join(lines),
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception:
        return None
    picked = (result.stdout or "").strip()
    return picked or None


def _launch_argv(argv, env=None):
    if not argv:
        return
    try:
        subprocess.Popen(argv, env=env, start_new_session=True)
    except OSError:
        pass


def activate_result(item):
    kind = item.get("kind")
    if kind == "app":
        _launch_argv(item.get("exec") or [])
        return 0
    if kind == "file":
        path = item.get("path")
        if not path:
            return 1
        if os.path.isdir(path):
            _launch_argv(["/usr/local/bin/darkos-files.py", path])
        else:
            _launch_argv(["xdg-open", path])
        return 0
    if kind == "setting":
        env = os.environ.copy()
        env["DARKOS_SETTINGS_TAB"] = item.get("tab") or "system"
        _launch_argv(["python", "/usr/local/bin/darkos-settings.py"], env=env)
        return 0
    if kind == "window":
        address = item.get("address")
        if address:
            _dispatch("focuswindow", f"address:{address}")
        return 0
    if kind == "workspace":
        workspace = item.get("workspace")
        if workspace is not None:
            _dispatch("workspace", str(workspace))
        return 0
    return 1


def _try_gtk():
    if not _have_display():
        return None
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, GdkPixbuf, GLib, Gtk
    except Exception:
        return None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from darkos_shell.css import apply_css
        apply_css()
    except Exception:
        pass
    return Gtk, Gdk, GdkPixbuf, GLib


def _new_overlay_window(Gtk, Gdk, title, wm_class, width, height):
    try:
        from gi.repository import GLib
        GLib.set_prgname(wm_class)
    except Exception:
        pass
    win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    win.set_title(title)
    win.set_decorated(False)
    win.set_keep_above(True)
    win.set_skip_taskbar_hint(True)
    win.set_accept_focus(True)
    win.set_default_size(width, height)
    try:
        win.set_type_hint(Gdk.WindowTypeHint.DIALOG)
    except Exception:
        pass
    win.connect("destroy", Gtk.main_quit)
    return win


def _icon_image(Gtk, icon_name, pixel_size=48):
    image = Gtk.Image()
    if icon_name and os.path.isfile(icon_name):
        image.set_from_file(icon_name)
        return image
    name = icon_name or "application-x-executable"
    try:
        image.set_from_icon_name(name, Gtk.IconSize.DIALOG)
    except Exception:
        image.set_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)
    image.set_pixel_size(pixel_size)
    return image


def run_switcher():
    clients = ordered_switcher_clients(_hyprctl_json("clients") or [])
    if not clients:
        return 0
    gtk = _try_gtk()
    if gtk:
        return _switcher_gtk(clients, gtk)
    return _switcher_wofi(clients)


def _switcher_wofi(clients):
    lines = [switcher_label(c) for c in clients]
    picked = _wofi_pick("Switch window", lines)
    for client, line in zip(clients, lines):
        if line == picked:
            _dispatch("focuswindow", f"address:{client['address']}")
            return 0
    return 0


def _switcher_gtk(clients, gtk):
    Gtk, Gdk, GdkPixbuf, GLib = gtk
    active = _hyprctl_json("activeworkspace") or {}
    active_id = active.get("id")
    thumb_dir = tempfile.mkdtemp(prefix="darkos-switcher-")
    selected = {"index": 0}

    win = _new_overlay_window(Gtk, Gdk, "Switch window", "darkos-switcher", 880, 220)
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    outer.set_border_width(16)
    hint = Gtk.Label(label="← →  choose    Enter  switch    Esc  cancel")
    outer.pack_start(hint, False, False, 0)
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    cards = []

    def restyle():
        for i, card in enumerate(cards):
            ctx = card.get_style_context()
            if i == selected["index"]:
                ctx.add_class("dock-highlight")
            else:
                ctx.remove_class("dock-highlight")

    def choose(index):
        selected["index"] = index % len(clients)
        restyle()

    def confirm(*_):
        client = clients[selected["index"]]
        _dispatch("focuswindow", f"address:{client['address']}")
        win.destroy()

    for i, client in enumerate(clients):
        card = Gtk.Button()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        thumb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        thumb.set_size_request(160, 90)
        icon_name = str(client.get("class") or "application-x-executable").lower()
        thumb.pack_start(_icon_image(Gtk, icon_name, 48), True, True, 0)
        box.pack_start(thumb, True, True, 0)
        label = Gtk.Label(label=str(client.get("title") or "")[:42], xalign=0.5)
        box.pack_start(label, False, False, 0)
        card.add(box)
        card.connect("clicked", lambda _b, idx=i: (choose(idx), confirm()))
        row.pack_start(card, False, False, 0)
        cards.append(card)
        card._thumb = thumb
        card._client = client

    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
    scroller.add(row)
    outer.pack_start(scroller, True, True, 0)
    win.add(outer)
    restyle()

    def on_key(_w, event):
        key = event.keyval
        if key in (Gdk.KEY_Escape,):
            win.destroy()
            return True
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            confirm()
            return True
        if key in (Gdk.KEY_Right, Gdk.KEY_Tab, Gdk.KEY_Down):
            choose(selected["index"] + 1)
            return True
        if key in (Gdk.KEY_Left, Gdk.KEY_ISO_Left_Tab, Gdk.KEY_Up):
            choose(selected["index"] - 1)
            return True
        return False

    win.connect("key-press-event", on_key)
    win.show_all()

    def load_thumbs():
        for i, client in enumerate(clients[:8]):
            workspace = client.get("workspace") or {}
            if active_id is not None and workspace.get("id") != active_id:
                continue
            dest = os.path.join(thumb_dir, f"{i}.png")
            path = capture_thumbnail(client, dest)
            if not path:
                continue

            def apply_thumb(card=cards[i], image_path=path):
                try:
                    pix = GdkPixbuf.Pixbuf.new_from_file_at_size(image_path, 160, 90)
                    img = Gtk.Image.new_from_pixbuf(pix)
                    for child in list(card._thumb.get_children()):
                        card._thumb.remove(child)
                    card._thumb.pack_start(img, True, True, 0)
                    card._thumb.show_all()
                except Exception:
                    pass
                return False

            GLib.idle_add(apply_thumb)
        return False

    GLib.idle_add(load_thumbs)
    Gtk.main()
    return 0


def run_search():
    query_holder = {"q": ""}
    gtk = _try_gtk()
    if gtk:
        return _search_gtk(gtk, query_holder)
    return _search_wofi()


def _collect_search(query):
    apps = load_desktop_apps()
    recent = []
    xbel = os.path.expanduser("~/.local/share/recently-used.xbel")
    try:
        with open(xbel, encoding="utf-8", errors="replace") as handle:
            recent = parse_recently_used(handle.read())
    except OSError:
        pass
    files = file_results(query, recent_paths=recent)
    settings = settings_results(query)
    return search_items(query, apps, files, settings)


def _search_wofi():
    items = _collect_search("")
    lines = [result_label(item) for item in items]
    picked = _wofi_pick("Search apps, files, settings", lines)
    if not picked:
        # Second chance: treat whatever was typed as a query. wofi --dmenu
        # only returns the selected line, so re-run with that text if it
        # didn't match a known label (user typed a query and hit enter).
        return 0
    for item, line in zip(items, lines):
        if line == picked:
            return activate_result(item)
    items = _collect_search(picked)
    if not items:
        return 0
    lines = [result_label(item) for item in items]
    picked2 = _wofi_pick(f"Results for {picked}", lines)
    for item, line in zip(items, lines):
        if line == picked2:
            return activate_result(item)
    return 0


def _search_gtk(gtk, query_holder):
    Gtk, Gdk, _pixbuf, GLib = gtk
    win = _new_overlay_window(Gtk, Gdk, "Search", "darkos-search", 640, 480)
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    outer.set_border_width(16)
    entry = Gtk.Entry()
    entry.set_placeholder_text("Search apps, files, settings…")
    outer.pack_start(entry, False, False, 0)
    listbox = Gtk.ListBox()
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.add(listbox)
    outer.pack_start(scroller, True, True, 0)
    win.add(outer)
    state = {"items": []}

    def refill(query):
        query_holder["q"] = query
        for child in list(listbox.get_children()):
            listbox.remove(child)
        state["items"] = _collect_search(query)
        for item in state["items"]:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.set_border_width(6)
            kind = item.get("kind") or "item"
            badge = Gtk.Label(label=kind.upper())
            box.pack_start(badge, False, False, 0)
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            title = Gtk.Label(label=item.get("name") or "", xalign=0)
            subtitle = Gtk.Label(label=(item.get("comment") or item.get("path") or "")[:80], xalign=0)
            texts.pack_start(title, False, False, 0)
            texts.pack_start(subtitle, False, False, 0)
            box.pack_start(texts, True, True, 0)
            row.add(box)
            row._item = item
            listbox.add(row)
        listbox.show_all()
        if state["items"]:
            listbox.select_row(listbox.get_row_at_index(0))

    def activate_row(row):
        if row is None:
            return
        activate_result(row._item)
        win.destroy()

    def on_key(_w, event):
        if event.keyval == Gdk.KEY_Escape:
            win.destroy()
            return True
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            activate_row(listbox.get_selected_row())
            return True
        return False

    entry.connect("changed", lambda e: refill(e.get_text()))
    listbox.connect("row-activated", lambda _lb, row: activate_row(row))
    win.connect("key-press-event", on_key)
    refill("")
    win.show_all()
    entry.grab_focus()
    Gtk.main()
    return 0


def run_snap(side):
    if side not in SNAP_SIDES:
        print(f"darkos-window-fx: unknown --snap value {side!r}", file=sys.stderr)
        return 2
    monitors = _hyprctl_json("monitors") or []
    active = _hyprctl_json("activewindow")
    if not monitors or not active:
        return 1
    monitor = next(
        (m for m in monitors if m.get("id") == active.get("monitor")),
        monitors[0],
    )
    rect = monitor_logical_rect(monitor)
    target = snap_rect(rect["x"], rect["y"], rect["w"], rect["h"], side)
    if target is None:
        return 2
    if not active.get("floating"):
        _dispatch("togglefloating")
    x, y, w, h = target
    _dispatch("moveactive", "exact", str(x), str(y))
    _dispatch("resizeactive", "exact", str(w), str(h))
    return 0


def run_snap_picker():
    gtk = _try_gtk()
    if gtk:
        return _snap_picker_gtk(gtk)
    picked = _wofi_pick("Snap layout", list(SNAP_SIDES))
    if picked in SNAP_SIDES:
        return run_snap(picked)
    return 0


def _snap_picker_gtk(gtk):
    Gtk, Gdk, _pixbuf, _glib = gtk
    win = _new_overlay_window(Gtk, Gdk, "Snap layout", "darkos-snap-picker", 280, 220)
    grid = Gtk.Grid()
    grid.set_column_spacing(6)
    grid.set_row_spacing(6)
    grid.set_border_width(16)
    cells = (
        (0, 0, 1, 1, "top-left", "Top left"),
        (1, 0, 1, 1, "top-right", "Top right"),
        (0, 1, 1, 1, "bottom-left", "Bottom left"),
        (1, 1, 1, 1, "bottom-right", "Bottom right"),
        (0, 2, 1, 1, "left", "Left"),
        (1, 2, 1, 1, "right", "Right"),
        (0, 3, 2, 1, "maximize", "Maximize"),
    )

    def pick(side):
        win.destroy()
        run_snap(side)

    for col, row, w, h, side, label in cells:
        button = Gtk.Button(label=label)
        button.set_size_request(120, 36)
        button.connect("clicked", lambda _b, value=side: pick(value))
        grid.attach(button, col, row, w, h)
    win.add(grid)

    def on_key(_w, event):
        if event.keyval == Gdk.KEY_Escape:
            win.destroy()
            return True
        return False

    win.connect("key-press-event", on_key)
    win.show_all()
    Gtk.main()
    return 0


def run_overview():
    clients = _hyprctl_json("clients") or []
    groups = group_clients_by_workspace(clients)
    if not groups:
        return 0
    gtk = _try_gtk()
    if gtk:
        return _overview_gtk(groups, gtk)
    lines = []
    mapping = []
    for workspace, members in groups.items():
        for client in members:
            line = f"WS {workspace}  —  {switcher_label(client)}"
            lines.append(line)
            mapping.append((line, client, workspace))
    picked = _wofi_pick("Workspaces", lines)
    for line, client, workspace in mapping:
        if line == picked:
            _dispatch("workspace", str(workspace))
            _dispatch("focuswindow", f"address:{client['address']}")
            return 0
    return 0


def _overview_gtk(groups, gtk):
    Gtk, Gdk, _pixbuf, _glib = gtk
    win = _new_overlay_window(Gtk, Gdk, "Workspaces", "darkos-overview", 900, 420)
    outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    outer.set_border_width(16)
    for workspace, members in groups.items():
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        header = Gtk.Button(label=f"Workspace {workspace}")
        header.connect("clicked", lambda _b, ws=workspace: (_dispatch("workspace", str(ws)), win.destroy()))
        column.pack_start(header, False, False, 0)
        for client in members:
            button = Gtk.Button(label=str(client.get("title") or "")[:48])
            button.connect(
                "clicked",
                lambda _b, c=client, ws=workspace: (
                    _dispatch("workspace", str(ws)),
                    _dispatch("focuswindow", f"address:{c['address']}"),
                    win.destroy(),
                ),
            )
            column.pack_start(button, False, False, 0)
        outer.pack_start(column, True, True, 0)
    scroller = Gtk.ScrolledWindow()
    scroller.add(outer)
    win.add(scroller)

    def on_key(_w, event):
        if event.keyval == Gdk.KEY_Escape:
            win.destroy()
            return True
        return False

    win.connect("key-press-event", on_key)
    win.show_all()
    Gtk.main()
    return 0


def current_zoom():
    for option in ("cursor:zoom_factor", "misc:cursor_zoom_factor"):
        data = _hyprctl_getoption(option)
        if not data:
            continue
        for key in ("float", "value"):
            if key in data:
                try:
                    return float(data[key]), option
                except (TypeError, ValueError):
                    continue
    return ZOOM_MIN, "cursor:zoom_factor"


def apply_zoom(factor, option=None):
    option = option or "cursor:zoom_factor"
    if not _keyword(option, factor) and option != "misc:cursor_zoom_factor":
        _keyword("misc:cursor_zoom_factor", factor)
    return 0


def run_zoom(action):
    current, option = current_zoom()
    return apply_zoom(next_zoom(current, action), option)


def load_user_settings(path=None):
    path = path or os.path.expanduser("~/.config/darkos/settings.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def run_a11y_apply(settings=None):
    settings = load_user_settings() if settings is None else settings
    if settings.get("a11y_magnifier"):
        return apply_zoom(ZOOM_ON)
    return apply_zoom(ZOOM_MIN)


def main():
    argv = sys.argv[1:]
    if "--switcher" in argv:
        return run_switcher()
    if "--search" in argv:
        return run_search()
    if "--overview" in argv:
        return run_overview()
    if "--snap-picker" in argv:
        return run_snap_picker()
    if "--a11y-apply" in argv:
        return run_a11y_apply()
    if "--zoom" in argv:
        idx = argv.index("--zoom")
        action = argv[idx + 1] if idx + 1 < len(argv) else ""
        if action not in ("in", "out", "reset", "on", "off", "toggle"):
            print(f"usage: {sys.argv[0]} --zoom {{in,out,reset,on,off,toggle}}", file=sys.stderr)
            return 2
        return run_zoom(action)
    if "--snap" in argv:
        idx = argv.index("--snap")
        side = argv[idx + 1] if idx + 1 < len(argv) else ""
        return run_snap(side)
    print(
        f"usage: {sys.argv[0]} --switcher | --search | --overview | "
        f"--snap-picker | --snap {{{','.join(SNAP_SIDES)}}} | "
        f"--zoom {{in,out,reset,on,off,toggle}} | --a11y-apply",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
