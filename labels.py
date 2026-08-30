"""Lay out a drawer label as an exact-size SVG (text converted to outlines)."""

from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

import svgpath

FONT_PATH = Path.home() / "Library/Fonts/JetBrainsMono-Bold.ttf"
PX_PER_IN = 96.0


def drawer_preview(entries, drawer_width_in, label_height_in=0.75, margin_in=0.15):
    """Compose a white-on-black mock-up of a drawer front from placed label paths.

    entries is a list of (side, paths, width_in) as returned by build_label.
    """
    W = drawer_width_in * PX_PER_IN
    H = (label_height_in + 2 * margin_in) * PX_PER_IN
    m = margin_in * PX_PER_IN
    groups = []
    for side, paths, w_in in entries:
        x = m if side == "primary" else W - m - w_in * PX_PER_IN
        d = "".join(p for _, p in paths)
        groups.append(f'<g transform="translate({x:.3f},{m:.3f})"><path d="{d}"/></g>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.1f}" height="{H:.1f}" '
        f'viewBox="0 0 {W:.3f} {H:.3f}">'
        f'<rect width="100%" height="100%" fill="#111111"/>'
        f'<g fill="#ffffff" fill-rule="nonzero">{"".join(groups)}</g></svg>\n'
    )

def tile_sheet(cells, cell_w_in, cell_h_in, cols, invert=False):
    """Tile fixed-size label cells into one exact-size sheet SVG.

    cells is a list of path lists as returned by build_bin_label.
    """
    rows = (len(cells) + cols - 1) // cols
    cw, ch = cell_w_in * PX_PER_IN, cell_h_in * PX_PER_IN
    W, H = cols * cw, rows * ch
    groups = []
    for i, paths in enumerate(cells):
        x, y = (i % cols) * cw, (i // cols) * ch
        d = "".join(p for _, p in paths)
        groups.append(f'<g transform="translate({x:.3f},{y:.3f})"><path d="{d}"/></g>')
    back = '<rect width="100%" height="100%" fill="#111111"/>' if invert else ""
    ink = "#ffffff" if invert else "#000000"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{cols * cell_w_in:.4f}in" height="{rows * cell_h_in:.4f}in" '
        f'viewBox="0 0 {W:.3f} {H:.3f}">{back}'
        f'<g fill="{ink}" fill-rule="nonzero" stroke="none">{"".join(groups)}</g></svg>\n'
    )


_font_cache = {}


def _font(path=FONT_PATH):
    path = Path(path)
    if path not in _font_cache:
        if not path.exists():
            raise SystemExit(f"Font not found: {path}")
        f = TTFont(str(path))
        _font_cache[path] = (f, f.getBestCmap(), f.getGlyphSet())
    return _font_cache[path]


def _cap_height(font):
    os2 = font.get("OS/2")
    if os2 is not None and getattr(os2, "sCapHeight", 0):
        return os2.sCapHeight
    return font["head"].unitsPerEm * 0.7


def text_outline(text, font_path=FONT_PATH, tracking_em=0.0):
    """Return (outline commands in font units, cap height in font units). Y is up."""
    font, cmap, glyphset = _font(font_path)
    upem = font["head"].unitsPerEm
    hmtx = font["hmtx"]
    tracking = tracking_em * upem
    cmds, pen_x, missing = [], 0.0, set()

    for ch in text:
        name = cmap.get(ord(ch))
        if name is None:
            missing.add(ch)
            name = cmap.get(ord("?"))
        pen = SVGPathPen(glyphset)
        glyphset[name].draw(pen)
        d = pen.getCommands()
        if d:
            cmds += svgpath.transform(svgpath.parse(d), 1, 0, 0, 1, pen_x, 0)
        pen_x += hmtx[name][0] + tracking

    if missing:
        print(f"  warning: font has no glyph for {sorted(missing)}")
    return cmds, _cap_height(font)


def _icon_commands(icon, height_px):
    """Scale a cached (normalized, y-down, 1000-tall) icon path to height_px."""
    s = height_px / 1000.0
    cmds = svgpath.transform(svgpath.parse(icon["path"]), s, 0, 0, s, 0, 0)
    x0, y0, x1, y1 = svgpath.bbox(cmds)
    cmds = svgpath.transform(cmds, 1, 0, 0, 1, -x0, -y0)
    return cmds, (x1 - x0)


def build_bin_label(
    text,
    icon=None,
    width_in=6.0,
    height_in=4.0,
    cap_height_in=0.4,
    icon_height_in=2.2,
    gap_in=0.25,
    pad_in=0.25,
    tracking_em=0.0,
    font_path=FONT_PATH,
):
    """Return (svg, paths, width_in, height_in) for a bin label: text stacked over icon.

    Unlike a drawer label the canvas is a fixed cell; content is centered in it both
    ways so a shelf of bins lines up without measuring anything on import.
    """
    W, H = width_in * PX_PER_IN, height_in * PX_PER_IN
    gap = gap_in * PX_PER_IN
    avail_w = W - 2 * pad_in * PX_PER_IN

    icon_cmds, icon_w, icon_h = None, 0.0, 0.0
    if icon:
        icon_h = icon_height_in * PX_PER_IN
        icon_cmds, icon_w = _icon_commands(icon, icon_h)
        if icon_w > avail_w:
            shrink = avail_w / icon_w
            icon_h *= shrink
            icon_cmds, icon_w = _icon_commands(icon, icon_h)

    raw, cap_units = text_outline(text, font_path, tracking_em)
    ink = svgpath.bbox(raw) if raw else None
    scale = (cap_height_in * PX_PER_IN) / cap_units
    if ink and (ink[2] - ink[0]) * scale > avail_w:
        scale *= avail_w / ((ink[2] - ink[0]) * scale)
        print(f"  shrank text to fit: cap height {scale * cap_units / PX_PER_IN:.3f}in")
    text_w = (ink[2] - ink[0]) * scale if ink else 0.0
    text_h = (ink[3] - ink[1]) * scale if ink else 0.0

    block_h = text_h + icon_h + (gap if text_h and icon_h else 0.0)
    if block_h > H:
        raise SystemExit(
            f"content is {block_h / PX_PER_IN:.2f}in tall but the cell is {height_in}in; "
            "lower --icon-height or --cap-height"
        )
    top = (H - block_h) / 2

    paths = []
    if raw:
        baseline = top + ink[3] * scale
        paths.append(("text", svgpath.serialize(svgpath.transform(
            raw, scale, 0, 0, -scale, (W - text_w) / 2 - ink[0] * scale, baseline
        ))))
    if icon_cmds:
        paths.append(("icon", svgpath.serialize(svgpath.transform(
            icon_cmds, 1, 0, 0, 1, (W - icon_w) / 2, top + text_h + (gap if text_h else 0)
        ))))

    body = "\n  ".join(f'<path id="{name}" d="{d}"/>' for name, d in paths)
    svg = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{width_in:.4f}in" height="{height_in:.4f}in" '
        f'viewBox="0 0 {W:.3f} {H:.3f}">\n'
        '  <g fill="#000000" fill-rule="nonzero" stroke="none">\n  '
        f"{body}\n  </g>\n</svg>\n"
    )
    return svg, paths, width_in, height_in


def build_label(
    text,
    icon=None,
    side="primary",
    label_height_in=0.75,
    cap_height_in=0.5,
    icon_height_in=0.75,
    gap_in=0.12,
    pad_in=0.0,
    tracking_em=0.0,
    max_width_in=None,
    font_path=FONT_PATH,
):
    """Return (svg_string, width_in, height_in). Icon prefixes primary, suffixes secondary."""
    H = label_height_in * PX_PER_IN
    gap = gap_in * PX_PER_IN
    pad = pad_in * PX_PER_IN

    icon_cmds, icon_w = (None, 0.0)
    if icon:
        icon_cmds, icon_w = _icon_commands(icon, icon_height_in * PX_PER_IN)

    raw, cap_units = text_outline(text, font_path, tracking_em)

    def lay_out(cap_in):
        scale = (cap_in * PX_PER_IN) / cap_units
        ink = svgpath.bbox(raw) if raw else None
        w = (ink[2] - ink[0]) * scale if ink else 0.0
        return scale, ink, w

    scale, ink, text_w = lay_out(cap_height_in)

    if max_width_in is not None:
        total = pad * 2 + text_w + (icon_w + gap if icon_cmds else 0.0)
        limit = max_width_in * PX_PER_IN
        if total > limit and text_w > 0:
            room = limit - (pad * 2 + (icon_w + gap if icon_cmds else 0.0))
            if room <= 0:
                raise SystemExit(f"--max-width {max_width_in}in leaves no room for text")
            cap_height_in *= room / text_w
            scale, ink, text_w = lay_out(cap_height_in)
            print(f"  shrank text to fit: cap height {cap_height_in:.3f}in")

    content_w = text_w + (icon_w + gap if icon_cmds else 0.0)
    total_w = pad * 2 + content_w

    if side == "primary":
        icon_x, text_x = pad, pad + icon_w + gap
    else:
        text_x, icon_x = pad, pad + text_w + gap
    if not icon_cmds:
        text_x = pad

    paths = []
    if icon_cmds:
        placed = svgpath.transform(
            icon_cmds, 1, 0, 0, 1, icon_x, (H - icon_height_in * PX_PER_IN) / 2
        )
        paths.append(("icon", svgpath.serialize(placed)))

    if raw:
        baseline = (H + cap_height_in * PX_PER_IN) / 2
        placed = svgpath.transform(
            raw, scale, 0, 0, -scale, text_x - ink[0] * scale, baseline
        )
        paths.append(("text", svgpath.serialize(placed)))

    w_in, h_in = total_w / PX_PER_IN, H / PX_PER_IN
    body = "\n  ".join(
        f'<path id="{name}" d="{d}"/>' for name, d in paths
    )
    svg = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{w_in:.4f}in" height="{h_in:.4f}in" '
        f'viewBox="0 0 {total_w:.3f} {H:.3f}">\n'
        '  <g fill="#000000" fill-rule="nonzero" stroke="none">\n  '
        f"{body}\n  </g>\n</svg>\n"
    )
    return svg, paths, w_in, h_in
