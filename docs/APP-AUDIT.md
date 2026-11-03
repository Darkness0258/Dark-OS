# App audit (branch `calm-dark`)

Same evidence convention as [STATUS.md](STATUS.md): **[C]** checked in the repo or a
sandbox, never on a booted DarkOS; **[R]** reported, not checked; **[U]** unverified;
**[J]** judgment. Everything below is **[C]** (an Ubuntu 24.04 sandbox with GTK3,
VTE, sway and the real tools under test — not Arch, not booted DarkOS) unless marked
otherwise. Four parts, as scoped in `CLAUDE.md`: `.desktop` files, imports/external
commands vs. `packages.x86_64`, every `darkos-*.py` started headless with stderr
read, and `pacman.conf`'s `[multilib]`/`[blackarch]` sections.

## 1. `.desktop` files (23, in `airootfs/usr/share/applications/`)

A script (`/tmp` during the audit, not shipped) parsed every file's `Exec=`,
`Icon=` and `Categories=` and checked each mechanically: `Exec=`'s first token
against the file actually existing and being executable in `airootfs/`;
`Icon=` against a shipped icon file first, then (below) the real Adwaita theme;
`Categories=` tokens against the Desktop Menu Specification's registered
category list, fetched live from
[specifications.freedesktop.org](https://specifications.freedesktop.org/menu/latest/category-registry.html)
rather than assumed from memory (it's since gained a 14th main category,
`HealthFitness`, that didn't exist when I last had reason to know this list).

**Exec= — all 23 resolve [C].** Every one is an absolute
`/usr/local/bin/darkos-*.py`, `/usr/local/bin/darkos-installer`, or
`/usr/local/bin/the-void.sh`, and the file exists in `airootfs/`. One nuance
worth a look since it's a different shape than the rest: the installer entry's
`Exec=` is `darkos-installer`, a small bash **wrapper**, not Calamares
directly — it already does its own `command -v calamares` check with a
friendly "Calamares is not installed." message before running it, so the
real "does `calamares` the package resolve" question is handled defensively
at runtime already, not something this static check needed to chase further.
(`calamares` is also one of only two `.desktop` files whose target is a
non-`.py` script, so it's outside the literal "for each darkos-*.py" scope of
part 2 below; mentioned here since it's the same file this part is already
looking at.)

All 23 files' `Exec=` targets are mode `644` in this git checkout, not `755`
— confirmed this is a checkout artifact, not a real gap: `git config
core.fileMode` is `false` for this repo, and `build-iso.sh`'s
`assert_runtime_scripts` function **[C, read directly, not just assumed]**
`chmod 0755`s every file in its `runtime_scripts` list — which these 23
targets are all members of — as the first thing a real build does (`repair`
mode, called on `'source profile'` before anything else), and re-verifies
`755` on the final squashfs output (`check` mode). Confirmed every flagged
target (`darkos-store.py`, `darkos-installer`, etc.) is actually listed in
that array, so the repair applies to all of them.

**Icon= — no `darkos-*` window-id used as an icon name anywhere [C].** The
specific failure `CLAUDE.md` called out (a WM_CLASS used as `Icon=`, which no
icon theme defines) does not occur in any of the 23 files, and I also checked
the runtime path, not just the static files: nothing in `darkos_shell/` looks
an icon up by WM_CLASS either (`surfaces.py`'s one WM_CLASS reference is for
matching a running-window dot on the dock, unrelated to icon resolution) —
dock icons come from each app's own `Icon=` the normal way.

That said, most `Icon=` values are legacy (non-symbolic) freedesktop names —
`preferences-system`, `system-file-manager`, `accessories-calculator`, and so
on, no `-symbolic` suffix. I checked all 21 distinct values (23 files, two
icons shared by two files each: notes/reader, tool-groups/the-void) against
this sandbox's real installed `adwaita-icon-theme` (46.0-1, the same package
`packages.x86_64` lists, via `Gtk.IconTheme.has_icon()`). **15 of the 21 need
`-symbolic` appended or a different name entirely to resolve** — current
Adwaita ships symbolic-only for most legacy names. Worth a second pair of
eyes because it means an icon-less or generic-fallback dock/menu entry for
most of the app list, not a crash:

| app | current `Icon=` | status |
|---|---|---|
| backup | `drive-harddisk-symbolic` | already symbolic, **OK** |
| calculator | `accessories-calculator` | needs `-symbolic` |
| calendar | `x-office-calendar` | needs `-symbolic` |
| clipboard | `edit-paste` | not checked individually (common GTK stock-alias name; low risk) |
| clock | `clock` | no symbolic form either — nearest real Adwaita name is `alarm-symbolic` |
| dashboard | `utilities-system-monitor` | needs `-symbolic` |
| devhub | `applications-development` | no symbolic form, and no other Adwaita equivalent |
| downloads | `folder-download` | bare name resolves, **OK** |
| emoji | `face-smile` | needs `-symbolic` |
| files | `system-file-manager` | needs `-symbolic` |
| gallery | `image-viewer` | not checked individually |
| gaming | `applications-games` | needs `-symbolic` |
| mail | `internet-mail` | no symbolic form either — nearest real Adwaita name is `mail-unread-symbolic` |
| mission (command center) | `view-grid-symbolic` | already symbolic, **OK** |
| network | `network-wireless` | needs `-symbolic` |
| notes / reader | `accessories-text-editor` | needs `-symbolic` |
| security | `security-high` | needs `-symbolic` |
| settings | `preferences-system` | needs `-symbolic` |
| store | `system-software-install` | needs `-symbolic` |
| tool-groups / the-void | `utilities-terminal` | needs `-symbolic` |
| installer | `calamares` | **[U]** — a separate package's own icon (the wrapper already falls back to a clean error message if `calamares` itself is missing, so this is display-only either way); not checkable without that package installed |

Recommended fix, if this is confirmed on a real Arch `adwaita-icon-theme`
**[R, needs a real Arch box to confirm, not done here]**: append `-symbolic`
to the 12 names confirmed above to need it (2 more, `edit-paste` and
`image-viewer`, weren't individually checked but are common enough GTK names
to be worth the same try), and pick a real name for `clock`
(`alarm-symbolic`) and `mail` (`mail-unread-symbolic`) instead of just
appending a suffix; `applications-development` has no Adwaita equivalent at
all, symbolic or not, and would need a different icon entirely; `calamares`
depends on that package's own icon, separately. I did not make this change —
rewriting Icon= across 20 unrelated files for a cosmetic gap is past what "do
the app audit" asked for; it's reported here as a finding, not applied.

**Categories= — all 23 use only registered tokens [C].** Checked against the
live-fetched Main and Additional category registries; every file has at least
one registered Main Category plus 0–2 Additional ones, no typos or made-up
tokens found.

## 2. Imports and external commands vs. `packages.x86_64` (30 `darkos-*.py`)

An AST-based script (also `/tmp`, not shipped) walked every top-level
`darkos-*.py`: every `import`/`from X import` not in Python 3.12's own stdlib
(`sys.stdlib_module_names`, so this is the real list for the interpreter doing
the checking, not a hand-typed guess), and the first argv element of every
`subprocess.run/Popen/call/check_call/check_output`, `os.system`, and
`shutil.which` call.

**Imports — clean [C].** `gi` → `python-gobject`, `cairo` → `python-cairo`,
`PIL` → `python-pillow`, `cryptography` → `python-cryptography`: all four
non-stdlib imports used anywhere in the 30 scripts map to a package
`packages.x86_64` actually lists. Nothing unmapped.

**External commands — clean [C], after chasing down what first looked like
10 gaps.** The raw AST scan flagged `proton`, `hyprctl`, `kdeconnect-app`,
`notify-send`, `lsblk`, `powerprofilesctl`, `makepkg`, `pacman-conf`,
`clamscan`, `pgrep`, `wl-copy` as not directly present as their own line in
`packages.x86_64`. Every one turned out to be provided by something that *is*
listed, or by the Arch `base` group itself (not usually spelled out as its own
line, since it's the floor every Arch install starts from) — checked, not
assumed:

- `proton` — not a separate package; bundled by Steam itself (`steam` **is**
  listed) and downloaded at runtime when a user opts into it.
- `hyprctl` — part of the `hyprland` package (listed).
- `kdeconnect-app` and `kdeconnect-cli` (the script actually uses both, for
  different things) — both are real binaries the `kdeconnect` package ships,
  confirmed against that package's file listing on three independent distros
  (Debian, Alpine, MSYS2) rather than assumed; `kdeconnect` is listed. The
  `kdeconnect-app` call is also already wrapped in `shutil.which()` with a
  friendly "install the kdeconnect package" message if it's ever missing —
  already defensive, nothing to fix.
- `notify-send` → `libnotify` (listed). `powerprofilesctl` →
  `power-profiles-daemon` (listed). `clamscan` → `clamav` (listed). `wl-copy`
  → `wl-clipboard` (listed).
- `lsblk`, `pgrep` → `util-linux` and `procps-ng`, both members of the Arch
  `base` group (`procps-ng`'s own `base` group membership confirmed against
  its PKGBUILD and the Arch bug tracker, not assumed) — `base` is
  `packages.x86_64`'s own first line.
- `makepkg`, `pacman-conf` → both ship inside the `pacman` package itself,
  which by definition is present on any Arch system (it's the package
  manager), same reasoning as `bash`/`sudo` not needing their own line.

## 3. Every `darkos-*.py` started on headless sway, stderr read

New, kept (not a one-off): `ci/headless/app_launch_check.sh`, wired into
`ci/headless/run-all.sh` as a fourth check (`launch`, alongside `dock`/`stall`/
`snip`) — same "not wired into CI, needs sway" status as the other three.
Starts each of the 30 scripts bare (no arguments), gives it 3 seconds, sends
SIGTERM then SIGKILL, and checks stderr for an unhandled Python traceback.
Several scripts are daemons (`darkos-netwatch.py`, `darkos-protect.py` —
expected to just sit there sampling) or CLI tools that require flags
(`darkos-window-fx.py`, `darkos-sandbox-launch.py` — expected to print a usage
error and exit 2 with no arguments); neither counts as a failure, only an
actual traceback does.

**First run found one [C], now fixed.** `darkos-integrity-check.py` crashed
outright — an unhandled `FileNotFoundError` from `subprocess.run(["aide", ...])`
when `aide` isn't on PATH. `aide` and `rkhunter` are both in
`packages.x86_64`, so this shouldn't happen on a normal install, but:

- the file's own `_notify()` function already wraps its subprocess call in
  `try/except (OSError, subprocess.TimeoutExpired)` a few lines above — the
  pattern was already established in this exact file, just not applied
  consistently;
- `run_aide()` raising means `run_rkhunter()` right after it in `main()`
  never runs either, so one missing/misbehaving tool silently cancels the
  other half of the integrity check too; and
- this is a security-monitoring script likely run from a timer with nobody
  watching the terminal, where "crashed before finishing" is the worst place
  for a tool like this to fail quietly.

Fixed by wrapping both `subprocess.run` calls the same way `_notify()` already
does, logging and returning instead of raising. Verified, not just edited:
recompiled, re-ran bare (now logs "aide --init could not run ... skipping AIDE
this pass" / same for rkhunter and reaches "integrity check finished", exit 0,
where it used to crash), reran `ci/test-integrity-check.py` (still 6/6,
unaffected — that suite already skipped on missing tools; production code now
matches what the tests already expected), then reran the full `launch` check
and the full `ci/headless/run-all.sh` (`dock`+`stall`+`snip`+`launch`) end to
end: 30/30 scripts, 0 tracebacks, all four checks pass.

No other script produced a traceback, and nothing in any script's stderr
beyond that one matched `critical|unhandled|fatal` (checked, not just
grepped for the one string).

## 4. `pacman.conf`

**Both present and actually configured, not just stub headers [C]:**
`[multilib]` has `Include = /etc/pacman.d/mirrorlist`; `[blackarch]` has
`SigLevel = Required DatabaseOptional` and a pinned
`Server = https://blackarch.org/blackarch/$repo/os/$arch` (with a comment
explaining why it's pinned rather than using BlackArch's own mirrorlist —
build determinism). `[chaotic-aur]` is also present and configured, which
`darkos-store-gated-aur-install.py` depends on.

## Not checkable here

Same ceiling as every other pass in this repo, restated for this one: real
Arch package names/versions actually resolving against live Arch/BlackArch/
Chaotic-AUR repos, the real `adwaita-icon-theme` on Arch (not Ubuntu) having
the same symbolic-only gaps found here, `/usr/bin/calamares` and its icon
existing once that package is installed, and anything about how these apps
actually look or behave once booted on real DarkOS. All **[U]**.
