#!/usr/bin/env python3
"""Generate the DarkOS boot/login wallpaper.

Crop-safe layout for Cover-fit on 16:9 displays:
  - 1536x1024 source → 1920x1080 with Cover = 100px cropped top + bottom
  - All important text sits in the center 50% vertical zone (y=256-768)
  - Corner labels placed at y=920 (bottom 10%) — WILL be cropped on 16:9,
    so they're decorative only, not informational
"""

import math
import os

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1536, 1024
OUTPUT = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "usr", "share", "backgrounds", "darkos", "darkos-wallpaper.png"
)

PRIMARY = (0, 229, 255)
SECONDARY = (45, 123, 255)
TEXT = (242, 245, 247)
MUTED = (154, 164, 173)
DANGER = (255, 59, 59)


def main():
    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background: dark radial gradient
    for y in range(HEIGHT):
        for x in range(WIDTH):
            dx, dy = x - WIDTH / 2, y - HEIGHT / 2
            dist = math.sqrt(dx * dx + dy * dy) / 750
            val = int(max(0, min(255, dist * 14)))
            img.putpixel((x, y), (val, val + 3, val + 5))

    cx, cy = WIDTH // 2, HEIGHT // 2
    ring_color = PRIMARY
    rotation = 0.5

    # Ambient glow
    pulse = 20 + 3 * math.sin(rotation * 4.0)
    for r in range(3, 22):
        a = max(0, int((1 - r / 22) * 25))
        draw.ellipse(
            [cx - pulse - r, cy - pulse - r, cx + pulse + r, cy + pulse + r],
            outline=(*ring_color, a),
        )

    # Inner dashed ring (r=54) — glow layers
    for lw, la in ((10, 0.12), (5, 0.40), (2, 1.0)):
        draw.arc(
            [cx - 54, cy - 54, cx + 54, cy + 54],
            0, 360, fill=(*ring_color, int(la * 255)), width=lw,
        )
    for angle in range(0, 360, 18):
        a = math.radians(angle + rotation * 24)
        x1 = cx + 54 * math.cos(a)
        y1 = cy + 54 * math.sin(a)
        x2 = cx + (54 - 8) * math.cos(a)
        y2 = cy + (54 - 8) * math.sin(a)
        draw.line([(x1, y1), (x2, y2)], fill=(*ring_color, 200), width=2)

    # Solid double-line ring (r=68/70) with intentional small gaps
    draw.arc([cx - 70, cy - 70, cx + 70, cy + 70], 0, 360,
             fill=(*SECONDARY, 200), width=1)
    draw.arc([cx - 68, cy - 68, cx + 68, cy + 68], 0, 360,
             fill=(*SECONDARY, 150), width=1)
    for angle_deg in (90, 270):
        a = math.radians(angle_deg)
        x1 = cx + (69 - 3) * math.cos(a - 0.18)
        y1 = cy + (69 - 3) * math.sin(a - 0.18)
        x2 = cx + (69 + 3) * math.cos(a + 0.18)
        y2 = cy + (69 + 3) * math.sin(a + 0.18)
        draw.line([(x1, y1), (x2, y2)], fill=(*TEXT, 30), width=3)

    # Middle dashed ring (r=88)
    for lw, la in ((10, 0.12), (5, 0.40), (2, 1.0)):
        draw.arc(
            [cx - 88, cy - 88, cx + 88, cy + 88],
            0, 360, fill=(*SECONDARY, int(la * 255 * 0.8)), width=lw,
        )
    for angle in range(0, 360, 18):
        a = math.radians(angle - rotation * 18)
        x1 = cx + 88 * math.cos(a)
        y1 = cy + 88 * math.sin(a)
        x2 = cx + (88 - 8) * math.cos(a)
        y2 = cy + (88 - 8) * math.sin(a)
        draw.line([(x1, y1), (x2, y2)], fill=(*SECONDARY, 160), width=2)

    # Outer dashed ring (r=122)
    for lw, la in ((10, 0.12), (5, 0.40), (2, 1.0)):
        draw.arc(
            [cx - 122, cy - 122, cx + 122, cy + 122],
            0, 360, fill=(*ring_color, int(la * 255 * 0.75)), width=lw,
        )
    for angle in range(0, 360, 18):
        a = math.radians(angle + rotation * 12)
        x1 = cx + 122 * math.cos(a)
        y1 = cy + 122 * math.sin(a)
        x2 = cx + (122 - 10) * math.cos(a)
        y2 = cy + (122 - 10) * math.sin(a)
        draw.line([(x1, y1), (x2, y2)], fill=(*ring_color, 140), width=2)

    # Bezel ring + ticks
    bezel = 136
    draw.arc(
        [cx - bezel, cy - bezel, cx + bezel, cy + bezel],
        0, 360, fill=(*TEXT, 30), width=1,
    )
    for angle in range(0, 360, 15):
        a = math.radians(angle)
        inner = bezel - 4
        outer = bezel - (2 if angle % 45 == 0 else 0)
        draw.line(
            [(cx + inner * math.cos(a), cy + inner * math.sin(a)),
             (cx + outer * math.cos(a), cy + outer * math.sin(a))],
            fill=(*TEXT, 30), width=1,
        )

    # Accent line + readout dashes at top
    top = -math.pi / 2.0
    x1, y1 = cx + 122 * math.cos(top), cy + 122 * math.sin(top)
    x2, y2 = cx + 132 * math.cos(top), cy + 132 * math.sin(top)
    draw.line([(x1, y1), (x2, y2)], fill=(*PRIMARY, 150), width=2)
    for i in range(3):
        draw.line(
            [(x2 + 4, y2 - 6 + i * 4), (x2 + 10, y2 - 6 + i * 4)],
            fill=(*TEXT, 50 + i * 15), width=1,
        )

    # Radial spokes
    for angle_deg in (0, 60, 120, 180, 240, 300):
        a = math.radians(angle_deg)
        draw.line(
            [(cx + 40 * math.cos(a), cy + 40 * math.sin(a)),
             (cx + bezel * math.cos(a), cy + bezel * math.sin(a))],
            fill=(*TEXT, 15), width=1,
        )

    # Center pulse
    cr_p = int(pulse)
    draw.ellipse(
        [cx - cr_p, cy - cr_p, cx + cr_p, cy + cr_p],
        outline=(*ring_color, 220), width=1,
    )

    # === TEXT — all in the center 50% vertical zone (safe from Cover crop) ===
    # DARK OS wordmark (center, slightly above ring center)
    try:
        font_bold = ImageFont.truetype("/usr/share/fonts/ttf/Inter/Inter-Bold.ttf", 28)
        font_tag = ImageFont.truetype("/usr/share/fonts/ttf/Inter/Inter-Regular.ttf", 14)
    except (OSError, IOError):
        font_bold = ImageFont.load_default()
        font_tag = font_bold

    text = "DARK OS"
    bbox = draw.textbbox((0, 0), text, font=font_bold)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw // 2, cy + 155), text, fill=TEXT, font=font_bold)

    text = "CONTROL EVERYTHING"
    bbox = draw.textbbox((0, 0), text, font=font_tag)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw // 2, cy + 182), text, fill=PRIMARY, font=font_tag)

    # Corner labels — decorative only, WILL be cropped on 16:9 with Cover
    corner_font = ImageFont.load_default()
    corner_color = (*MUTED, 140)
    draw.text((20, HEIGHT - 40), "SYSTEM ONLINE", fill=corner_color, font=corner_font)
    bbox = draw.textbbox((0, 0), "DARK OS 1.3.0", font=corner_font)
    tw = bbox[2] - bbox[0]
    draw.text((WIDTH - tw - 20, HEIGHT - 40), "DARK OS 1.3.0", fill=corner_color, font=corner_font)

    img.save(OUTPUT, "PNG")
    print(f"Wallpaper written to {OUTPUT}  ({WIDTH}x{HEIGHT})")


if __name__ == "__main__":
    main()
