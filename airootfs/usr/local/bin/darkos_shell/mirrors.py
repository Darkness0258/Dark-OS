"""Mirror ranking: pick fast, current HTTPS mirrors and install the list safely.

The old choose-mirror piped reflector straight into /etc/pacman.d/mirrorlist
with errors thrown away. A flaky network could leave pacman with one bad mirror
(or none) and no way back, and nothing in the system ever called it.

Here reflector writes to a temporary file, the result is validated (HTTPS only,
`$repo` and `$arch` present, at least three distinct mirrors, nothing but
Server lines and comments), the current list is backed up, and only then is
the new one swapped in with an atomic rename. Any failure leaves the existing
list exactly as it was.

No GTK, and nothing here accepts a file path from a caller: the CLI that runs
as root (darkos-mirrors.py) can only ever touch the two constants below, so it
cannot be turned into "overwrite any file as root".
"""
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

MIRRORLIST = "/etc/pacman.d/mirrorlist"
BACKUP = "/etc/pacman.d/mirrorlist.darkos-bak"
HEADER_PREFIX = "# Ranked by DarkOS on "
MIN_MIRRORS = 3
DEFAULT_NUMBER = 10
MAX_NUMBER = 30
RUN_TIMEOUT = 150          # seconds for one reflector run; it is killed after this

# Countries offered in Settings, as ISO codes: the only values ever passed to reflector.
COUNTRIES = (
    ("AU", "Australia"), ("AT", "Austria"), ("BD", "Bangladesh"), ("BY", "Belarus"), ("BE", "Belgium"),
    ("BR", "Brazil"), ("BG", "Bulgaria"), ("CA", "Canada"), ("CL", "Chile"), ("CN", "China"),
    ("CO", "Colombia"), ("HR", "Croatia"), ("CZ", "Czechia"), ("DK", "Denmark"), ("EC", "Ecuador"),
    ("EE", "Estonia"), ("FI", "Finland"), ("FR", "France"), ("DE", "Germany"), ("GR", "Greece"),
    ("HK", "Hong Kong"), ("HU", "Hungary"), ("IS", "Iceland"), ("IN", "India"), ("ID", "Indonesia"),
    ("IR", "Iran"), ("IE", "Ireland"), ("IL", "Israel"), ("IT", "Italy"), ("JP", "Japan"),
    ("KZ", "Kazakhstan"), ("KE", "Kenya"), ("LV", "Latvia"), ("LT", "Lithuania"), ("LU", "Luxembourg"),
    ("MX", "Mexico"), ("NL", "Netherlands"), ("NZ", "New Zealand"), ("NO", "Norway"), ("PK", "Pakistan"),
    ("PL", "Poland"), ("PT", "Portugal"), ("RO", "Romania"), ("RU", "Russia"), ("RS", "Serbia"),
    ("SG", "Singapore"), ("SK", "Slovakia"), ("SI", "Slovenia"), ("ZA", "South Africa"),
    ("KR", "South Korea"), ("ES", "Spain"), ("SE", "Sweden"), ("CH", "Switzerland"), ("TW", "Taiwan"),
    ("TH", "Thailand"), ("TR", "Turkey"), ("UA", "Ukraine"), ("GB", "United Kingdom"),
    ("US", "United States"), ("VN", "Vietnam"),
)
COUNTRY_CODES = tuple(code for code, _name in COUNTRIES)

SERVER_RE = re.compile(r"^Server\s*=\s*(https://[A-Za-z0-9.-]+(?::\d{1,5})?/\S*)\s*$")


class MirrorError(RuntimeError):
    """Something went wrong, and the existing mirror list was left untouched."""


@dataclass
class RankResult:
    mirrors: int
    fastest: str
    countries: tuple
    relaxed: bool        # True when the 24-hour freshness filter had to be dropped


@dataclass
class Status:
    exists: bool
    servers: int
    fastest: str
    ranked_at: object    # datetime or None
    has_backup: bool


def parse_servers(text):
    """Valid https mirror URLs, in order, without duplicates."""
    seen, out = set(), []
    for line in text.splitlines():
        match = SERVER_RE.match(line.strip())
        if match and "$repo" in match.group(1) and "$arch" in match.group(1) and match.group(1) not in seen:
            seen.add(match.group(1))
            out.append(match.group(1))
    return out


def validate_list(text, minimum=MIN_MIRRORS):
    """(ok, reason). Strict on purpose: this file decides where every package comes from."""
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = SERVER_RE.match(line)
        if not match:
            return False, f"line {number} is not a plain https Server entry"
        if "$repo" not in match.group(1) or "$arch" not in match.group(1):
            return False, f"line {number} is missing $repo or $arch"
    count = len(parse_servers(text))
    if count < minimum:
        return False, f"only {count} usable mirror{'s' if count != 1 else ''} (need at least {minimum})"
    return True, ""


def clean_countries(countries):
    """Upper-cased, validated against the table. Raises ValueError for anything else."""
    out = []
    for code in countries or ():
        code = str(code).strip().upper()
        if code not in COUNTRY_CODES:
            raise ValueError(f"unknown country code: {code!r}")
        if code not in out:
            out.append(code)
    return tuple(out)


def clean_number(number):
    if isinstance(number, bool) or not isinstance(number, int) or not (MIN_MIRRORS <= number <= MAX_NUMBER):
        raise ValueError(f"number of mirrors must be {MIN_MIRRORS} to {MAX_NUMBER}")
    return number


def build_reflector_argv(save_path, countries=(), number=DEFAULT_NUMBER, relaxed=False):
    countries = clean_countries(countries)
    number = clean_number(number)
    argv = ["reflector", "--protocol", "https", "--sort", "rate", "--latest", "40", "--number", str(number),
            "--connection-timeout", "5", "--download-timeout", "8", "--threads", "8", "--save", save_path]
    if countries:
        argv += ["--country", ",".join(countries)]
    if not relaxed:
        argv += ["--age", "24"]
    return argv


def default_run(argv, timeout=RUN_TIMEOUT):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise MirrorError("reflector is not installed.") from exc
    except subprocess.TimeoutExpired as exc:
        raise MirrorError("Ranking took too long and was stopped. Your mirror list was not changed.") from exc
    return done.returncode, done.stdout, done.stderr


def _last_line(text):
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _atomic_write(path, text, mode=0o644):
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".mirrors.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def host_of(url):
    return urlparse(url).hostname or ""


def rank(countries=(), number=DEFAULT_NUMBER, run=default_run, mirrorlist=MIRRORLIST, backup=BACKUP,
         now=None, euid=os.geteuid, require_root=True):
    """Run reflector into a temp file, validate, back up, swap in. Raises MirrorError on any failure."""
    if require_root and euid() != 0:
        raise MirrorError("Ranking mirrors needs administrator rights.")
    countries = clean_countries(countries)
    number = clean_number(number)
    directory = os.path.dirname(mirrorlist)
    os.makedirs(directory, exist_ok=True)
    reason = ""
    for relaxed in (False, True):
        fd, tmp = tempfile.mkstemp(prefix=".mirrorlist.", dir=directory)
        os.close(fd)
        try:
            code, _out, err = run(build_reflector_argv(tmp, countries, number, relaxed), RUN_TIMEOUT)
            if code != 0:
                raise MirrorError(f"reflector failed: {_last_line(err) or 'no details'}. "
                                  "Your mirror list was not changed.")
            with open(tmp, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            ok, reason = validate_list(text)
            if not ok:
                continue          # first pass can come up short; the relaxed pass drops the 24 h filter
            stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
            where = ", ".join(countries) if countries else "anywhere"
            final = f"{HEADER_PREFIX}{stamp} (countries: {where}; fastest {number} https mirrors)\n{text}"
            if os.path.exists(mirrorlist):
                with open(mirrorlist, "r", encoding="utf-8", errors="replace") as f:
                    _atomic_write(backup, f.read())       # if this fails, nothing has changed yet
            _atomic_write(mirrorlist, final)
            servers = parse_servers(final)
            return RankResult(len(servers), host_of(servers[0]), countries, relaxed)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    raise MirrorError(f"Could not find enough good mirrors: {reason}. Your mirror list was not changed.")


def restore(mirrorlist=MIRRORLIST, backup=BACKUP, require_root=True, euid=os.geteuid):
    """Put the list from before the last ranking back. Raises MirrorError if there is nothing sound to restore."""
    if require_root and euid() != 0:
        raise MirrorError("Restoring mirrors needs administrator rights.")
    try:
        with open(backup, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as exc:
        raise MirrorError("There is no earlier mirror list to restore.") from exc
    ok, reason = validate_list(text, minimum=1)
    if not ok:
        raise MirrorError(f"The saved mirror list is not usable ({reason}), so it was not restored.")
    _atomic_write(mirrorlist, text)
    return len(parse_servers(text))


def status(mirrorlist=MIRRORLIST, backup=BACKUP):
    try:
        with open(mirrorlist, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return Status(False, 0, "", None, os.path.exists(backup))
    servers = parse_servers(text)
    ranked_at = None
    first = text.splitlines()[0] if text else ""
    if first.startswith(HEADER_PREFIX):
        stamp = first[len(HEADER_PREFIX):].split(" ", 1)[0]
        try:
            ranked_at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            ranked_at = None
    return Status(True, len(servers), host_of(servers[0]) if servers else "", ranked_at, os.path.exists(backup))


def describe(info, now=None):
    """One line for Settings."""
    if not info.exists or info.servers == 0:
        return "No mirrors are enabled, so updates cannot download. Rank mirrors to fix that."
    plural = "mirror" if info.servers == 1 else "mirrors"
    if info.ranked_at is None:
        return f"Not ranked by DarkOS yet. {info.servers} {plural} enabled, first: {info.fastest}."
    days = ((now or datetime.now(timezone.utc)) - info.ranked_at).days
    when = "today" if days <= 0 else ("yesterday" if days == 1 else f"{days} days ago")
    note = "  It has been a while; ranking again is worthwhile." if days >= 30 else ""
    return f"Ranked {when}. {info.servers} {plural}, fastest: {info.fastest}.{note}"
