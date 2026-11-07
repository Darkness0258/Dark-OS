#!/usr/bin/env python3
"""darkos-mirrors: show, rank or restore the pacman mirror list.

    darkos-mirrors.py status [--json]
    darkos-mirrors.py rank [--country DE,FR] [--number 10] [--json]     (root)
    darkos-mirrors.py restore [--json]                                  (root)

Settings runs rank/restore through pkexec, so this process is root while its
arguments come from an unprivileged user. That is why it takes NO file paths:
it can only ever touch /etc/pacman.d/mirrorlist and its one backup, and
countries are checked against a fixed table before reflector sees them. All
the logic and its safety checks are in darkos_shell/mirrors.py.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from darkos_shell import mirrors  # noqa: E402


def build_parser():
    parser = argparse.ArgumentParser(prog="darkos-mirrors", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="show what is in use")
    status.add_argument("--json", action="store_true")
    rank = sub.add_parser("rank", help="rank fast https mirrors and install the list (root)")
    rank.add_argument("--country", default="", help="comma-separated ISO codes, e.g. DE,FR (default: anywhere)")
    rank.add_argument("--number", type=int, default=mirrors.DEFAULT_NUMBER,
                      help=f"how many mirrors to keep ({mirrors.MIN_MIRRORS} to {mirrors.MAX_NUMBER})")
    rank.add_argument("--json", action="store_true")
    restore = sub.add_parser("restore", help="put back the list from before the last ranking (root)")
    restore.add_argument("--json", action="store_true")
    return parser


def _emit(args, ok, message, out, err, **extra):
    if args.json:
        print(json.dumps({"ok": ok, "message": message, **extra}), file=out)
    else:
        print(message, file=out if ok else err)
    return 0 if ok else 1


def main(argv=None, out=None, err=None, **overrides):
    """`overrides` (run, mirrorlist, backup, euid, require_root, now) exist for tests; argv cannot set them."""
    out = out or sys.stdout
    err = err or sys.stderr
    args = build_parser().parse_args(argv)
    paths = {k: overrides[k] for k in ("mirrorlist", "backup") if k in overrides}
    try:
        if args.command == "status":
            info = mirrors.status(**paths)
            return _emit(args, True, mirrors.describe(info, overrides.get("now")), out, err,
                         servers=info.servers, fastest=info.fastest, has_backup=info.has_backup,
                         ranked_at=info.ranked_at.isoformat() if info.ranked_at else None)
        if args.command == "rank":
            try:
                countries = mirrors.clean_countries([c for c in args.country.split(",") if c.strip()])
                number = mirrors.clean_number(args.number)
            except ValueError as exc:
                _emit(args, False, str(exc), out, err)
                return 2   # a usage error, distinct from a failed run (1)
            kwargs = dict(paths)
            kwargs.update({k: overrides[k] for k in ("run", "euid", "require_root", "now") if k in overrides})
            result = mirrors.rank(countries, number, **kwargs)
            return _emit(args, True, f"Ranked {result.mirrors} mirrors; fastest: {result.fastest}.", out, err,
                         mirrors=result.mirrors, fastest=result.fastest, countries=list(result.countries),
                         relaxed=result.relaxed)
        if args.command == "restore":
            kwargs = dict(paths)
            kwargs.update({k: overrides[k] for k in ("euid", "require_root") if k in overrides})
            count = mirrors.restore(**kwargs)
            return _emit(args, True, f"Restored the earlier mirror list ({count} mirrors).", out, err, mirrors=count)
    except mirrors.MirrorError as exc:
        return _emit(args, False, str(exc), out, err)
    except OSError as exc:
        return _emit(args, False, f"Could not write the mirror list: {exc}", out, err)
    return 2


if __name__ == "__main__":
    sys.exit(main())
