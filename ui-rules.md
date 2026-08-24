# UI Rules

> Behavior and layout conventions — the things a design system enforces that tokens alone can't.

## Layout
**Always-on base layer:**
- Top bar: logo + wordmark (left), date/time (center), system tray — display, sound, Bluetooth, Wi-Fi, battery %, avatar (right)
- Left icon rail: AI, Files, Terminal, Settings, Browser, Gallery, Store, Notes, Music, Gaming — icon-only, always visible
- Bottom dock: floating, transparent, rounded, centered, AI Orb enlarged at its center (idle/"sleeping" state when Command Center is closed) — icons enlarge on hover — never a solid bar spanning full width
- App windows (Files, Terminal, etc.) float freely above this base layer — glass, rounded, glow border, closable/minimizable/resizable

**Command Center (on demand — SUPER+H, or `--toggle-command-center`):**
- Center stage: the AI Core — circular radar/dial HUD (concentric rings, segmented labeled arcs, cyan glow on black), "Dark OS" wordmark and "Control Everything" tagline beneath it — nothing else competes with it for visual weight
- Floating glass panels, left-of-center: AI chat card (greeting + waveform + input box), weather, system overview (CPU/GPU/RAM/storage as circular gauges with specifics, network up/down)
- Floating glass panels, right-of-center: notifications (grouped, "Clear All"), connectivity (Wi-Fi/Bluetooth status cards + Dark Mode/Airplane/Night Light/Focus toggles + brightness/volume sliders), media widget, calendar
- Dismisses the same way it opened (HUD visibility is the source-of-truth open/closed flag — see `__init__.py:do_command_line`); reuses the panel stagger-in animation already documented below in Motion, since that entrance only makes narrative sense as a real power-on moment
- Known open edge case: `activity_detector` can still independently show/hide left/right by activity profile while Command Center is open or closed — the two systems aren't yet reconciled, see progress-tracker.md
- Responsive breakpoints: TBD once target display sizes are confirmed — this is desktop-first; exact HiDPI/tablet breakpoints come once Phase 2 has a real display to test on

## Motion
- Every animation must serve a purpose (state change, feedback, or attention) — no decoration that doesn't communicate something
- Physics-based movement for window open/close/resize/drag — spring/elastic easing, never linear
- Target 120 FPS on animations; degrade gracefully on lower-end GPUs (reduce particles/glow first — never drop frame pacing)
- AI Orb has exactly 5 states, each with its own motion signature: sleeping (slow breathing glow), listening (reactive waveform), thinking (rotating/pulsing rings), speaking (waveform synced to audio output), error (brief red pulse, not a jarring shake)
- Panel entrances stagger (40-60ms offset per panel), not all at once — reinforces the "HUD powering on" feel from the reference mockup
- Dock icons get magnetic hover (icon + 1-2 neighbors scale slightly toward cursor), matching the "enlarge on hover" rule already set above
- App-to-app switches use a brief scan-line/glass-refraction transition instead of a hard cut, reusing the existing glass material rather than a new effect
- Ambient background (behind the AI Core) subtly reacts to system load — never so much it competes with the Core for attention, per the existing "nothing competes with the Core" rule

## Buttons & interactive states
- Primary action: filled glass panel, `--color-primary` glow on hover/focus
- Secondary: outline only, glow appears on hover, not at rest
- Destructive: `--color-danger`, always behind a confirmation dialog
- Disabled: 40% opacity, no glow, no hover response
- Loading: reuses the AI Orb's "thinking" ring-pulse motion language — one motion vocabulary reused everywhere, not a generic spinner

## Component conventions
- Every modal/dialog closes from the same corner (top-right) and closes on `Esc`
- Every floating panel dismisses on click-outside — no dead-end modals
- Global search is reachable from one shortcut everywhere, not re-implemented per app
- Notifications are grouped and AI-summarized, never a raw unsorted stack

## Accessibility baseline
- Fully keyboard-navigable end to end — voice/AI control is an addition, not a replacement for keyboard/mouse
- Minimum 4.5:1 contrast for body text even against glass/blur backgrounds — glow and blur are never an excuse to drop contrast
- Visible focus states on every interactive element — glow alone isn't sufficient for low-vision users
- High-contrast and dyslexia-friendly font options ship as a real settings toggle, not an afterthought
