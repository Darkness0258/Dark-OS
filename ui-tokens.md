# UI Tokens

> Design primitives as variables. If a value could be typed as a raw number or hex code inside a component, it belongs here instead.

## Color
```css
--color-bg: #000000;                      /* Pure Black */
--color-bg-alt: #0d0f12;                  /* Dark Carbon */
--color-bg-elevated: #16181c;             /* Dark Graphite */
--color-surface: rgba(255,255,255,0.06);  /* glass panel fill, blurred */
--color-border: rgba(255,255,255,0.12);   /* edge definition on glass */
--color-text: #f2f5f7;
--color-text-muted: #9aa4ad;
--color-primary: #00e5ff;                 /* Electric Cyan */
--color-secondary: #2d7bff;               /* Neon Blue */
--color-accent: #a855f7;                  /* Purple */
--color-warning: #ff8a00;                 /* Orange — alerts */
--color-danger: #ff3b3b;                  /* Red — warnings */
--color-success: #22e07a;                 /* Green — success */
```

## Spacing
```css
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 32px;
--space-xl: 48px;
```

## Typography
```css
--font-body: "Inter", "SF Pro Display", sans-serif;   /* thin, elegant weight for body text */
--font-heading: "Space Grotesk", sans-serif;          /* slightly futuristic display face */
--text-sm: 13px;
--text-base: 15px;
--text-lg: 20px;
--text-xl: 32px;
--letter-spacing-uppercase: 0.5px;
```

Apply `--letter-spacing-uppercase` to uppercase section and subsection labels. Product wordmarks are a deliberate exception and may use wider brand tracking (the desktop HUD uses `2px`).

## Radius / elevation
- Corner radius: 8px (compact controls/cards), 16px (panels), 24px (dialogs / AI Orb container), fully round (dock icons, AI Orb itself)
- Glass: GTK surfaces achieve blur through Hyprland compositor layerrules (`blur on`, `blur_passes`, `blur_size`), not CSS `backdrop-filter` (GTK3 doesn't support it). The 24px token represents the target visual equivalent; actual blur is rendered by the compositor. `--color-surface` fill, `--color-border` 1px edge
- Glow: use exactly three same-color Cairo strokes, painted outside-in so the haze cannot soften the core: outer haze `10px × 0.12 alpha`, mid glow `5px × 0.40`, sharp core `2px × 1.00`. Multiply that curve by the component's base alpha; keep the ratios unchanged. Preserve one path between strokes (`stroke_preserve`) instead of reconstructing three slightly different paths. GTK widgets are real controls, so use CSS blur instead: resting AI orb `0 0 16px alpha(primary, 0.30)`, active toggle `0 0 12px alpha(primary, 0.32)`, and hover/focus may strengthen the same hue. Reserve glow for AI, focus, and active states; applying it everywhere destroys hierarchy.
- Elevation: 3 levels — resting (no shadow), raised (soft 24px blur shadow), active (glow + raised)

## Rings / gauges
- Circular progress rings for stats (CPU/GPU/RAM/storage): thin stroke, `--color-primary` fill arc, remaining track at low-opacity `--color-surface`, percentage centered inside
- The AI Core HUD scales the same ring language up dramatically — multiple concentric rings, segmented/dashed arcs, slow idle rotation, brightens and speeds up with assistant activity

---
`imprint` checks new components against this file. If a token is missing, that's a signal the design system needs to grow, not that the component should hardcode a value.
