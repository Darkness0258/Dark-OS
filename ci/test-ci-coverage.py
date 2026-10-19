#!/usr/bin/env python3
"""Every test file in ci/ must actually run in CI.

Tests nobody runs rot: one asserted behaviour that had been removed, another
was deleted while the workflow still called it. This guard fails when
  * a ci/test-*.py or ci/test-*.sh exists that the workflow never invokes, or
  * the workflow invokes a ci/ file that does not exist.

A test may be exempted only by adding it to EXEMPT below with a reason.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "build-iso.yml"
EXEMPT = {}  # {"ci/test-name.py": "why it cannot run in CI"}


def referenced(workflow_text):
    return set(re.findall(r"\bci/[A-Za-z0-9._/-]+\.(?:py|sh)\b", workflow_text))


def problems(workflow_text, existing_tests, exempt, existing_files):
    ran = referenced(workflow_text)
    out = [f"{t} exists but the workflow never runs it" for t in sorted(existing_tests)
           if t not in ran and t not in exempt]
    out += [f"workflow runs {r} but that file does not exist" for r in sorted(ran)
            if r not in existing_files]
    out += [f"{e} is exempt but no longer exists" for e in sorted(exempt) if e not in existing_files]
    return out


class Logic(unittest.TestCase):
    """The checker itself must be able to fail."""

    def test_unrun_test_is_reported(self):
        got = problems("python ci/test-a.py", {"ci/test-a.py", "ci/test-b.py"}, {},
                       {"ci/test-a.py", "ci/test-b.py"})
        self.assertEqual(got, ["ci/test-b.py exists but the workflow never runs it"])

    def test_missing_file_is_reported(self):
        got = problems("python ci/test-a.py\npython ci/test-gone.py", {"ci/test-a.py"}, {},
                       {"ci/test-a.py"})
        self.assertEqual(got, ["workflow runs ci/test-gone.py but that file does not exist"])

    def test_exemption_needs_a_reason_and_a_file(self):
        self.assertEqual(problems("", {"ci/test-a.py"}, {"ci/test-a.py": "needs hardware"},
                                  {"ci/test-a.py"}), [])
        self.assertEqual(problems("", set(), {"ci/test-old.py": "x"}, set()),
                         ["ci/test-old.py is exempt but no longer exists"])

    def test_clean_case(self):
        self.assertEqual(problems("a ci/test-a.py b", {"ci/test-a.py"}, {}, {"ci/test-a.py"}), [])


class RealRepo(unittest.TestCase):
    def test_workflow_and_tests_agree(self):
        tests = {p.relative_to(ROOT).as_posix() for p in (ROOT / "ci").glob("test-*.*")
                 if p.suffix in {".py", ".sh"}}
        files = {p.relative_to(ROOT).as_posix() for p in (ROOT / "ci").rglob("*") if p.is_file()}
        for reason in EXEMPT.values():
            self.assertTrue(reason.strip(), "every exemption needs a reason")
        self.assertEqual(problems(WORKFLOW.read_text(), tests, EXEMPT, files), [])


if __name__ == "__main__":
    sys.exit(unittest.main(verbosity=2).result.wasSuccessful() is False)
