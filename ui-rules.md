# UI Rules

> Behavior and layout conventions — the things a design system enforces that tokens alone can't.

## Layout
- Top bar: logo + wordmark (left), date/time (center), system tray — display, sound, Bluetooth, Wi-Fi, battery %, avatar (right)
- Left icon rail: AI, Files, Terminal, Settings, Browser, Gallery, Store, Notes, Music, Gaming — icon-only, always visible
- Center stage: the AI Core — circular radar/dial HUD (concentric rings, segmented labeled arcs, cyan glow on black), "Dark OS" wordmark and "Control Everything" tagline beneath it — nothing else competes with it for visual weight
- Floating glass panels, left-of-center: AI chat card (greeting + waveform + input box), weather, system overview (CPU/GPU/RAM/storage as circular gauges with specifics, network up/down)
- Floating glass panels, right-of-center: notifications (grouped, "Clear All"), connectivity (Wi-Fi/Bluetooth status cards + Dark Mode/Airplane/Night Light/Focus toggles + brightness/volume sliders), media widget, calendar
- App windows (Files, Terminal, etc.) float freely above this base layer — glass, rounded, glow border, closable/minimizable/resizable
- Bottom dock: floating, transparent, rounded, centered, AI Orb enlarged at its center — icons enlarge on hover — never a solid bar spanning full width
- Responsive breakpoints: TBD once target display sizes are confirmed — this is desktop-first; exact HiDPI/tablet breakpoints come once Phase 2 has a real display to test on

## Motion
- Every animation must serve a purpose (state change, feedback, or attention) — no decoration that doesn't communicate something
- Physics-based movement for window open/close/resize/drag — spring/elastic easing, never linear
- Target 120 FPS on animations; degrade gracefully on lower-end GPUs (reduce particles/glow first — never drop frame pacing)
- AI Orb has exactly 5 states, each with its own motion signature: sleeping (slow breathing glow), listening (reactive waveform), thinking (rotating/pulsing rings), speaking (waveform synced to audio output), error (brief red pulse, not a jarring shake)

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
