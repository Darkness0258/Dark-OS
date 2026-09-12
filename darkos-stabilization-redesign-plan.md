## Stabilization & Redesign Pass (insert after Phase 8, before Phase 9)

Goal — close the gap that's making a code-complete build feel rough, and land
the visual refresh you've wanted since Aug 23, before Phase 9 (Cloud) adds
anything new on top of a shell that isn't settled yet.

**Why this is its own pass, not scattered bug tickets:** ui-registry.md's own
notes repeat the same caveat on almost every one of the 21 apps and every
shell surface — "target Hyprland/hardware acceptance still open." Nearly
everything so far has been verified under Xvfb/X11 or over SSH into VMware,
not the real Wayland/Hyprland compositor on real hardware. "Runs, but feels
rough" is exactly the symptom you'd expect the first time that gap gets
closed for real — this pass is what closes it.

### Step 1 — Real-environment audit (before touching any code)

**Static half — done, from this sandbox, not guessed:**
- `activity_detector` vs. Command Center: confirmed the mechanism. Every
  ~3s activity poll called `left.show_all()`/`right.show_all()` directly,
  with no check on whether Command Center (HUD) was even open — that's
  what made panels pop open on their own while switching apps. Fixed with
  a one-line guard (only adjust left/right when `hud.is_visible()`), and
  verified against the real method with mock windows across all 4
  open/closed × show/hide combinations — all 4 correct. Patch attached.
- GTK3 node-theming gap: rendered the real `css.py` against every stock
  widget type the app actually uses (not a guess — grepped every `Gtk.*(`
  call site first). `scale`, `levelbar`, and `progressbar` all had the same
  stock-light trough Calendar/Notebook/TextView already had fixed —
  screenshotted before/after each, confirmed fixed. `switch` and
  `progressbar`'s fill also defaulted to GTK's stock blue instead of your
  cyan accent token — same fix, now token-driven so it follows whatever
  Step 3 lands on rather than needing to be redone. `Notebook` and
  `TreeView` looked broken in isolation too, but checking real usage showed
  every real instance already applies the scoping class (`terminal-tabs` /
  `darkos-list`) that covers it — false alarm, not touched. Scrollbar
  chrome (forced out of overlay-hidden mode to actually check it) looked
  fine as-is. `ComboBoxText` renders fine. Two patches attached (applied to
  your repo already, per your terminal output) — nothing else in this
  static pass came up broken.

**Still needs your hardware — nothing here replaces it:**
Boot the actual build and go through every always-on surface plus the
Command Center with `ui-rules.md` open next to it, on the real Hyprland
compositor. Xvfb can confirm a widget's colors; it can't confirm layer-shell
positioning, blur, or motion feel — that's a real-hardware-only check. Note
anything that still diverges. Output folds into the same punch list above.

### Step 2 — Performance reality check
`ui-rules.md` targets 120 FPS, real-time blur, spring/elastic easing. Your
dev machine's GPU (GeForce 940MX, 2GB) is going to struggle with parts of
that spec no matter how clean the code is. Worth checking Hyprland's debug
FPS overlay before assuming something on the punch list is a code bug —
some of "rough" may be "correct code, wrong performance budget for this
GPU," which has a different fix: `ui-rules.md` already says to degrade
blur/particles first on lower-end GPUs, but nothing implements that
threshold yet. Worth building it as part of this pass either way, since
whatever ships has to run on real end-user hardware too, not just yours.

### Step 3 — Pick the redesign direction
Before touching `ui-tokens.md`, pick one, since it changes what Step 4 does:
- **Refine** — keep the black/cyan/glass/ring language, reduce how much
  competes for attention at once (this is the literal Aug 23 ask: "less
  cluttered/cleaner").
- **Reset** — a more fundamental palette/shape change.

Given how deliberate `ui-tokens.md` already is and that the only complaint
on record is "cluttered," Refine looks like the fit — but that's a real
call, not one to make on your behalf.

### Step 4 — Implement against the punch list + chosen direction
Token/CSS changes land in `ui-tokens.md`/`ui-rules.md` first — CLAUDE.md's
own rule is that tokens are the source of truth and `darkos-shell.py` stays
in sync with them, not the other way around. Then component code. Then run
`imprint` against `ui-registry.md` for each touched component, same as
always.

### Step 5 — Re-verify for real
Every "target acceptance still open" line in `ui-registry.md` gets an
actual Hyprland/hardware pass this time, not Xvfb. This is the step every
session so far has deferred — closing it is what actually earns "stable,"
not another round of source-level fixes.

---

**Files this touches:** `ui-tokens.md`, `ui-rules.md`, `ui-registry.md`,
`darkos_shell/*.py` (mainly `surfaces.py`, `css.py`, `tokens.py`),
`build-plan.md` (add this section), `progress-tracker.md` (new dated
entries as it progresses).

**Doesn't touch:** `architecture.md` — nothing here crosses a documented
boundary or changes the stack.

---

## Kickoff prompt (for Claude Code / Codex)

```
Read project-overview.md, architecture.md, build-plan.md, ui-tokens.md,
ui-rules.md, and ui-registry.md first.

Do Step 1 of the "Stabilization & Redesign Pass" section in build-plan.md:
boot the current build, walk every always-on shell surface and the Command
Center against ui-rules.md, and produce a concrete, named punch list of
where it diverges (motion, unwanted panel show/hide, incorrectly-themed
widgets, anything else). Don't fix anything yet.

Then do Step 2: check actual frame timing against the 120 FPS target on
this hardware (GeForce 940MX, 2GB) and note where it falls short.

Stop after the punch list and performance notes. Don't touch ui-tokens.md,
any darkos_shell code, or start Step 3's direction choice until Hamza
signs off on what you found — same rule this project has followed every
session so far.
```
