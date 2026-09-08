#!/usr/bin/env python3
"""Focused arithmetic and timer regressions, without GTK or real waiting."""
import ast
import math
import operator
from pathlib import Path
import time
import types
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

BIN = Path(__file__).resolve().parents[1] / "airootfs/usr/local/bin"


def extract(filename, names, namespace):
    tree = ast.parse((BIN / filename).read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    exec(compile(tree, filename, "exec"), namespace)
    return namespace


calc = extract("darkos-calculator.py", {"safe_eval", "bounded_number"}, {
    "ast": ast, "math": math, "MAX_EXPRESSION_LENGTH": 512, "MAX_INTEGER_BITS": 4096,
    "_BIN_OPS": {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                 ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow},
    "_UNARY_OPS": {ast.UAdd: operator.pos, ast.USub: operator.neg},
})
clock = extract("darkos-clock.py", {"ClockWindow", "format_hms"}, {
    "Gtk": types.SimpleNamespace(ApplicationWindow=object), "time": time,
    "math": math, "datetime": datetime,
})


class CalculatorTests(unittest.TestCase):
    def test_real_button_symbols(self):
        for expression, expected in (("12−8", 4), ("−4×3", -12), ("12÷3", 4), ("2^10", 1024), ("2**1000", 2**1000)):
            self.assertEqual(calc["safe_eval"](expression), expected)

    def test_unsafe_or_unbounded_expressions(self):
        for expression in ("True", "__import__('os')", "2**999999999999", "1e999", "(-1)**0.5", "2**(2**1000)", "1+" * 100 + "1", "1" * 513):
            with self.subTest(expression=expression):
                with self.assertRaises(ValueError):
                    calc["safe_eval"](expression)


class TimerTests(unittest.TestCase):
    def test_delayed_tick_uses_elapsed_time_and_fires_once(self):
        window = types.SimpleNamespace(
            timer_running=True, timer_remaining=10, timer_deadline=110,
            timer_start_btn=Mock(), timer_label=Mock(), time_label=Mock(), date_label=Mock(),
            world_list=Mock(), alarms=[], stopwatch_running=False, _toast=Mock(),
        )
        window.world_list.get_children.return_value = []
        with patch.object(time, "monotonic", return_value=107.2):
            clock["ClockWindow"]._tick(window)
        self.assertAlmostEqual(window.timer_remaining, 2.8)
        window.timer_label.set_markup.assert_called_with("<span size='36000'>00:03</span>")
        with patch.object(time, "monotonic", return_value=115):
            clock["ClockWindow"]._tick(window)
            clock["ClockWindow"]._tick(window)
        self.assertFalse(window.timer_running)
        window._toast.assert_called_once_with("Timer finished")

    def test_pause_resume_keeps_remaining_duration(self):
        window = types.SimpleNamespace(timer_running=True, timer_deadline=110, timer_remaining=10, timer_start_btn=Mock())
        with patch.object(time, "monotonic", return_value=104):
            clock["ClockWindow"]._timer_toggle(window)
        self.assertEqual(window.timer_remaining, 6)
        with patch.object(time, "monotonic", return_value=200):
            clock["ClockWindow"]._timer_toggle(window)
        self.assertEqual(window.timer_deadline, 206)


if __name__ == "__main__":
    unittest.main(verbosity=2)
