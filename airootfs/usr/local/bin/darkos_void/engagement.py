#!/usr/bin/env python3
"""The engagement workspace: a name, a target and a notes folder.

An engagement is a directory under `~/engagements/<slug>/` with four
subfolders (`scans`, `loot`, `notes`, `logs`) and an `engagement.json`
holding the human-readable name, the current target and a created
timestamp. `darkos-terminal.py` exports the active engagement's `TARGET`
and `ENGAGEMENT_DIR` into every new pane via VTE's `envv` (which *adds*
variables to the inherited environment rather than replacing it, so PATH,
HOME, etc. are untouched — see `TerminalPage._envv_for`).

No GTK here: everything is plain `pathlib`/`json`/`dataclasses`, so it can
be unit-tested without a display.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SUBDIRS = ("scans", "loot", "notes", "logs")
_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def default_root() -> Path:
    """`~/engagements`. Honours `$HOME` so tests can redirect it."""
    return Path(os.environ.get("HOME") or Path.home()) / "engagements"


def slugify(name: str) -> str:
    """A filesystem-safe directory name for an engagement's display name.

    Collapses anything that is not `[A-Za-z0-9._-]` to a single `-`, trims
    leading/trailing `-`/`.` (blocks a bare ".." traversal and hidden-dotfile
    surprises), and falls back to a timestamp if that leaves nothing —
    e.g. a name that is only emoji/punctuation.
    """
    slug = _SLUG_UNSAFE.sub("-", name.strip()).strip("-.")
    return slug or f"engagement-{int(time.time())}"


@dataclass
class Engagement:
    name: str
    target: str
    dir: Path
    created: str

    def to_dict(self) -> dict:
        return {"name": self.name, "target": self.target, "created": self.created}

    @property
    def json_path(self) -> Path:
        return self.dir / "engagement.json"

    def env(self) -> dict[str, str]:
        """The env vars a new pane for this engagement should get."""
        env = {"ENGAGEMENT_DIR": str(self.dir)}
        if self.target:
            env["TARGET"] = self.target
        return env


class EngagementError(ValueError):
    """An engagement could not be created or loaded."""


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def create_engagement(name: str, target: str = "", root: Path | None = None) -> Engagement:
    """Create `<root>/<slug(name)>/{scans,loot,notes,logs}` + engagement.json.

    Idempotent on the directories (`mkdir(parents=True, exist_ok=True)`);
    raises `EngagementError` if `engagement.json` already exists there, so
    this never silently overwrites an existing engagement's metadata — use
    `update_target` for that.
    """
    name = name.strip()
    if not name:
        raise EngagementError("An engagement needs a name.")
    root = root or default_root()
    engagement_dir = root / slugify(name)
    for sub in SUBDIRS:
        (engagement_dir / sub).mkdir(parents=True, exist_ok=True)
    # Microsecond resolution (not time.strftime's whole seconds) so two
    # engagements created in the same second still sort newest-first in
    # list_engagements instead of tying and falling back to name order.
    engagement = Engagement(name=name, target=target.strip(), dir=engagement_dir,
                             created=datetime.now().isoformat(timespec="microseconds"))
    if engagement.json_path.exists():
        raise EngagementError(f"An engagement already exists at {engagement_dir}.")
    _atomic_write_json(engagement.json_path, engagement.to_dict())
    return engagement


def load_engagement(engagement_dir: Path) -> Engagement:
    engagement_dir = Path(engagement_dir)
    try:
        data = json.loads((engagement_dir / "engagement.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EngagementError(f"Cannot read engagement.json in {engagement_dir}: {exc}") from exc
    return Engagement(
        name=data.get("name") or engagement_dir.name,
        target=data.get("target") or "",
        dir=engagement_dir,
        created=data.get("created") or "",
    )


def list_engagements(root: Path | None = None) -> list[Engagement]:
    """Every engagement under `root`, most recently created first."""
    root = root or default_root()
    if not root.is_dir():
        return []
    found = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "engagement.json").is_file():
            try:
                found.append(load_engagement(child))
            except EngagementError:
                continue  # corrupt engagement.json: skip rather than crash the list
    found.sort(key=lambda e: e.created, reverse=True)
    return found


def update_target(engagement: Engagement, target: str) -> Engagement:
    """Rewrite `engagement.json` with a new target; returns the updated record."""
    engagement.target = target.strip()
    _atomic_write_json(engagement.json_path, engagement.to_dict())
    return engagement
