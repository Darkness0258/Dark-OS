#!/usr/bin/env python3
"""Drive the REAL shell through every dock position and size on a headless
wlroots compositor and check, for each one:

  * the dock's own state,
  * the exclusive zone it reserved -- measured from the space sway gives an
    ordinary tiled window, so it is what a maximised app would really get,
  * a screenshot (written to $HEADLESS_SHOTS, default: a temp directory).

Settings are changed the way the Settings app does it (an atomic write of
settings.json); the running shell has to pick the change up on its own.

Run through ci/headless/run-all.sh, or inside a session started with
ci/headless/lib.sh.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.environ["DARKOS_BIN"])
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from darkos_shell import DarkOSApplication  # noqa: E402
from darkos_shell.tokens import DOCK_EDGE_MARGIN, dock_exclusive_zone  # noqa: E402
from darkos_shell.user_settings import DEFAULTS, save_settings, settings_path  # noqa: E402

OUT_W, OUT_H = 1920, 1080
# The icon rail: exclusive_zone 68 plus its 12px left margin (wlroots adds the margin).
RAIL_RESERVED_LEFT = 68 + 12
SHOTS = os.environ.get("HEADLESS_SHOTS") or tempfile.mkdtemp(prefix="darkos-dock-")

app = DarkOSApplication()
app.register(None)
app.activate()
probe = Gtk.Window(title="probe")  # an ordinary toplevel: sway tiles it into the usable area
probe.show_all()


def probe_rect():
    tree = json.loads(subprocess.run(["swaymsg", "-t", "get_tree"], capture_output=True, text=True).stdout)

    def walk(node):
        if node.get("name") == "probe" and node.get("pid"):
            return node["rect"]
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            found = walk(child)
            if found:
                return found
        return None

    return walk(tree)


def write_atomic(position, size):
    data = dict(DEFAULTS, dock_position=position, dock_size=size)
    assert save_settings(data)


def write_raw(text):  # what a hand edit does: no atomic rename
    with open(settings_path(), "w", encoding="utf-8") as handle:
        handle.write(text)


STEPS = [
    ("01 default (no settings file)", None, ("bottom", "default")),
    ("02 top", lambda: write_atomic("top", "default"), ("top", "default")),
    ("03 left", lambda: write_atomic("left", "default"), ("left", "default")),
    ("04 right", lambda: write_atomic("right", "default"), ("right", "default")),
    ("05 bottom compact", lambda: write_atomic("bottom", "compact"), ("bottom", "compact")),
    ("06 bottom large", lambda: write_atomic("bottom", "large"), ("bottom", "large")),
    ("07 left large", lambda: write_atomic("left", "large"), ("left", "large")),
    ("08 right compact", lambda: write_atomic("right", "compact"), ("right", "compact")),
    ("09 invalid values (hand edit)",
     lambda: write_raw(json.dumps({"dock_position": "diagonal", "dock_size": 99})), ("bottom", "default")),
    ("10 back to default", lambda: write_atomic("bottom", "default"), ("bottom", "default")),
]

results, zones = [], {}


def check(label, ok, detail=""):
    results.append(ok)
    print(("  PASS " if ok else "  FAIL ") + label + (f"  [{detail}]" if detail else ""), flush=True)


def verify(name, want_position, want_size):
    dock = app.dock
    print(f"== {name}", flush=True)
    layout = dock._layout
    check("dock layout state", (layout.position, layout.size) == (want_position, want_size),
          f"got {layout.position}/{layout.size}")
    allocation = dock.get_allocation()
    thickness = allocation.width if layout.vertical else allocation.height
    zone = dock_exclusive_zone(layout, thickness)
    check("exclusive zone == margin + measured thickness + clearance", dock._exclusive_zone == zone,
          f"zone={dock._exclusive_zone} thickness={thickness} dock={allocation.width}x{allocation.height}")
    zones[(want_position, want_size)] = (zone, allocation.width, allocation.height)

    reserved = zone + DOCK_EDGE_MARGIN  # compositors add the margin on the anchored edge
    left = RAIL_RESERVED_LEFT + (reserved if want_position == "left" else 0)
    right = reserved if want_position == "right" else 0
    top = reserved if want_position == "top" else 0
    bottom = reserved if want_position == "bottom" else 0
    expected = {"x": left, "y": top, "width": OUT_W - left - right, "height": OUT_H - top - bottom}
    rect = probe_rect()
    got = {key: rect[key] for key in ("x", "y", "width", "height")} if rect else None
    check("sway usable area for a tiled window matches the reservation", got == expected,
          f"expected {expected} got {got}")
    slug = name.split()[0] + "-" + "".join(c if c.isalnum() else "_" for c in name[3:])
    subprocess.run(["grim", os.path.join(SHOTS, slug + ".png")])


loop = GLib.MainLoop()
state = {"index": 0}


def run_step():
    _name, action, _want = STEPS[state["index"]]
    if action:
        action()
    GLib.timeout_add(1600, finish_step)  # file event + 150ms debounce + layout + compositor commit
    return False


def finish_step():
    name, _action, (position, size) = STEPS[state["index"]]
    verify(name, position, size)
    state["index"] += 1
    if state["index"] >= len(STEPS):
        loop.quit()
    else:
        GLib.idle_add(run_step)
    return False


GLib.timeout_add(1500, run_step)
loop.run()

print("\nzones (position/size -> zone, dock WxH):")
for key, (zone, width, height) in zones.items():
    print("  %-16s zone=%-4d dock=%dx%d" % ("/".join(key), zone, width, height))
compact, default, large = (zones[("bottom", size)][0] for size in ("compact", "default", "large"))
check("zone grows with size: compact < default < large", compact < default < large, f"{compact} < {default} < {large}")
# Left and right docks are the same width; use whichever one the steps visited for each size.
vertical = [next(width for (pos, sz), (_zone, width, _h) in zones.items() if sz == size and pos in ("left", "right"))
            for size in ("compact", "default", "large")]
check("a vertical dock gets wider with size", vertical == sorted(vertical) and len(set(vertical)) == 3, str(vertical))

try:
    from PIL import Image, ImageDraw

    names = sorted(f for f in os.listdir(SHOTS) if f.endswith(".png") and f[0].isdigit())
    cell_w, cell_h, cols = 640, 360, 3
    rows = (len(names) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * (cell_h + 22)), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    for i, fname in enumerate(names):
        x, y = (i % cols) * cell_w, (i // cols) * (cell_h + 22)
        sheet.paste(Image.open(os.path.join(SHOTS, fname)).convert("RGB").resize((cell_w, cell_h)), (x, y + 22))
        draw.text((x + 6, y + 5), fname[:-4], fill=(0, 230, 255))
    sheet.save(os.path.join(SHOTS, "contact-sheet.png"))
except ImportError:
    pass

print(f"\nscreenshots: {SHOTS}")
print("RESULT: %d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
