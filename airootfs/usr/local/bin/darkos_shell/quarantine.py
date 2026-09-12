"""Quarantine storage: move flagged files aside with restore, never delete
silently. Decides nothing about what gets quarantined or why -- callers
(Shield's continuous-protection watcher, on-demand scans) pass a path and
a reason; this module only owns the move/restore/list/purge mechanics.

architecture.md is explicit: "flagged files move to a quarantine folder
with one-click restore -- false positives are normal for heuristic AV, and
silent deletion loses user trust and data." Every function here is built
around that: restore is always possible until permanent_delete is called
explicitly, and nothing here ever unlinks the original in place.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import json
import os
import shutil
import time
import uuid

QUARANTINE_DIR = Path.home() / ".local" / "share" / "darkos" / "quarantine"


@dataclass
class QuarantineEntry:
    """One quarantined file's record. `id` is the sidecar/blob's shared
    filename stem -- stable, filesystem-safe, and never the original name
    (a malicious filename shouldn't get to choose where it lands)."""

    id: str
    original_path: str
    reason: str
    quarantined_at: float
    sha256: str

    def blob_path(self) -> Path:
        return QUARANTINE_DIR / f"{self.id}.blob"

    def meta_path(self) -> Path:
        return QUARANTINE_DIR / f"{self.id}.meta.json"


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quarantine_file(path: Path, reason: str) -> QuarantineEntry:
    """Move `path` into quarantine and record why. Raises the same errors
    `shutil.move`/`open` would (missing file, permission denied) rather
    than swallowing them -- callers already handle scan-level failures
    and should see this kind too, not have it hidden.

    `reason` is caller-supplied (e.g. a ClamAV signature name) -- this
    module doesn't interpret it, only stores it.

    Preserves the original file's owner on the quarantined copy. Matters
    once a root-owned daemon (the fanotify watcher) is what's calling
    this, not just the user's own unprivileged Security Center session --
    without this, a root-quarantined file couldn't be restored later by
    the user who's supposed to get the one-click restore. A no-op in the
    unprivileged case, since a user's own files are already theirs."""
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    path = Path(path).resolve()
    original_stat = path.stat()
    entry = QuarantineEntry(
        id=uuid.uuid4().hex,
        original_path=str(path),
        reason=reason,
        quarantined_at=time.time(),
        sha256=_sha256_of(path),
    )
    shutil.move(str(path), str(entry.blob_path()))
    entry.meta_path().write_text(json.dumps(asdict(entry), indent=2))
    try:
        os.chown(entry.blob_path(), original_stat.st_uid, original_stat.st_gid)
        os.chown(entry.meta_path(), original_stat.st_uid, original_stat.st_gid)
    except PermissionError:
        pass  # unprivileged caller quarantining their own file: already correct
    return entry


def list_quarantine() -> list[QuarantineEntry]:
    """All currently-quarantined entries, newest first. Skips a sidecar
    whose blob has gone missing (e.g. hand-deleted outside this module)
    rather than raising -- the UI should be able to always render a list."""
    if not QUARANTINE_DIR.exists():
        return []
    entries = []
    for meta_file in QUARANTINE_DIR.glob("*.meta.json"):
        try:
            data = json.loads(meta_file.read_text())
            entry = QuarantineEntry(**data)
        except (json.JSONDecodeError, TypeError, KeyError):
            continue
        if entry.blob_path().exists():
            entries.append(entry)
    return sorted(entries, key=lambda e: e.quarantined_at, reverse=True)


def restore(entry_id: str, target_path: Path | None = None) -> tuple[bool, str]:
    """Move a quarantined file back. Defaults to its original path; if
    that path now has something else there, this refuses rather than
    overwriting it -- pass an explicit `target_path` once the caller (or
    the user, via the UI) has resolved the conflict. Returns (ok, message)
    instead of raising, since both outcomes are routine for a restore
    action, not exceptional."""
    meta_path = QUARANTINE_DIR / f"{entry_id}.meta.json"
    if not meta_path.exists():
        return False, "No quarantine record with that id."
    entry = QuarantineEntry(**json.loads(meta_path.read_text()))
    if not entry.blob_path().exists():
        return False, "Quarantined file is missing on disk."
    dest = Path(target_path) if target_path else Path(entry.original_path)
    if dest.exists():
        return False, f"{dest} already exists -- choose a different restore location."
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(entry.blob_path()), str(dest))
    meta_path.unlink()
    return True, f"Restored to {dest}"


def permanent_delete(entry_id: str) -> bool:
    """Explicit, named permanent delete -- the one function in this module
    that doesn't leave a way back. Never called automatically by anything
    else here; a UI action, not a scan outcome."""
    meta_path = QUARANTINE_DIR / f"{entry_id}.meta.json"
    if not meta_path.exists():
        return False
    entry = QuarantineEntry(**json.loads(meta_path.read_text()))
    entry.blob_path().unlink(missing_ok=True)
    meta_path.unlink()
    return True
