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
```

## Radius / elevation
- Corner radius: 16px (panels), 24px (dialogs / AI Orb container), fully round (dock icons, AI Orb itself)
- Glass: `backdrop-filter: blur(24px)`, `--color-surface` fill, `--color-border` 1px edge
- Glow: soft outer glow in `--color-primary` or `--color-accent`, low opacity, reserved for focus/active states — a glow on every element reads as noise, not premium
- Elevation: 3 levels — resting (no shadow), raised (soft 24px blur shadow), active (glow + raised)

## Rings / gauges
- Circular progress rings for stats (CPU/GPU/RAM/storage): thin stroke, `--color-primary` fill arc, remaining track at low-opacity `--color-surface`, percentage centered inside
- The AI Core HUD scales the same ring language up dramatically — multiple concentric rings, segmented/dashed arcs, slow idle rotation, brightens and speeds up with assistant activity

---
`imprint` checks new components against this file. If a token is missing, that's a signal the design system needs to grow, not that the component should hardcode a value.
