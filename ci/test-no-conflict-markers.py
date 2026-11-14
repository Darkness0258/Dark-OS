#!/usr/bin/env python3
"""No tracked file may contain git conflict markers.

When `git merge` stops on conflicts it writes <<<<<<< / ======= / >>>>>>> into the
files. `git add .` followed by `git commit` then records the markers as content, and
the first symptom is a confusing failure somewhere else (`bash -n build-iso.sh`
reporting a syntax error near unexpected token `<<<`). This check runs first in CI
and says what actually happened and where.

A lone `=======` is not a marker (Markdown and reStructuredText use it for
underlines); a file counts only if it has an opening `<<<<<<< ` or a closing
`>>>>>>> ` line.
"""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPEN = re.compile(r"^<<<<<<< ")
CLOSE = re.compile(r"^>>>>>>> ")
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".zip", ".gz", ".xz", ".zst", ".pdf",
                 ".ttf", ".otf", ".woff", ".woff2", ".qm", ".so", ".pyc"}


def find_markers(text):
    """[(line number, line)] for every opening or closing conflict marker in `text`."""
    return [(n, line.rstrip()) for n, line in enumerate(text.splitlines(), 1)
            if OPEN.match(line) or CLOSE.match(line)]


def tracked_files(root=ROOT):
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, timeout=30, check=True).stdout
        return [root / p for p in out.decode("utf-8", "replace").split("\0") if p]
    except (OSError, subprocess.SubprocessError):
        return [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]


def scan(files, root=ROOT):
    found = {}
    for path in files:
        if path.suffix.lower() in SKIP_SUFFIXES or path.is_symlink() or not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:8192]:
            continue                      # binary
        hits = find_markers(raw.decode("utf-8", "replace"))
        if hits:
            found[str(path.relative_to(root))] = hits
    return found


class ConflictMarkerTests(unittest.TestCase):
    def test_no_tracked_file_has_conflict_markers(self):
        found = scan(tracked_files())
        report = "\n".join(f"  {name}:{n}: {line}" for name, hits in sorted(found.items()) for n, line in hits)
        self.assertEqual(found, {}, "unresolved merge conflict markers were committed:\n" + report +
                         "\nResolve them (git status shows 'Unmerged paths' during a merge) before 'git add'.")

    def test_the_scanner_finds_real_markers(self):
        text = "a\n<<<<<<< HEAD\nmine\n=======\ntheirs\n>>>>>>> origin/main\nb\n"
        self.assertEqual([n for n, _ in find_markers(text)], [2, 6])

    def test_markdown_underlines_and_indented_text_are_not_markers(self):
        text = "Title\n=======\n\n    <<<<<<< quoted in a code block\nx >>>>>>> y\n"
        self.assertEqual(find_markers(text), [])

    def test_scan_skips_binaries_and_reports_by_relative_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.sh").write_text("echo 1\n<<<<<<< HEAD\necho 2\n>>>>>>> x\n")
            (root / "good.md").write_text("Heading\n=======\n")
            (root / "blob.bin").write_bytes(b"\0\1<<<<<<< HEAD\n")
            found = scan(sorted(root.iterdir()), root)
            self.assertEqual(list(found), ["bad.sh"])
            self.assertEqual([n for n, _ in found["bad.sh"]], [2, 4])


if __name__ == "__main__":
    sys.exit(unittest.main(verbosity=1))
