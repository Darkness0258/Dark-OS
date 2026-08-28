#!/usr/bin/env python3
"""DarkOS Calculator — standard calculator with a safe expression evaluator.

Deliberately does not use eval()/exec() on the typed expression — arithmetic
is parsed into an AST and walked, allowing only numeric literals and +-*/%**
so nothing but arithmetic can ever execute, regardless of what's typed or
pasted in.
"""
import ast
import operator
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, run_app  # noqa: E402

APP_ID = "org.darkos.Calculator"
WM_CLASS = "darkos-calculator"

_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def safe_eval(expr):
    """Evaluate a plain arithmetic expression without eval(). Raises
    ValueError for anything that isn't a numeric literal or +-*/%** — no
    names, calls, attributes, subscripts, or comparisons are ever allowed
    to reach Python's evaluator."""
    expr = expr.strip().replace("×", "*").replace("÷", "/").replace("^", "**")
    if not expr:
        raise ValueError("empty expression")
    try:
        node = ast.parse(expr, mode="eval").body
    except SyntaxError as e:
        raise ValueError(str(e)) from e

    def _eval(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN_OPS:
            return _BIN_OPS[type(n.op)](_eval(n.left), _eval(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UNARY_OPS:
            return _UNARY_OPS[type(n.op)](_eval(n.operand))
        raise ValueError("only plain arithmetic is allowed")

    return _eval(node)


def format_result(value):
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        value = int(value)
    text = f"{value:.10g}" if isinstance(value, float) else str(value)
    return text


BUTTONS = [
    ("C", "func"), ("⌫", "func"), ("%", "op"), ("÷", "op"),
    ("7", "digit"), ("8", "digit"), ("9", "digit"), ("×", "op"),
    ("4", "digit"), ("5", "digit"), ("6", "digit"), ("−", "op"),
    ("1", "digit"), ("2", "digit"), ("3", "digit"), ("+", "op"),
    ("0", "digit0"), (".", "digit"), ("=", "equals"),
]

KEYVAL_TO_LABEL = {
    Gdk.KEY_plus: "+", Gdk.KEY_KP_Add: "+",
    Gdk.KEY_minus: "−", Gdk.KEY_KP_Subtract: "−",
    Gdk.KEY_asterisk: "×", Gdk.KEY_KP_Multiply: "×",
    Gdk.KEY_slash: "÷", Gdk.KEY_KP_Divide: "÷",
    Gdk.KEY_percent: "%",
    Gdk.KEY_period: ".", Gdk.KEY_KP_Decimal: ".",
    Gdk.KEY_Return: "=", Gdk.KEY_KP_Enter: "=", Gdk.KEY_equal: "=",
    Gdk.KEY_BackSpace: "⌫",
    Gdk.KEY_Escape: "C",
}
for _i in range(10):
    KEYVAL_TO_LABEL[getattr(Gdk, f"KEY_{_i}")] = str(_i)
    KEYVAL_TO_LABEL[getattr(Gdk, f"KEY_KP_{_i}")] = str(_i)


class CalculatorWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Calculator")
        self.set_default_size(340, 520)
        self.set_resizable(False)
        add_class(self, "app-window")

        self.expression = ""
        self.just_evaluated = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        self.history_store = Gtk.ListBox()
        self.history_store.set_selection_mode(Gtk.SelectionMode.NONE)
        add_class(self.history_store, "sidebar")
        history_scroller = Gtk.ScrolledWindow()
        history_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        history_scroller.set_size_request(-1, 110)
        history_scroller.add(self.history_store)
        root.pack_start(history_scroller, False, False, 0)
        root.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        display_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        display_box.set_border_width(16)
        self.expr_label = Gtk.Label(label="", xalign=1.0)
        add_class(self.expr_label, "path-crumb")
        self.display = Gtk.Label(label="0", xalign=1.0)
        self.display.set_ellipsize(Pango.EllipsizeMode.START)
        display_box.pack_start(self.expr_label, False, False, 0)
        display_box.pack_start(self.display, False, False, 0)
        root.pack_start(display_box, False, False, 0)

        grid = Gtk.Grid(row_spacing=6, column_spacing=6, column_homogeneous=True, row_homogeneous=True)
        grid.set_border_width(12)
        row = col = 0
        for label, kind in BUTTONS:
            btn = Gtk.Button(label=label)
            add_class(btn, "action-button" if kind == "equals" else "icon-button")
            btn.connect("clicked", self._on_button, label)
            if label == "0":
                grid.attach(btn, col, row, 2, 1)
                col += 2
            elif label == "=":
                grid.attach(btn, col, row, 2, 1)
                col += 2
            else:
                grid.attach(btn, col, row, 1, 1)
                col += 1
            if col >= 4:
                col = 0
                row += 1
        root.pack_start(grid, True, True, 0)

        self.connect("key-press-event", self._on_key_press)
        self.history_store.connect("row-activated", self._on_history_row)
        self._refresh_display()

    # -- input handling ----------------------------------------------------
    def _on_key_press(self, _widget, event):
        label = KEYVAL_TO_LABEL.get(event.keyval)
        if label:
            self._on_button(None, label)
            return True
        return False

    def _on_button(self, _btn, label):
        if label == "C":
            self.expression = ""
            self.just_evaluated = False
        elif label == "⌫":
            self.expression = self.expression[:-1]
            self.just_evaluated = False
        elif label == "=":
            self._evaluate()
            return
        else:
            if self.just_evaluated and label not in ("+", "−", "×", "÷", "%"):
                self.expression = ""
            self.just_evaluated = False
            self.expression += label
        self._refresh_display()

    def _evaluate(self):
        if not self.expression.strip():
            return
        try:
            result = safe_eval(self.expression)
            text = format_result(result)
        except ZeroDivisionError:
            text = "Error: divide by zero"
        except (ValueError, OverflowError):
            text = "Error"
        self._add_history(self.expression, text)
        self.expression = text
        self.just_evaluated = True
        self._refresh_display(expr_override="")

    def _refresh_display(self, expr_override=None):
        expr = self.expression if expr_override is None else expr_override
        self.expr_label.set_text(expr if self.just_evaluated else "")
        self.display.set_text(self.expression if self.expression else "0")

    def _add_history(self, expr, result):
        if "Error" in result:
            return
        row = Gtk.ListBoxRow()
        label = Gtk.Label(label=f"{expr}  =  {result}", xalign=1.0)
        label.set_margin_top(4)
        label.set_margin_bottom(4)
        label.set_margin_end(8)
        add_class(label, "sidebar-row")
        row.add(label)
        row.result_text = result
        self.history_store.prepend(row)
        row.show_all()
        rows = self.history_store.get_children()
        if len(rows) > 30:
            self.history_store.remove(rows[-1])

    def _on_history_row(self, _box, row):
        self.expression = row.result_text
        self.just_evaluated = True
        self._refresh_display(expr_override="")


def build_window(app):
    return CalculatorWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
