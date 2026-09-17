# Progress Tracker

## Current status (2026-09-16)

Phases 1–8 are code-complete; see `build-plan.md` for the authoritative
per-item checklist (this file tracks the narrative and lessons, not
feature-by-feature status). Phase 9 (Cloud) is a scaffold only.

**Genuinely open right now:**
- **Real Hyprland/Wayland + hardware pass** — almost everything below was
  verified under Xvfb/X11, VMware+SSH, or by reading source against
  upstream docs, not the real compositor on real hardware (see "Standing
  ceiling" below). `ci/hardware-audit.sh` is ready to run.
- **Network-transparency dashboard** — blocked on Hamza sharing PHANTOM's
  source; reusing its actual monitoring core needs the real code, not a
  reimplementation from a guess at what "reuse" means.
- **Phase 9 Cloud** — `darkos_cloud.py` scaffold exists (license/tier
  check + cloud-AI-call stub, both degrade safely unconfigured). Needs a
  real Supabase project URL/anon key and Hamza's call on the data-
  retention window (`PRIVACY-DRAFT.md` has the disclosure text drafted,
  two `[TODO]`s waiting on that decision).
- **Flatpak Shield scan** — shipped deliberately without one (pacman/AUR
  both scan before install; Flatpak's OSTree layout wasn't verifiable
  from this sandbox). Named gap, not started.
- **Connect** (real KDE Connect protocol) — needs its own dedicated
  session, not a rushed add-on to something else.
- **Command Center visual refine** (2026-09-16) — border/header-weight
  softening applied to `css.py`, not yet seen on real hardware.

## Standing verification ceiling

No Arch box, real GPU, or Wayland/Hyprland compositor has been available
in any session logged here. "Verified" below almost always means one of:
Xvfb/X11 (catches real logic/rendering bugs, not compositor-specific
behavior), VMware Workstation + SSH (real boot, real processes, no
physical GPU), or direct source-against-upstream-docs review. Treat every
"code complete" or "verified" entry as "as far as this sandbox allows"
unless it explicitly says Hamza confirmed it live. Sessions stopped
re-stating this after almost every entry; it's stated once here instead.

## Lessons worth remembering

1. **`Gtk.Label.set_line_wrap_mode()` wants `Pango.WrapMode`, not
   `Gtk.WrapMode`** — `Gtk.TextView.set_wrap_mode()` genuinely does want
   `Gtk.WrapMode`, so it's an easy mix-up. Got it wrong once in
   `surfaces.py:make_label()` and it crashed `do_activate()` on the first
   wrapped label built — took down all 5 overlay windows, not just one.
   `py_compile` can't catch it (it's a name-resolution error); only
   actually importing/running the module does.
2. **A new top-level script needs registering in three separate,
   independently-maintained lists**, not one: `build-iso.sh`'s
   `runtime_scripts`/`python_scripts`/`cmp_scripts`, `profiledef.sh`'s
   `file_permissions`, and `ci/verify-iso.sh`'s `payload`/`scripts`
   arrays. Missing one doesn't fail loudly until that specific stage of
   CI runs — bit this project twice, on two different scripts.
3. **`profiledef.sh`'s `file_permissions` runs *before* `pacstrap`** (per
   archiso's real `mkarchiso` source) — it can only ever fix files that
   ship in this repo's own `airootfs/` tree. It structurally cannot fix
   an executable bit on a file a *package* installs (e.g. waydroid's
   binary) — that needs a pacman hook instead.
4. **`ci/verify-iso.sh`'s executable check didn't handle symlinks** —
   `/usr/bin/waydroid` is genuinely a symlink upstream (confirmed against
   waydroid's real install Makefile), and the checker's `unsquashfs`
   extraction never pulled in the link's target, so it always looked
   like a dangling/non-executable file. Two sessions were spent chasing a
   "real" permissions bug before empirical testing (a real pacman install
   in a scratch root) found the actual cause: a false positive in the
   verifier itself. Fixed by branching on `-L` — symlinks now just need a
   real target, regular files still need a real `-x` bit.
5. **`configparser` silently lowercases option keys** (`Type`→`type`) and
   its `write()` reformats `Key=Value` into `Key = Value`, which doesn't
   match this repo's actual `.desktop` file convention. Caught before
   shipping; replaced with a surgical single-line text edit instead of a
   full parse/rewrite cycle for that one Settings toggle.
6. **GTK3's "complex" native-themed widgets don't inherit
   `background-color`** from an ancestor class — `GtkCalendar`,
   `GtkNotebook`'s stack area, and `GtkTextView`'s text area all need
   their own CSS node targeted directly. Full writeup and the fix pattern
   are in `ui-registry.md`; hit this three separate times before it was
   named as a pattern.

## Session log (condensed)

### 2026-08-13 – 08-16 — Phase 2 review and first VM verification
Seven fixes applied to shell chrome (Plymouth HOOKS assertion hardened,
media-refresh timeout stacking, quick-toggle wiring confirmed, BlackArch
picker terminal launch fixed for VMs without hardware GL, Now Playing
card ordering). The full erase-disk-install → reboot cycle ran in a real
VM on 08-16: login, password hash, and the first-boot tools dialog all
confirmed working. Plymouth's installed-system rendering stayed open —
a display/KMS-only question, can't be answered from source.

### 2026-08-17 — Scope expansion agreed
Antivirus/security, Android app compat (Waydroid), and 4 concrete Motion
additions designed and written into architecture.md/build-plan.md/
ui-rules.md. Client/server ("DarkOS Cloud") clarified: tiered services +
account/opt-in data, not remote control — this boundary has held since.
"Professional look," macOS app support, and "all devices" logged as
open questions needing Hamza's input, not designed further yet.

### 2026-08-18 — Phase 3 refactor, Plymouth confirmed unverified, lag fixed
`darkos-shell.py` (1,549 lines) split into the `darkos_shell/` package.
Hamza confirmed the boot-animation claim in README/CLAUDE.md had been
premature — genuinely unverified, not actually checked. Three lag causes
found and fixed by reading the Phase 2 code directly: one `cr.stroke()`
call per waveform bar instead of one path total, the orb redrawing at
full rate even while idle/sleeping, and up to 4 sequential blocking
`playerctl` subprocess calls on the GTK main thread (moved to a
background thread) — the last of which also surfaced a real bug where a
`None` return was silently killing the position-poll timer.

### 2026-08-20 — Phase 3 wired, 4 bugs found in code review, then 4 more found in a real VM boot
All Phase 3 modules connected: `actions.py` (ActionDispatcher +
snapshot-before-act), `ai_brain.py` (chat + `[ACTION]` dispatch),
`assistant_trigger.py`, activity-aware `__init__.py`/`surfaces.py`
wiring. Code review then found and fixed 3 real bugs (AT-SPI subprocess
args broken by a stray `"--"`, comma-splitting in argument parsing,
malformed snapshot destination path) — none of which `py_compile` could
catch. A full ISO build + live VMware boot the same day found 4 more,
all crash-level (`apply_css` never implemented despite being imported,
a Cairo helper imported from the wrong module, a GTK LayerShell call
missing its window argument, an undefined `cairo` name) plus a Hyprland
0.55+ IPC compatibility fix. After all of that: live-VM-verified
snapshot creation, D-Bus/hyprctl control (real volume + workspace
changes), and AT-SPI control, all confirmed via `hyprctl layers` output
and a real test suite run inside the guest.

### 2026-08-21 — Independent review confirms Aug 20, finds 2 more
Re-checked the "final 4 gaps" against actual source rather than a
report — all confirmed genuinely fixed and wired. Two new bugs caught
independently: a `.dock-highlight` CSS class that was toggled but never
defined (detection worked, nothing visible happened), and `explain()`'s
extracted text being concatenated raw onto the reply instead of
actually being explained by the LLM.

### 2026-08-23 — Command Center split out; the HUD had never actually rendered
Implementing a Zorin/CachyOS-inspired "don't show everything at once"
layout surfaced a real gap: `DarkOSHUDOverlay` was imported but never
instantiated — the Aug 16 "VM-verified" HUD checkbox had only covered
the chrome around it. Fixed: HUD/left/right now start hidden, a new
`--toggle-command-center` (bound `SUPER+H`) opens all three together
using the HUD's own `is_visible()` as the single source of truth.
Noted, not fixed: `activity_detector` can still independently show/hide
left/right regardless of Command Center state — the two systems weren't
reconciled yet (fixed 2026-09-11, see below).

### 2026-08-24 — Phase 3 fully runtime-verified via SSH; Hamza confirms 4 items live
Network fix (`dhcpcd` + an `ensure-network` script) unblocked SSH into
the VM. From there: 5-minute stability check clean, real volume/
workspace control via D-Bus, a real AI chat round-trip, `explain()`
against a real window title, and the voice pipeline's STT leg executing
without crashing. Hamza then confirmed live, in person: TTS audio
audible, dock highlight glow visible, Plymouth boot splash renders, and
full AI chat with real API keys works end to end.

### 2026-08-27 – 08-28 — Phase 4: all 11 native apps built
File Explorer, Terminal, Notes, Calendar, Clock, Calculator, Reader,
Clipboard, Emoji Picker, Gallery, Downloads — all built, all
Xvfb-verified with real data (not fixtures): real directory trees, a
real generated PDF, real clipboard writes, a real `.zip`'s actual
contents. Found the shell-crashing `CAIRO_DANGER` import bug and the
GTK3 background-color gotcha (Lesson 6) during this stretch. Two scope
calls worth remembering: clipboard history is session-only by design (a
persistent plaintext copy-log is a real privacy risk on a security OS),
and Downloads is a folder view, not a live progress tracker, since
nothing in DarkOS exposes download-progress events to hook into.

### 2026-08-29 – 08-31 — Phase 5 (Settings, Network, Security, Backup, Dashboard, Mission) + Phase 6 start
`user_settings.py` shipped as a real shared settings store — confirmed
by direct test that a saved value actually changes `tokens.py`'s live
constants, not just a write-only file. Two `configparser` gotchas caught
in Settings' Startup tab (Lesson 5). Security Center's Vault/Encrypt use
real PBKDF2+Fernet, verified against both correct- and wrong-password
paths, and that a failed decrypt leaves no corrupted file behind.
Backup/Dashboard fully verified (byte-identical restore, a real
CPU-load test moving the live reading 0%→100%). Mission/Spaces
initially mis-bucketed as "unverifiable like Shield" — corrected same
session and built, since it's really just hyprctl JSON parsing. DevHub
built and partly verified against real `git`/PyPI data. **Deliberately
not attempted, each with a stated reason:** Connect (own session
needed), Shield (needs real kernel access + daemons, can't verify from
a sandbox), network-transparency dashboard (blocked on PHANTOM's
source).

### 2026-08-31 — Store hits a real wall
Every Store backend — pacman, AUR, Flatpak, Wine/Proton, Waydroid — is
genuinely unreachable from this sandbox (confirmed, not assumed: a real
`Forbidden` from the AUR RPC, the rest simply not installed). Built
correctly against each tool's real documented CLI/API regardless.
Installs gated behind Shield per architecture.md — since Shield didn't
exist yet at this point, every Install button was disabled outright
rather than installing ungated.

### 2026-09-06 — Six sessions: audit confirmed, Store gates built, a real shell crash found, Phase 8 started
Independently re-ran the full through-Phase-7 audit in a fresh Ubuntu
sandbox rather than trust its own claims — confirmed correct (94/94
tests, two harmless doc inaccuracies found and noted). Then, in order:
the pacman Shield-gate (resolve → download-without-installing → scan →
install, 22 tests), the AUR gate (same shape, weaker by design — a
malicious PKGBUILD already runs before there's a file to scan, stated
directly to the user rather than glossed over — 28 tests, plus a real
bug fixed where the AUR package name was only ever kept fused into a
display string), and Flatpak (`--user` install, deliberately *without* a
Shield scan — OSTree's fetch-then-checkout mechanics weren't verifiable
here, named as a real gap rather than faked). A real GitHub Actions
failure led to finding the 3-list script-registration gotcha (Lesson 2).
A full audit pass then found the `Gtk.WrapMode`/`Pango.WrapMode`
shell-crashing bug (Lesson 1) — the first time `darkos-shell.py` itself,
not just the 21 standalone apps, had actually been run under Xvfb.
Session closed with Phase 8's onboarding flow (performance-profile
picker folded into the existing first-boot tool wizard), tested through
6 real scenarios.

### 2026-09-08 – 09-10 — CI reaches a real ISO build, then a verifier false positive
CI got past every earlier blocker for the first time — a real 3.7GB ISO
built, 106/106 permission checks passed — and failed on
`/usr/bin/waydroid` not being executable. A first fix (a pacman hook to
chmod it post-install) didn't resolve it. Root cause, found empirically
rather than guessed a third time: `/usr/bin/waydroid` is a symlink, and
the checker was never extracting its target (Lesson 3 + Lesson 4).
Fixed at the actual source — the checker itself — which generalizes to
every other symlinked package in that same list, not just waydroid.

### 2026-09-11 — Stabilization pass: Shield closed, redesign direction confirmed
*(Reconstructed from `darkos-status-handoff.md` — this session's own
tracker entry, if a fuller one exists elsewhere, hasn't been reconciled
against this yet.)* The `activity_detector`-vs-Command-Center conflict
noted 2026-08-23 was fixed (guarded on `hud.is_visible()`). A recurring
GTK3 stock-chrome gap (white/light chrome despite the dark theme) fixed
across `scale`, `levelbar`, `progressbar`, `switch`, `Gtk.ListBox`/
`row`. **Shield's full arc closed**: quarantine (move/restore/delete,
one-click restore), continuous protection (watches Downloads/Desktop/
removable media via inotify — fanotify doesn't deliver events in this
sandbox), a Quarantine review tab, an on/off toggle, daily rkhunter+AIDE
baselines (rkhunter's exit code is always 0 regardless of findings —
parse `--rwo` output text instead). 47 tests passing. Redesign
direction confirmed as **Refine** (soften what's competing for
attention, not a palette/shape reset) — the Aug 23 ask was "less
cluttered/cleaner."

### 2026-09-16 — Command Center CSS refine
Implemented the Refine plan from 09-11: `.glass-panel` border alpha
0.12→0.06, `.section-title` weight 700→600 (both in `css.py`), same
colors/content. Approved by Hamza; not yet visually verified — no
Hyprland/GTK available in the sandbox that made the edit.

---
*Condensed 2026-09-16 from an ~85KB/581-line log spanning 2026-08-13
through 2026-09-10, with 09-11 folded in from `darkos-status-handoff.md`.
Correction to an earlier version of this note: this file is genuinely
git-tracked (`git log -- progress-tracker.md` shows real commits) — it
is NOT gitignored. The full original (exact commit hashes, full
verification transcripts, every bug's full repro) is recoverable with
`git checkout <commit> -- progress-tracker.md` even after this file is
overwritten, as long as the repo's `.git` history stays intact. This
trades that granularity for something actually readable in one sitting,
not for something irrecoverable.*
