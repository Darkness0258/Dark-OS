# DarkOS Update Plan v2: Unified Features, Opt-in Store, Real Design

Drafted 2026-10-17. Replaces v1. Status section 9 and the wallpaper decision in section 8 were updated 2026-10-18 after the code pass. Companion files: `darkos-reference-projects.md` (GitHub research) and `darkos-stitch-prompts.md`.

## 0. What changed from v1

1. **Store model corrected.** Useful core apps ship preinstalled. Everything else, including Windows-style bloat, lives in the Store and is opt-in (section 4).
2. **GitHub research added.** I had skipped it. Results are in `darkos-reference-projects.md`.
3. **Design direction replaced** (section 3). v1's "black + neon cyan + glow + glass" is the generic AI-generated look you described.
4. **New verified risk:** Hyprland 0.55+ moved to Lua config and dropped-soon legacy config (section 5).

## 1. Honest limits

1. **I have not seen your current build.** My design diagnosis comes from your docs (custom Cairo drawing, glow strokes, cyan on black) and from how the best shells solve it. Send 3 screenshots (desktop, Command Center, Store) and I will critique the real thing.
2. **"All functions of every OS" can't be copied one-to-one.** Plan: one Store, one Search, one Settings, three app lanes (native, Windows, Android). macOS apps cannot run, so macOS contributes features and look only.
3. **Stitch makes static screens**, not animations or GTK code. Use its output as reference plus a `DESIGN.md`.
4. **Lag is a mistake you are fixing.** Design and Store work can proceed in parallel. Nothing new ships until the lag test in section 7 passes on your laptop, not only the VM.
5. **Android lane stays the riskiest.** Waydroid is unverified on your stack.

## 2. The model: one front door, three lanes

**Front door (one of each):** Store, Search, Settings.

| Lane | Engine | Store badge | Risk |
|---|---|---|---|
| Native Linux | pacman + Flatpak (v1); AppImage (v2); AUR gated and labelled "Community" | Native / Flatpak / Community | Low |
| Windows | Bottles (Wine/Proton), Steam for games | Windows | Medium |
| Android | Waydroid + Waydroid Helper | Android | High |
| macOS | none | none | Features and look only |

## 3. Design direction v2 ("Calm Dark, HUD as an accent")

**Why the current look reads as AI-generated** (my judgment, not a measurement): neon accent glowing everywhere, pure black with transparent panels, mixed icons, and many equal-weight effects. The best shells in the research do the opposite: they use a token system, one icon family, one type scale and a restrained palette.

**Rules** (each becomes a check in the test manual):

1. **Palette comes from one accent, generated, not hand-picked.** Use a Material-style tonal palette generator (DankMaterialShell uses `matugen`; end-4's shell depends on the `materialyoucolor` Python library). Feed it your accent colour, write the output into `tokens.py`. You get surface, container, outline and text colours with sane contrast.
2. **Accent covers a small part of any screen** (my rule of thumb: about 10%). Neutrals do the work.
3. **Surfaces, not glow.** Three levels (base, raised, overlay) with 1px low-contrast borders. Shadows only on floating things. Glow only for focus and the active item.
4. **Glass is optional and rare.** Floating overlays only (dock, launcher). Panels are solid. Caelestia's own example config ships with transparency off. Your Glass slider (Clear / Frosted / Solid) stays; Solid is the default on weak hardware.
5. **One icon family.** App icons: Papirus (GPL-3.0, in Arch `extra`, has Dark and Light variants). UI glyphs: Material Symbols as a font (Caelestia does this), so icons tint with CSS colour and stay crisp at any size. No emoji, no mixed sets. Windows apps need a fallback icon because Papirus does not theme them.
6. **Two font families, one scale.** Suggested: Inter for text and JetBrains Mono for code. Use Space Grotesk only for large headings or drop it. Define sizes once (for example 12 / 14 / 16 / 20 / 28) and use only those.
7. **No raw numbers in components.** Colours, radii, spacing, durations all come from tokens. Copy Caelestia's idea: a separate tokens file with scale multipliers.
8. **Motion lives in the compositor.** Hyprland supports bezier and spring curves, window styles (slide, popin, gnomed), layer styles (slide, popin, fade) and workspace styles. Your dock and panels are layer-shell surfaces, so try animating the Command Center with a *layer* animation instead of Python redraws (works only if the shell maps and unmaps the surface; **untested**). Hyprland 0.55 also added a native glow window decoration: try it for the active window instead of Cairo glow. Never use the `loop` style: it forces a new frame every refresh.
9. **HUD identity only in two places:** the Command Center centre mark and the lock screen. Everywhere else stays quiet.
10. **Design from references, not vibes.** For each screen collect 3 to 5 screenshots from the shells in the research, note what you borrow, and give Stitch those screenshots as image input along with the prompt.

## 4. Store spec v2 (corrected)

**Rule:** the **useful core** is preinstalled (what a daily user needs and what Windows also ships). **Everything else is in the Store**, including Windows-style bloat, and nothing installs unless the user chooses it.

**Proposed split** (my guess from app *names only*; I have not read these apps; your call):
- **Core, preinstalled:** Files, Terminal, Settings, Store, Calculator, Notes, Clock, Calendar, Gallery, Reader, Clipboard, Downloads, Network Center, Security Center, Backup, Emoji picker, plus a browser, media player and text editor if they are not already in the image.
- **Store-only:** Gaming hub, Mail, DevHub, Mission, Dashboard, and everything below.

**What "bloat" means here:** the junk Windows ships preinstalled and promotes: casual games, social and streaming clients, news and weather widgets, trials, extra browsers and office suites. In DarkOS these are catalogue entries, never promoted, never autostarting.

**Store design**
- **Catalogue:** the whole Flathub catalogue plus pacman packages, with the DarkOS "curated" tab holding your packs and extras. Bazaar's design is the model (curated tab configured by YAML, UI decoupled from backend work, queued downloads, permissions shown).
- **Every app card:** source badge, download and installed size, permissions (network, home folder, devices), "starts at login" yes/no, Install or Remove.
- **No nags:** no ads, no "recommended for you" banners, no first-run install prompts that cannot be skipped.
- **Remove** asks "keep or delete app data?".
- **Starter packs are rule-based:** Everyday, Student, Developer, Creator, Gamer, Office. First-run "Pick your extras" is skippable and starts with everything unticked.
- **AI seam:** one function, `recommend(profile) -> ranked list`. Today it returns the static packs. Later the AI flag swaps its body. No AI code in the build now.
- **Known gap:** pacman/AUR installs are Shield-gated; Flatpak installs skip the scan. Decide: scan after install, or label "unscanned".

## 5. Verified risk: Hyprland 0.55+

- Hyprland 0.55 (May 2026) introduced Lua config; legacy `hyprland.conf` is deprecated and, per Debian's notes, to be dropped 1 to 2 releases later.
- Your Oct 2 boot fell back to `hyprland.conf` because no Lua config existed. That works now and will stop working.
- 0.55 also changed several dispatchers. Your `darkos-window-fx.py` uses `hyprctl dispatch`, so test every call on the exact Hyprland version in your ISO.
- hyprshell (if you adopt it) needs 0.55 or newer.
- **Action:** record `hyprctl version` in every test log, and check whether you can pin the Hyprland version for ISO builds (for example with an Arch Linux Archive date snapshot in the build's pacman config; **feasibility unverified**).

## 6. Phases

**A. Prove it works** (blocking for shipping, not for design)
- Boot, lag fix confirmed on laptop and VM, close buttons, the five fixed apps, sandbox re-enabled per app.
- Effects level (Off / Balanced / Full) and Glass slider settings exist before any new effect.
- Hyprland version recorded and `hyprctl dispatch` calls tested.

**B. Shell spike (3 days, decision gate)**
- Build the *same two screens* (dock + Command Center) in each option, then measure idle CPU, memory and open/close smoothness on the laptop and VM.
  1. Keep GTK3 (cheapest; the CPU-drawn path stays).
  2. GTK4 + gtk4-layer-shell (GPU renderer; keeps Python and GTK knowledge; hyprshell proves the stack).
  3. Quickshell/QML (what the top shells use; biggest rewrite).
  4. Adopt DankMaterialShell as the base (MIT, in Arch `extra`; fastest to polished, but you re-skin someone else's design and write apps on top).
- Decide on numbers, not taste.

**C. Store v1**: native lane, curated YAML packs, source badges, permissions, Remove with data prompt, Updates tab.

**D. Search and switching**: evaluate shipping hyprshell (Alt+Tab, overview) and Vicinae (palette) against your own; check license and lag first.

**E. Windows lane**: Bottles, version pinned and tested.

**F. Android lane**: phone link (KDE Connect) first; then Waydroid with Waydroid Helper, hardware-gated. Use Dextop's idea: probe capabilities at runtime and show "Not available on this device" with the reason.

**G. Design pass**: tokens, generated palette, icon family, type scale, compositor animations, Glass slider.

**H. Parity gaps and later**: drag-to-edge snap, widgets, picture-in-picture, annotation, multi-monitor test; then AI back on, Cloud tier, distrobox lane.

## 7. Testing manual (run at the end of every work pass)

Run on **both** the VMware VM and the laptop. Log the commit hash and `hyprctl version`.

1. **Build:** CI builds the ISO and `ci/verify-iso.sh` passes.
2. **Fresh boot:** reaches the desktop with no keyboard help; note time to desktop.
3. **Idle (Command Center closed, 60 s):** CPU % and frame time with Effects Off, Balanced, Full.
4. **Command Center (`SUPER+H`):** open, record CPU %, close, confirm CPU returns to idle. If not, a loop is leaking.
5. **All apps:** each opens; titlebar minimize, maximize, close work.
6. **Window tools:** Alt+Tab, snap (`SUPER+CTRL+Left/Right`), overview, search. Run every `hyprctl dispatch` the tools use.
7. **Store:** fresh image has no optional apps; install one Flatpak app, launch it, remove it and answer the data prompt; the Installed tab lists it while installed.
8. **Glass slider and Effects level:** change each; note live or after restart; persists after reboot.
9. **Design check:** save 3 screenshots (desktop, Command Center, Store). For each, tick: tokens only, one icon family, accent under ~10%, text readable on every panel, no always-on glow.
10. **Windows lane (once built):** install one small `.exe`, run, remove.
11. **Android lane (once built):** real hardware only; confirm "Not available" on the VM.

| Test | VM | Laptop | Notes |
|---|---|---|---|
| 1 Build | | | |
| 2 Fresh boot | | | |
| 3 Idle CPU / frame time | | | |
| 4 Command Center | | | |
| 5 Apps | | | |
| 6 Window tools | | | |
| 7 Store | | | |
| 8 Glass / Effects | | | |
| 9 Design check | | | |

## 8. Decisions needed from you

1. **Core vs Store split:** confirm or fix the proposed list in section 4.
2. **Wallpaper:** ~~removed~~ **resolved 2026-10-18:** wallpapers are back. Nine images ship, default is Midnight Silk, and Settings > Wallpaper switches between them or takes your own image. No plain-background assumption remains.
3. **Shell direction:** which option from the section 6 spike do you want to test first?
4. **License:** what license will DarkOS code use? It decides whether you can copy any code from GPL projects.
5. **Flatpak scan gap:** scan after install, or label "unscanned".

## 9. Status after the 2026-10-17/18 code pass

Everything below is in the repo and passes the automated tests (18 test files, 32 of them in `ci/test-polish.py`). **None of it has been built into an ISO or booted yet**, so "done" means "written and tested in a headless sandbox", not "works on your laptop".

**Phase A (prove it works)**
- *Lag:* the AI assistant, HUD and activity detector are removed. This is the suspected main cause, but it is **untested**. Also changed: the dock no longer runs `hyprctl` on the UI thread, hidden panels do not poll, autostart is staggered, the live squashfs is zstd, background services run at idle priority. Needs test 3 and 4 of section 7 on the laptop and the VM.
- *Effects level:* Settings > Performance has Automatic / Lite / Full plus a renderer choice (Automatic / Software / GPU). The plan asks for Off / Balanced / Full: Lite is about Off, **Balanced does not exist yet**. The **Glass slider is not built**.
- *Hyprland version:* the testing manual now logs `hyprctl version` and `hyprctl configerrors`. Pinning the version in the ISO build is **not done and unverified**.
- *`hyprctl dispatch` calls:* the new picture-in-picture code uses `togglefloating`, `resizewindowpixel`, `movewindowpixel`, `pin`. **Untested on Hyprland 0.55+.**

**Pulled forward from phase H** (written, not yet tried on a real compositor): picture-in-picture (`SUPER+SHIFT+P`), screenshot annotation through swappy (`SUPER+SHIFT+A`). Also added: Night Light (hyprsunset), Focus mode (mako do-not-disturb), Orca screen-reader toggle, volume/brightness/media keys, fullscreen, move-to-workspace, mouse move/resize, a Settings Updates tab, and the nine wallpapers with a picker.

**Not started:** B shell spike, C Store (and the core/Store split), D search and switching evaluation, E Windows lane, F Android lane, G design pass (generated palette, icon family, type scale, compositor animations), and the rest of H (drag-to-edge snap, widgets board, multi-monitor, Cloud tier, AI back on, distrobox lane).

**Where this pass conflicts with the plan**
1. Section 1.4 says nothing new ships until the lag test passes. This pass added features before that test existed. Treat all the features above as **unshipped** until test 3 and 4 pass on both machines.
2. Section 5: the new config lines (`misc` options, binds, a final `source`, an opacity override rule) use the legacy `hyprland.conf` syntax. If the ISO's Hyprland is 0.55 or newer, run `hyprctl configerrors` first. The Lua migration is still open.
3. Section 3: the new dropdown, menu and disabled-button CSS reuses the current tokens. It is not the generated palette from design rule 1, and will be redone in phase G.
4. The default wallpaper (Midnight Silk) is the quietest of the nine, which suits "Calm Dark". The green, red and amber ones carry much more accent than the 10% rule allows; they stay as user choices.

**Known limitation:** the lock screen and login screen always show the default wallpaper, not the one the user picked.

**Still needed from you:** the UI references (coming), the core-vs-Store split (decision 1), shell direction (decision 3), license (decision 4), Flatpak scan gap (decision 5). Section 1.1 also asks for 3 screenshots of the real build (desktop, Command Center, Store); only a headless sandbox was available here, so those still have to come from your machine.
