"""Small custom widgets for the shell.

ResourceRow replaces the old ring gauges: a label, a thin bar and a number on
one line, so a resource read-out costs one row instead of a quarter of a
panel (docs/MASTER-PLAN.md section 5: no giant gauges).
"""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from darkos_shell.tokens import SPACE_SM


class ResourceRow(Gtk.Box):
    """`CPU  [=====----]  42%`. The bar turns amber at WARN_AT and red at
    CRIT_AT, so colour only appears when it means something."""

    WARN_AT = 85.0
    CRIT_AT = 95.0

    def __init__(self, title):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_SM)
        self.title = Gtk.Label(label=title)
        self.title.set_xalign(0.0)
        self.title.set_size_request(72, -1)
        self.title.get_style_context().add_class("resource-label")

        self.bar = Gtk.ProgressBar()
        self.bar.set_valign(Gtk.Align.CENTER)
        self.bar.set_hexpand(True)
        self.bar.get_style_context().add_class("resource-bar")

        self.value = Gtk.Label(label="--")
        self.value.set_xalign(1.0)
        self.value.set_width_chars(5)
        self.value.get_style_context().add_class("resource-value")

        self.pack_start(self.title, False, False, 0)
        self.pack_start(self.bar, True, True, 0)
        self.pack_start(self.value, False, False, 0)
        # show_all() on the parent must not resurrect a row that has no data.
        self.set_no_show_all(True)
        self.show()
        self.title.show()
        self.bar.show()
        self.value.show()

    def set_percent(self, percent):
        """Show `percent` (0-100). None means the source doesn't exist on this
        machine (no GPU counters, say), so the whole row is hidden."""
        if percent is None:
            self.hide()
            return
        self.show()
        percent = max(0.0, min(100.0, float(percent)))
        self.bar.set_fraction(percent / 100.0)
        self.value.set_text(f"{percent:.0f}%")
        context = self.bar.get_style_context()
        for name in ("warn", "crit"):
            context.remove_class(name)
        if percent >= self.CRIT_AT:
            context.add_class("crit")
        elif percent >= self.WARN_AT:
            context.add_class("warn")
