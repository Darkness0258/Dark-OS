#!/usr/bin/env python3
"""The command palette's command list and its filter.

`darkos-terminal.py` maps each `Command.id` to a bound method and shows
`BASE_COMMANDS` filtered by `filter_commands(query)`. Kept here, with no
GTK import, so the filter/ranking logic is unit-testable on its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Command:
    id: str
    title: str
    category: str
    keywords: tuple[str, ...] = field(default_factory=tuple)


BASE_COMMANDS: tuple[Command, ...] = (
    Command("new-tab", "New Tab", "Tabs & Panes", ("shell", "terminal")),
    Command("close-pane", "Close Pane", "Tabs & Panes", ("close", "quit")),
    Command("split-right", "Split Right", "Tabs & Panes", ("split", "vertical", "pane")),
    Command("split-down", "Split Down", "Tabs & Panes", ("split", "horizontal", "pane")),
    Command("find", "Find in Scrollback", "Search", ("search", "grep", "regex")),
    Command("new-engagement", "New Engagement", "Engagement", ("target", "workspace", "pentest")),
    Command("switch-engagement", "Switch Engagement", "Engagement", ("target", "workspace")),
    Command("set-target", "Set Target", "Engagement", ("target", "ip", "host")),
    Command("start-log", "Start Session Log", "Engagement", ("script", "record", "transcript")),
    Command("tool-launcher", "Open Tool Launcher", "Tools", ("blackarch", "nmap", "security")),
    Command("save-scrollback", "Save Scrollback As...", "Tools", ("export", "text", "file")),
    Command("copy", "Copy", "Edit", ("clipboard",)),
    Command("paste", "Paste", "Edit", ("clipboard",)),
    Command("zoom-in", "Zoom In", "View", ("font", "bigger")),
    Command("zoom-out", "Zoom Out", "View", ("font", "smaller")),
    Command("zoom-reset", "Reset Zoom", "View", ("font",)),
)


def filter_commands(query: str, commands: tuple[Command, ...] = BASE_COMMANDS) -> list[Command]:
    """Commands whose title/keywords/category contain `query`
    (case-insensitive), title-starts-with ranked above contains, then
    original order. Empty query returns everything, in order."""
    q = query.strip().lower()
    if not q:
        return list(commands)

    def rank(cmd: Command):
        title = cmd.title.lower()
        haystack = " ".join((title, cmd.category.lower(), *cmd.keywords))
        if q not in haystack:
            return None
        return (0 if title.startswith(q) else 1, len(title))

    ranked = [(rank(c), c) for c in commands]
    matched = [(r, c) for r, c in ranked if r is not None]
    matched.sort(key=lambda pair: pair[0])
    return [c for _, c in matched]
