r"""Generate the MT5 workstation icon set for both appearance modes.

Run with the project virtual environment::

    .\.venv\Scripts\python.exe src\mt5_workbench\ui\resources\icons\generate.py

Only Pillow is used for raster output. SVG and PNG use the same vector geometry.
The 24-unit view box makes every glyph line up on the same visual grid.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw


HERE = Path(__file__).resolve().parent
GLYPH_SIZES = (16, 20, 24, 32)

# These follow mt5_workbench.ui.theme. Gold highlights selected navigation actions.
PALETTES = {
    "dark": {
        "ink": "#CFD9E7",
        "gold": "#F6C777",
        "surface": "#17263B",
    },
    "light": {
        "ink": "#41546D",
        "gold": "#B4751C",
        "surface": "#FFFFFF",
    },
}


class Glyph:
    def __init__(self) -> None:
        self.ops: list[tuple] = []

    def line(self, points, color="ink", width=1.8):
        self.ops.append(("line", tuple(points), color, width))

    def polygon(self, points, fill, stroke=None, width=1.6):
        self.ops.append(("polygon", tuple(points), fill, stroke, width))

    def rect(self, x0, y0, x1, y1, radius=0, fill=None, stroke="ink", width=1.8):
        self.ops.append(("rect", (x0, y0, x1, y1), radius, fill, stroke, width))

    def circle(self, x, y, radius, fill=None, stroke="ink", width=1.8):
        self.ops.append(("circle", (x, y, radius), fill, stroke, width))


def build(name: str, active: bool = False) -> Glyph:
    g = Glyph()
    c = "gold" if active else "ink"
    if name == "dashboard":
        g.rect(3, 3, 21, 21, 2.5, stroke=c)
        g.line(((7, 15), (10.2, 11.7), (12.4, 13.2), (17.3, 7.7)), c, 1.9)
        g.line(((7, 17.8), (17.5, 17.8)), c, 1.4)
    elif name == "orders":
        g.rect(5, 3, 19, 21, 2.2, stroke=c)
        g.line(((8, 8), (16, 8)), c)
        g.line(((8, 12), (16, 12)), c)
        g.line(((8, 16), (13.4, 16)), c)
    elif name == "journal":
        g.line(((5, 5), (19, 5), (21, 7), (21, 15), (19, 17),
                (14, 17), (10, 21), (10, 17), (5, 17), (3, 15),
                (3, 7), (5, 5)), c, 1.8)
        g.line(((7, 9), (17, 9)), c, 1.5)
        g.line(((7, 12.5), (14, 12.5)), c, 1.5)
    elif name == "allocation":
        g.rect(3, 14, 7, 20, 0.8, stroke=c)
        g.rect(10, 10, 14, 20, 0.8, stroke=c)
        g.rect(17, 5, 21, 20, 0.8, stroke=c)
    elif name == "controls":
        for y in (6, 12, 18):
            g.line(((3.5, y), (20.5, y)), c)
        for x, y in ((9, 6), (15, 12), (8, 18)):
            g.circle(x, y, 2, "surface", c, 1.8)
    elif name == "refresh":
        points = [(12 + 7 * math.cos(math.radians(a)),
                   12 + 7 * math.sin(math.radians(a)))
                  for a in range(40, 321, 20)]
        g.line(points, c, 1.9)
        g.line(((18.8, 5.9), (18.6, 9), (15.4, 8.9)), c, 1.9)
    elif name == "sun":
        g.circle(12, 12, 3.6, stroke=c)
        for angle in range(0, 360, 45):
            a = math.radians(angle)
            g.line(((12 + 7.2 * math.cos(a), 12 + 7.2 * math.sin(a)),
                    (12 + 9.2 * math.cos(a), 12 + 9.2 * math.sin(a))), c, 1.7)
    elif name == "moon":
        g.line(((15.6, 3.7), (13.2, 5.8), (11.9, 8.9), (12.2, 12.2),
                (14.3, 14.8), (17.3, 15.7), (20, 15)), c, 1.8)
        g.line(((20, 15), (18, 18), (14.6, 20), (10.9, 20.1),
                (7.3, 18.4), (4.8, 15.2), (4, 11.5), (5.1, 7.7),
                (7.7, 4.9), (11.3, 3.6), (15.6, 3.7)), c, 1.8)
    elif name == "fullscreen":
        for points in (((9, 4), (4, 4), (4, 9)),
                       ((15, 4), (20, 4), (20, 9)),
                       ((4, 15), (4, 20), (9, 20)),
                       ((20, 15), (20, 20), (15, 20))):
            g.line(points, c)
    elif name == "exit-fullscreen":
        for points in (((4, 9), (9, 9), (9, 4)),
                       ((20, 9), (15, 9), (15, 4)),
                       ((4, 15), (9, 15), (9, 20)),
                       ((20, 15), (15, 15), (15, 20))):
            g.line(points, c)
    elif name == "send":
        g.polygon(((3, 11.4), (20.3, 3.8), (15.1, 20.2), (11.4, 13.1)),
                  None, c, 1.7)
        g.line(((11.4, 13.1), (20.3, 3.8)), c, 1.6)
    elif name == "copy":
        g.rect(7, 7, 20, 21, 2, stroke=c)
        g.line(((4, 17), (4, 5.2), (5.2, 4), (16, 4)), c)
        g.line(((10, 12), (17, 12)), c, 1.4)
        g.line(((10, 15.5), (16, 15.5)), c, 1.4)
    elif name == "calculate":
        g.rect(5, 3, 19, 21, 2, stroke=c)
        g.rect(8, 6, 16, 9.1, 0.5, stroke=c, width=1.2)
        for x in (9, 12, 15):
            for y in (13, 17):
                g.circle(x, y, 0.7, c, None)
    elif name == "close":
        g.rect(3.5, 3.5, 20.5, 20.5, 3, stroke=c)
        g.line(((8, 8), (16, 16)), c, 2)
        g.line(((16, 8), (8, 16)), c, 2)
    elif name == "remove":
        g.line(((4, 7), (20, 7)), c)
        g.line(((9, 4), (15, 4)), c)
        g.line(((6.5, 8), (7.5, 20), (16.5, 20), (17.5, 8)), c)
        g.line(((10, 11), (10.5, 17)), c, 1.4)
        g.line(((14, 11), (13.5, 17)), c, 1.4)
    elif name == "connection":
        g.line(((5, 7), (5, 11), (8, 14), (16, 14), (19, 11), (19, 7)), c)
        g.line(((8, 3), (8, 7)), c)
        g.line(((16, 3), (16, 7)), c)
        g.line(((12, 14), (12, 21)), c)
    elif name == "warning":
        g.polygon(((12, 3.5), (21, 20), (3, 20)), None, c, 1.8)
        g.line(((12, 9), (12, 14)), c, 2)
        g.circle(12, 17, 0.8, c, None)
    elif name == "check":
        g.circle(12, 12, 9, stroke=c)
        g.line(((7.2, 12.1), (10.3, 15.2), (16.9, 8.6)), c, 2)
    elif name == "info":
        g.circle(12, 12, 9, stroke=c)
        g.line(((12, 10.5), (12, 16.8)), c, 1.9)
        g.circle(12, 7.4, 0.85, c, None)
    elif name == "calendar":
        g.rect(3.5, 5.5, 20.5, 21, 2.1, stroke=c)
        g.line(((3.5, 10), (20.5, 10)), c)
        g.line(((8, 3), (8, 7.5)), c)
        g.line(((16, 3), (16, 7.5)), c)
        g.circle(8, 14, 0.8, c, None)
        g.circle(12, 14, 0.8, c, None)
        g.circle(16, 14, 0.8, c, None)
    elif name == "chart-line":
        g.line(((4, 4), (4, 20), (21, 20)), c, 1.5)
        g.line(((7, 16), (10, 12), (13, 14), (17.5, 7.5), (20, 9)), c, 1.9)
    elif name == "candles":
        g.line(((6, 6), (6, 19)), c, 1.5)
        g.rect(4, 9, 8, 15, 0.5, stroke=c, width=1.5)
        g.line(((12, 3.5), (12, 16)), c, 1.5)
        g.rect(10, 6, 14, 12, 0.5, stroke=c, width=1.5)
        g.line(((18, 7), (18, 20)), c, 1.5)
        g.rect(16, 11, 20, 17, 0.5, stroke=c, width=1.5)
    elif name == "bar-chart":
        g.line(((3, 20), (21, 20)), c, 1.4)
        g.rect(4, 12, 8, 19, 0.6, stroke=c, width=1.6)
        g.rect(10, 8, 14, 19, 0.6, stroke=c, width=1.6)
        g.rect(16, 4, 20, 19, 0.6, stroke=c, width=1.6)
    elif name == "status":
        g.circle(12, 12, 8.5, stroke=c)
        g.circle(12, 12, 3, fill=c, stroke=None)
    elif name == "confirm":
        g.circle(12, 12, 9, stroke=c)
        g.line(((7.2, 12.1), (10.3, 15.2), (16.9, 8.6)), c, 2)
    elif name == "cancel":
        g.circle(12, 12, 9, stroke=c)
        g.line(((9, 9), (15, 15)), c, 1.9)
        g.line(((15, 9), (9, 15)), c, 1.9)
    else:
        raise ValueError(f"Unknown glyph: {name}")
    return g


def svg(g: Glyph, palette: dict[str, str]) -> str:
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
             'viewBox="0 0 24 24" fill="none">']
    color = lambda key: palette[key] if key else "none"
    for op in g.ops:
        if op[0] == "line":
            _, points, stroke, width = op
            coords = " ".join(f"{x:.3g},{y:.3g}" for x, y in points)
            parts.append(f'<polyline points="{coords}" fill="none" '
                         f'stroke="{color(stroke)}" stroke-width="{width}" '
                         'stroke-linecap="round" stroke-linejoin="round"/>')
        elif op[0] == "polygon":
            _, points, fill, stroke, width = op
            coords = " ".join(f"{x:.3g},{y:.3g}" for x, y in points)
            parts.append(f'<polygon points="{coords}" fill="{color(fill)}" '
                         f'stroke="{color(stroke)}" stroke-width="{width}" '
                         'stroke-linecap="round" stroke-linejoin="round"/>')
        elif op[0] == "rect":
            _, (x0, y0, x1, y1), radius, fill, stroke, width = op
            parts.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" '
                         f'rx="{radius}" fill="{color(fill)}" stroke="{color(stroke)}" '
                         f'stroke-width="{width}"/>')
        else:
            _, (x, y, radius), fill, stroke, width = op
            parts.append(f'<circle cx="{x}" cy="{y}" r="{radius}" '
                         f'fill="{color(fill)}" stroke="{color(stroke)}" '
                         f'stroke-width="{width}"/>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def raster(g: Glyph, palette: dict[str, str], size: int) -> Image.Image:
    scale = size / 24 * 8
    side = size * 8
    image = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    xy = lambda point: (round(point[0] * scale), round(point[1] * scale))
    rgba = lambda key: palette[key] if key else None
    for op in g.ops:
        if op[0] == "line":
            _, points, stroke, width = op
            coords = [xy(point) for point in points]
            w = max(1, round(width * scale))
            draw.line(coords, fill=rgba(stroke), width=w, joint="curve")
            radius = w / 2
            for x, y in (coords[0], coords[-1]):
                draw.ellipse((round(x-radius), round(y-radius),
                              round(x+radius), round(y+radius)),
                             fill=rgba(stroke))
        elif op[0] == "polygon":
            _, points, fill, stroke, width = op
            coords = [xy(point) for point in points]
            draw.polygon(coords, fill=rgba(fill))
            if stroke:
                draw.line(coords + [coords[0]], fill=rgba(stroke),
                          width=max(1, round(width * scale)), joint="curve")
        elif op[0] == "rect":
            _, (x0, y0, x1, y1), radius, fill, stroke, width = op
            draw.rounded_rectangle((*xy((x0, y0)), *xy((x1, y1))),
                                   radius=round(radius * scale),
                                   fill=rgba(fill), outline=rgba(stroke),
                                   width=max(1, round(width * scale)))
        else:
            _, (x, y, radius), fill, stroke, width = op
            draw.ellipse((*xy((x-radius, y-radius)), *xy((x+radius, y+radius))),
                         fill=rgba(fill), outline=rgba(stroke),
                         width=max(1, round(width * scale)))
    return image.resize((size, size), Image.Resampling.LANCZOS)


NAMES = ("dashboard", "orders", "allocation", "controls", "journal",
         "refresh", "sun", "moon", "fullscreen", "exit-fullscreen", "send",
         "copy", "calculate", "close", "remove", "connection", "warning",
         "check", "info", "calendar", "chart-line", "candles", "bar-chart",
         "status", "confirm", "cancel")
ACTIVE_NAMES = ("dashboard", "orders", "allocation", "controls", "journal", "chart-line")


def main() -> None:
    for theme, palette in PALETTES.items():
        svg_dir = HERE / "svg" / theme
        svg_dir.mkdir(parents=True, exist_ok=True)
        for name in NAMES:
            for active in ((False, True) if name in ACTIVE_NAMES else (False,)):
                label = name + ("-active" if active else "")
                glyph = build(name, active)
                (svg_dir / f"{label}.svg").write_text(svg(glyph, palette), encoding="utf-8")
                for size in GLYPH_SIZES:
                    raster(glyph, palette, size).save(HERE / f"{label}-{theme}-{size}.png")


if __name__ == "__main__":
    main()
