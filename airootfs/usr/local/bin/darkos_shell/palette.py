#!/usr/bin/env python3
"""Calm Dark palette generator.

Pure Python on purpose (no GTK, no settings): the design check in
ci/test-design-tokens.py, the Waybar style generator and the shell all import
the same code, so a colour can't be right in one place and wrong in another.

Everything is generated from two inputs: the accent seed (a user setting,
default #00E5FF) and one neutral hue. Surfaces are placed by OKLCH lightness
so the steps between them are even to the eye, then checked against WCAG
contrast (docs/MASTER-PLAN.md section 5, rules 1, 2 and 8):

* three tonal surfaces (base, raised, overlay), not pure black
* body text >= 4.5:1 on every surface, control borders >= 3:1
* the accent text colour and the label on an accent button are adjusted to
  pass whatever accent the user picks
"""
import math

# Neutral hue (OKLCH degrees): deep blue-grey.
NEUTRAL_HUE = 255

# (lightness, chroma) per role, dark mode.
SURFACES = {
    "bg_base": (0.145, 0.016),
    "bg_raised": (0.225, 0.018),
    "bg_overlay": (0.305, 0.020),
}
TEXT_TONES = {
    "text": (0.96, 0.006),
    "text_muted": (0.78, 0.016),
}
BORDER_CONTROL_TONE = (0.60, 0.020)

# Minimum ratios (WCAG 2.x). Text 4.5:1, large text / UI components 3:1.
MIN_TEXT = 4.5
MIN_UI = 3.0
MIN_SURFACE_STEP = 1.15
HC_MIN_TEXT = 7.0


# ── Colour maths ──────────────────────────────────────────────────────

def hex_to_rgb(value):
    """'#rrggbb' -> (r, g, b) as ints 0-255."""
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"not a hex colour: {value!r}")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _to_linear(channel):
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _from_linear(value):
    value = max(0.0, min(1.0, value))
    return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055


def relative_luminance(value):
    r, g, b = (_to_linear(c) for c in hex_to_rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first, second):
    """WCAG contrast ratio, 1.0 (identical) to 21.0 (black on white)."""
    high, low = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def hex_to_oklch(value):
    r, g, b = (_to_linear(c) for c in hex_to_rgb(value))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(x) ** (1 / 3), x) for x in (l, m, s))
    lab_l = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    lab_a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    lab_b = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    chroma = math.hypot(lab_a, lab_b)
    hue = math.degrees(math.atan2(lab_b, lab_a)) % 360 if chroma > 1e-4 else 0.0
    return lab_l, chroma, hue


def _oklch_to_linear_rgb(lightness, chroma, hue):
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )


def oklch_to_hex(lightness, chroma, hue):
    """OKLCH -> '#rrggbb'. Out-of-gamut colours lose chroma (not hue or
    lightness) until they fit, so a vivid request never shifts colour."""
    lightness = max(0.0, min(1.0, lightness))
    low, high = 0.0, max(0.0, chroma)
    rgb = _oklch_to_linear_rgb(lightness, high, hue)
    if not all(-1e-4 <= c <= 1 + 1e-4 for c in rgb):
        for _ in range(24):
            mid = (low + high) / 2
            rgb = _oklch_to_linear_rgb(lightness, mid, hue)
            if all(-1e-4 <= c <= 1 + 1e-4 for c in rgb):
                low = mid
            else:
                high = mid
        rgb = _oklch_to_linear_rgb(lightness, low, hue)
    return rgb_to_hex(tuple(_from_linear(c) * 255 for c in rgb))


def ensure_contrast(color, background, minimum):
    """Return `color` unchanged if it already reaches `minimum`:1 on
    `background`; otherwise move its OKLCH lightness (hue and chroma kept)
    away from the background just far enough."""
    if contrast_ratio(color, background) >= minimum:
        return color
    lightness, chroma, hue = hex_to_oklch(color)
    lighten = relative_luminance(background) < 0.5
    step = 0.005 if lighten else -0.005
    for _ in range(200):
        lightness += step
        candidate = oklch_to_hex(lightness, chroma, hue)
        if contrast_ratio(candidate, background) >= minimum:
            return candidate
        if lightness <= 0.0 or lightness >= 1.0:
            break
    return "#ffffff" if lighten else "#000000"


def shift_lightness(color, delta):
    lightness, chroma, hue = hex_to_oklch(color)
    return oklch_to_hex(lightness + delta, chroma, hue)


# ── Palette ───────────────────────────────────────────────────────────

def _normalise_accent(accent):
    try:
        return rgb_to_hex(hex_to_rgb(accent))
    except (ValueError, AttributeError, TypeError):
        return "#00e5ff"


def generate_palette(accent="#00e5ff", high_contrast=False):
    """Every colour the shell and the apps use, as '#rrggbb' strings."""
    accent = _normalise_accent(accent)
    if high_contrast:
        return _high_contrast_palette(accent)

    palette = {name: oklch_to_hex(L, C, NEUTRAL_HUE) for name, (L, C) in SURFACES.items()}
    palette.update({name: oklch_to_hex(L, C, NEUTRAL_HUE) for name, (L, C) in TEXT_TONES.items()})
    palette["border_control"] = oklch_to_hex(*BORDER_CONTROL_TONE, NEUTRAL_HUE)
    palette["text_disabled"] = oklch_to_hex(0.58, 0.014, NEUTRAL_HUE)

    overlay = palette["bg_overlay"]
    palette["accent"] = accent
    palette["accent_hover"] = shift_lightness(accent, 0.06)
    palette["accent_pressed"] = shift_lightness(accent, -0.06)
    # Accent used as *text* (links, active labels) must pass on every surface.
    palette["accent_text"] = ensure_contrast(accent, overlay, MIN_TEXT)
    # The label on a filled accent button: dark or light, whichever reads best.
    dark = oklch_to_hex(0.18, 0.03, hex_to_oklch(accent)[2])
    palette["on_accent"] = max((dark, "#ffffff"), key=lambda c: contrast_ratio(c, accent))

    palette["success"] = ensure_contrast(oklch_to_hex(0.80, 0.17, 150), overlay, MIN_TEXT)
    palette["warning"] = ensure_contrast(oklch_to_hex(0.83, 0.15, 80), overlay, MIN_TEXT)
    palette["danger"] = ensure_contrast(oklch_to_hex(0.72, 0.19, 25), overlay, MIN_TEXT)
    palette["on_danger"] = palette["bg_base"]
    palette["black"] = "#000000"
    return palette


def _high_contrast_palette(accent):
    """Opaque black and white, 7:1 everywhere, for the High Contrast mode."""
    black, white = "#000000", "#ffffff"
    bright = ensure_contrast(accent, black, HC_MIN_TEXT)
    return {
        "bg_base": black, "bg_raised": black, "bg_overlay": black,
        "text": white, "text_muted": white, "text_disabled": "#bdbdbd",
        "border_control": white,
        "accent": bright, "accent_hover": bright, "accent_pressed": bright,
        "accent_text": bright, "on_accent": black,
        "success": ensure_contrast("#4ade80", black, HC_MIN_TEXT),
        "warning": ensure_contrast("#fbbf24", black, HC_MIN_TEXT),
        "danger": ensure_contrast("#ff7b72", black, HC_MIN_TEXT),
        "on_danger": black, "black": black,
    }


def validate(palette, high_contrast=False):
    """Check a palette against the design rules. Returns a list of plain-text
    violations; an empty list means it passes."""
    problems = []
    surfaces = [palette[name] for name in ("bg_base", "bg_raised", "bg_overlay")]
    text_min = HC_MIN_TEXT if high_contrast else MIN_TEXT

    if not high_contrast:
        if palette["bg_base"].lower() == "#000000":
            problems.append("bg_base is pure black")
        for lower, upper in zip(surfaces, surfaces[1:]):
            ratio = contrast_ratio(lower, upper)
            if ratio < MIN_SURFACE_STEP:
                problems.append(f"surface step {lower}->{upper} is only {ratio:.2f}:1 (needs {MIN_SURFACE_STEP}:1)")

    for name in ("text", "text_muted", "accent_text", "success", "warning", "danger"):
        for surface_name, surface in zip(("bg_base", "bg_raised", "bg_overlay"), surfaces):
            ratio = contrast_ratio(palette[name], surface)
            if ratio < text_min:
                problems.append(f"{name} on {surface_name} is {ratio:.2f}:1 (needs {text_min}:1)")
    for surface_name, surface in zip(("bg_base", "bg_raised", "bg_overlay"), surfaces):
        ratio = contrast_ratio(palette["border_control"], surface)
        if ratio < MIN_UI:
            problems.append(f"border_control on {surface_name} is {ratio:.2f}:1 (needs {MIN_UI}:1)")
    ratio = contrast_ratio(palette["on_accent"], palette["accent"])
    if ratio < text_min:
        problems.append(f"label on accent button is {ratio:.2f}:1 (needs {text_min}:1)")
    ratio = contrast_ratio(palette["on_danger"], palette["danger"])
    if ratio < text_min:
        problems.append(f"label on danger is {ratio:.2f}:1 (needs {text_min}:1)")
    return problems


def to_rgb_floats(value):
    """'#rrggbb' -> (r, g, b) floats 0-1, the form Cairo wants."""
    return tuple(c / 255.0 for c in hex_to_rgb(value))
