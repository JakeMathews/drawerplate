"""Lay out a drawer label as an exact-size SVG (text converted to outlines)."""

from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

import svgpath

FONT_PATH = Path.home() / "Library/Fonts/JetBrainsMono-Bold.ttf"
PX_PER_IN = 96.0


CUT_STROKE_PX = 1.0


def is_cut_line(name):
    """Cut-only paths (frame, divider) are stroked hairlines, not filled shapes."""
    return name.startswith("cut")


def _paths_markup(paths, ink_color, x_px=0.0, y_px=0.0):
    """<path> elements for one label with its offset baked into the path data.

    Filled shapes (text, icons) merge into one path; each cut line stays its own
    unfilled stroked path so the cutter follows it once.
    """
    def placed(path_data):
        commands = svgpath.parse(path_data)
        if x_px or y_px:
            commands = svgpath.translate(commands, x_px, y_px)
        return svgpath.serialize(commands)

    fill_data = "".join(placed(data) for name, data in paths if not is_cut_line(name))
    markup = f'<path d="{fill_data}"/>' if fill_data else ""
    for name, data in paths:
        if is_cut_line(name):
            markup += (f'<path d="{placed(data)}" fill="none" stroke="{ink_color}" '
                       f'stroke-width="{CUT_STROKE_PX:g}"/>')
    return markup


def drawer_preview(entries, drawer_width_in, label_height_in=0.75, margin_in=0.15):
    """Compose a white-on-black mock-up of a drawer front from placed label paths.

    entries is a list of (side, paths, width_in) as returned by build_label.
    """
    width_px = drawer_width_in * PX_PER_IN
    height_px = (label_height_in + 2 * margin_in) * PX_PER_IN
    margin_px = margin_in * PX_PER_IN
    groups = []
    for side, paths, label_width_in in entries:
        x = margin_px if side == "primary" else (
            width_px - margin_px - label_width_in * PX_PER_IN
        )
        groups.append(_paths_markup(paths, "#ffffff", x, margin_px))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px:.1f}" '
        f'height="{height_px:.1f}" '
        f'viewBox="0 0 {width_px:.3f} {height_px:.3f}">'
        f'<rect width="100%" height="100%" fill="#111111"/>'
        f'<g fill="#ffffff" fill-rule="nonzero">{"".join(groups)}</g></svg>\n'
    )


def _sheet_svg(body, width_in, height_in, invert):
    background = '<rect width="100%" height="100%" fill="#111111"/>' if invert else ""
    ink_color = "#ffffff" if invert else "#000000"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{width_in:.4f}in" height="{height_in:.4f}in" '
        f'viewBox="0 0 {width_in * PX_PER_IN:.3f} {height_in * PX_PER_IN:.3f}">'
        f'{background}'
        f'<g fill="{ink_color}" fill-rule="nonzero" stroke="none">{body}</g></svg>\n'
    )


def tile_sheet(cells, cell_width_in, cell_height_in, columns, sheet_width_in,
               sheet_height_in, invert=False, margin_in=0.0, gutter_in=0.0):
    """Tile fixed-size label cells onto one full-size sheet SVG.

    cells is a list of path lists as returned by build_bin_label. Cells pack into the
    bottom-right corner, bottom row first and right to left, so the unused stock is
    one clean rectangle at the top left.
    """
    column_step_px = (cell_width_in + gutter_in) * PX_PER_IN
    row_step_px = (cell_height_in + gutter_in) * PX_PER_IN
    right_px = (sheet_width_in - margin_in - cell_width_in) * PX_PER_IN
    bottom_px = (sheet_height_in - margin_in - cell_height_in) * PX_PER_IN
    ink_color = "#ffffff" if invert else "#000000"
    groups = []
    for index, paths in enumerate(cells):
        x = right_px - (index % columns) * column_step_px
        y = bottom_px - (index // columns) * row_step_px
        groups.append(_paths_markup(paths, ink_color, x, y))
    return _sheet_svg("".join(groups), sheet_width_in, sheet_height_in, invert)


def nest(items, sheet_width_in, sheet_height_in, label_height_in, gutter_in, margin_in):
    """Shelf-pack fixed-height, variable-width labels onto sheets.

    items is a list of (key, paths, width_in). All labels share one height, so rows are
    uniform and only the horizontal fill varies — widest-first into the first row with
    room. Rows stack up from the bottom edge and each row is flush right, so the unused
    stock is one clean block at the top left. Returns a list of sheets, each a list of
    (key, paths, x_in, y_in).
    """
    usable_width_in = sheet_width_in - 2 * margin_in
    usable_height_in = sheet_height_in - 2 * margin_in
    rows_per_sheet = int(
        (usable_height_in + gutter_in + 1e-9) // (label_height_in + gutter_in)
    )
    if rows_per_sheet < 1:
        raise SystemExit(
            f"a {label_height_in}in label does not fit a {sheet_height_in}in sheet with "
            f"{margin_in}in margins"
        )
    too_wide = [key for key, _, width_in in items if width_in > usable_width_in]
    if too_wide:
        raise SystemExit(
            f"wider than the {usable_width_in:.2f}in usable sheet width: "
            f"{', '.join(too_wide)}"
        )

    row_widths_in = []
    row_contents = []
    for item in sorted(items, key=lambda entry: -entry[2]):
        item_width_in = item[2]
        for row_index, filled_width_in in enumerate(row_widths_in):
            if filled_width_in + gutter_in + item_width_in <= usable_width_in:
                row_widths_in[row_index] += gutter_in + item_width_in
                row_contents[row_index].append(item)
                break
        else:
            row_widths_in.append(item_width_in)
            row_contents.append([item])

    sheets = []
    for first_row in range(0, len(row_contents), rows_per_sheet):
        placed = []
        sheet_rows = row_contents[first_row : first_row + rows_per_sheet]
        for row_index, row_items in enumerate(sheet_rows):
            x_in = sheet_width_in - margin_in - row_widths_in[first_row + row_index]
            y_in = (sheet_height_in - margin_in - label_height_in
                    - row_index * (label_height_in + gutter_in))
            for key, paths, width_in in row_items:
                placed.append((key, paths, x_in, y_in))
                x_in += width_in + gutter_in
        sheets.append(placed)
    return sheets


def nest_sheet(placed, sheet_width_in, sheet_height_in, invert=False):
    """Render one packed sheet, baking each label's offset into its path data."""
    ink_color = "#ffffff" if invert else "#000000"
    rendered = [_paths_markup(paths, ink_color, x_in * PX_PER_IN, y_in * PX_PER_IN)
                for _, paths, x_in, y_in in placed]
    return _sheet_svg("".join(rendered), sheet_width_in, sheet_height_in, invert)


_font_cache = {}


def _load_font(path=FONT_PATH):
    path = Path(path)
    if path not in _font_cache:
        if not path.exists():
            raise SystemExit(f"Font not found: {path}")
        font = TTFont(str(path))
        _font_cache[path] = (font, font.getBestCmap(), font.getGlyphSet())
    return _font_cache[path]


def _cap_height(font):
    os2_table = font.get("OS/2")
    if os2_table is not None and getattr(os2_table, "sCapHeight", 0):
        return os2_table.sCapHeight
    return font["head"].unitsPerEm * 0.7


def text_outline(text, font_path=FONT_PATH, tracking_em=0.0):
    """Return (outline commands in font units, cap height in font units). Y is up."""
    font, character_map, glyph_set = _load_font(font_path)
    units_per_em = font["head"].unitsPerEm
    horizontal_metrics = font["hmtx"]
    tracking_units = tracking_em * units_per_em
    commands, pen_x, missing = [], 0.0, set()

    for character in text:
        glyph_name = character_map.get(ord(character))
        if glyph_name is None:
            missing.add(character)
            glyph_name = character_map.get(ord("?"))
        pen = SVGPathPen(glyph_set)
        glyph_set[glyph_name].draw(pen)
        path_data = pen.getCommands()
        if path_data:
            commands += svgpath.translate(svgpath.parse(path_data), pen_x, 0)
        pen_x += horizontal_metrics[glyph_name][0] + tracking_units

    if missing:
        print(f"  warning: font has no glyph for {sorted(missing)}")
    return commands, _cap_height(font)


def _icon_commands(icon, height_px):
    """Scale a cached (normalized, y-down, 1000-tall) icon path to height_px."""
    scale = height_px / 1000.0
    commands = svgpath.transform(svgpath.parse(icon["path"]), scale, 0, 0, scale, 0, 0)
    left, top, right, _ = svgpath.bounding_box(commands)
    return svgpath.translate(commands, -left, -top), right - left


# Offset that makes a cubic bezier approximate a quarter circle.
_KAPPA = 0.5522847498307936


def _rounded_rect(x, y, width, height, radius, counter_clockwise=False):
    """Absolute M/L/C/Z path for a rounded rectangle. Reverse winding cuts a hole."""
    radius = max(0.0, min(radius, width / 2, height / 2))
    control = radius * _KAPPA
    right, bottom = x + width, y + height
    if not counter_clockwise:
        return (
            f"M{x + radius:.3f},{y:.3f}"
            f"L{right - radius:.3f},{y:.3f}"
            f"C{right - radius + control:.3f},{y:.3f} "
            f"{right:.3f},{y + radius - control:.3f} {right:.3f},{y + radius:.3f}"
            f"L{right:.3f},{bottom - radius:.3f}"
            f"C{right:.3f},{bottom - radius + control:.3f} "
            f"{right - radius + control:.3f},{bottom:.3f} {right - radius:.3f},{bottom:.3f}"
            f"L{x + radius:.3f},{bottom:.3f}"
            f"C{x + radius - control:.3f},{bottom:.3f} "
            f"{x:.3f},{bottom - radius + control:.3f} {x:.3f},{bottom - radius:.3f}"
            f"L{x:.3f},{y + radius:.3f}"
            f"C{x:.3f},{y + radius - control:.3f} "
            f"{x + radius - control:.3f},{y:.3f} {x + radius:.3f},{y:.3f}Z"
        )
    return (
        f"M{x + radius:.3f},{y:.3f}"
        f"C{x + radius - control:.3f},{y:.3f} "
        f"{x:.3f},{y + radius - control:.3f} {x:.3f},{y + radius:.3f}"
        f"L{x:.3f},{bottom - radius:.3f}"
        f"C{x:.3f},{bottom - radius + control:.3f} "
        f"{x + radius - control:.3f},{bottom:.3f} {x + radius:.3f},{bottom:.3f}"
        f"L{right - radius:.3f},{bottom:.3f}"
        f"C{right - radius + control:.3f},{bottom:.3f} "
        f"{right:.3f},{bottom - radius + control:.3f} {right:.3f},{bottom - radius:.3f}"
        f"L{right:.3f},{y + radius:.3f}"
        f"C{right:.3f},{y + radius - control:.3f} "
        f"{right - radius + control:.3f},{y:.3f} {right - radius:.3f},{y:.3f}Z"
    )


# Measured off the hand-built reference label out/raw/bin.svg (Yamaha XSR900) and held
# as fractions of the box inside the pad so any bin size reproduces that layout. The
# reference art fills its 4in height edge to edge, so the text sits hard against the
# top of the box.
BIN_CAP_HEIGHT_FRACTION = 0.0922
BIN_TEXT_CENTER_FRACTION = 0.0522
BIN_ICON_CENTER_FRACTION = 0.6187
BIN_ICON_HEIGHT_FRACTION = 0.7530


def _svg_document(paths, width_in, height_in, viewbox_width_px, viewbox_height_px):
    body = "\n  ".join(
        f'<path id="{name}" d="{path_data}" fill="none" stroke="#000000" '
        f'stroke-width="{CUT_STROKE_PX:g}"/>'
        if is_cut_line(name) else f'<path id="{name}" d="{path_data}"/>'
        for name, path_data in paths
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{width_in:.4f}in" height="{height_in:.4f}in" '
        f'viewBox="0 0 {viewbox_width_px:.3f} {viewbox_height_px:.3f}">\n'
        '  <g fill="#000000" fill-rule="nonzero" stroke="none">\n  '
        f"{body}\n  </g>\n</svg>\n"
    )


def build_bin_label(
    text,
    icon=None,
    width_in=6.0,
    height_in=4.0,
    cap_height_in=None,
    icon_height_in=None,
    pad_in=0.25,
    tracking_em=0.0,
    border_px=1.0,
    corner_radius_in=0.25,
    divider=True,
    font_path=FONT_PATH,
):
    """Return (svg, paths, width_in, height_in) for a bin label: text over a subject.

    Both are centered on the cell's vertical axis, with the text cap box and the
    subject's bounding box each pinned to the height fraction measured off the
    reference label, so every bin size prints the same composition.

    A single cut line frames the cell at its edge and a divider runs across it midway
    between the text and the subject, so the negative weeds out in two smaller pieces.
    The composition is laid out in the box pad_in inside the frame, so nothing touches
    it. border_px=0 drops both cut lines.
    """
    width_px, height_px = width_in * PX_PER_IN, height_in * PX_PER_IN
    pad_px = pad_in * PX_PER_IN
    box_height_in = height_in - 2 * pad_in
    box_height_px = box_height_in * PX_PER_IN
    available_width_px = width_px - 2 * pad_px
    if cap_height_in is None:
        cap_height_in = box_height_in * BIN_CAP_HEIGHT_FRACTION
    if icon_height_in is None:
        icon_height_in = box_height_in * BIN_ICON_HEIGHT_FRACTION

    icon_commands, icon_width_px, icon_height_px = None, 0.0, 0.0
    if icon:
        icon_height_px = icon_height_in * PX_PER_IN
        icon_commands, icon_width_px = _icon_commands(icon, icon_height_px)
        if icon_width_px > available_width_px:
            icon_height_px *= available_width_px / icon_width_px
            icon_commands, icon_width_px = _icon_commands(icon, icon_height_px)

    text_commands, cap_height_units = text_outline(text, font_path, tracking_em)
    ink_box = svgpath.bounding_box(text_commands) if text_commands else None
    scale = (cap_height_in * PX_PER_IN) / cap_height_units
    if ink_box and (ink_box[2] - ink_box[0]) * scale > available_width_px:
        scale *= available_width_px / ((ink_box[2] - ink_box[0]) * scale)
        print(
            "  shrank text to fit: cap height "
            f"{scale * cap_height_units / PX_PER_IN:.3f}in"
        )
    cap_height_px = cap_height_units * scale

    icon_top_px = pad_px + box_height_px * BIN_ICON_CENTER_FRACTION - icon_height_px / 2
    if icon_commands and (icon_top_px < pad_px
                          or icon_top_px + icon_height_px > height_px - pad_px):
        raise SystemExit(
            f"a {icon_height_px / PX_PER_IN:.2f}in subject overruns the {box_height_in}in "
            "box inside the pad; lower --icon-height"
        )

    paths = []
    frame_px = CUT_STROKE_PX / 2
    if border_px > 0:
        paths.append(("cut-frame", _rounded_rect(
            frame_px, frame_px, width_px - 2 * frame_px, height_px - 2 * frame_px,
            corner_radius_in * PX_PER_IN,
        )))
    text_bottom_px = None
    if text_commands:
        baseline = pad_px + box_height_px * BIN_TEXT_CENTER_FRACTION + cap_height_px / 2
        left_px = (width_px - (ink_box[0] + ink_box[2]) * scale) / 2
        paths.append(("text", svgpath.serialize(svgpath.transform(
            text_commands, scale, 0, 0, -scale, left_px, baseline
        ))))
        text_bottom_px = baseline - ink_box[1] * scale
    if icon_commands:
        paths.append(("icon", svgpath.serialize(svgpath.translate(
            icon_commands, (width_px - icon_width_px) / 2, icon_top_px
        ))))
    if border_px > 0 and divider and text_bottom_px is not None and icon_commands:
        divider_px = (text_bottom_px + icon_top_px) / 2
        paths.append(("cut-divider",
                      f"M{frame_px:.3f},{divider_px:.3f}"
                      f"L{width_px - frame_px:.3f},{divider_px:.3f}"))

    svg = _svg_document(paths, width_in, height_in, width_px, height_px)
    return svg, paths, width_in, height_in


def build_label(
    text,
    icon=None,
    side="primary",
    label_height_in=0.75,
    cap_height_in=None,
    icon_height_in=None,
    gap_in=0.12,
    pad_in=0.0,
    tracking_em=0.0,
    max_width_in=None,
    border_px=1.0,
    inset_px=5.0,
    corner_radius_in=0.09,
    icon_slot_in=0.75,
    icon_align="center",
    guide_in=0.1,
    font_path=FONT_PATH,
):
    """Return (svg, paths, width_in, height_in). Icon prefixes primary, suffixes secondary.

    A rounded frame rings the label as a single cut line, held inset_px clear of the
    content (border_px is its drawn weight; 0 drops it). Icon and cap height both
    default to whatever that leaves, so the two match and fill the label without
    touching the frame.

    The icon sits in a slot icon_slot_in wide no matter how wide the icon is, so the
    text starts at the same x on every label (0 shrinks the slot to the icon). Icons
    wider than the slot scale down to fit it; icon_align puts the icon at the left,
    center or right of the slot.

    guide_in adds a filled bar of that width on the outer edge of the label, the full
    content height, with a gap before the icon slot. It is a positive piece: it weeds
    and transfers with the label so its outer edge can be squared to a pencil line or
    the drawer edge, then it peels off once the label is down. 0 omits it.
    """
    height_px = label_height_in * PX_PER_IN
    gap_px = gap_in * PX_PER_IN
    pad_px = pad_in * PX_PER_IN
    border = max(0.0, border_px)
    inset = inset_px if border else 0.0
    frame_px = pad_px + border + inset

    content_height_px = height_px - 2 * frame_px
    if content_height_px <= 0:
        raise SystemExit(
            f"border+inset take up more than the {label_height_in}in label height"
        )
    if cap_height_in is None:
        cap_height_in = content_height_px / PX_PER_IN
    if icon_height_in is None:
        icon_height_in = content_height_px / PX_PER_IN

    if icon_align not in ("left", "center", "right"):
        raise SystemExit(f"icon_align must be left, center or right, not {icon_align!r}")
    slot_px = max(0.0, icon_slot_in) * PX_PER_IN
    guide_px = max(0.0, guide_in) * PX_PER_IN
    guide_and_gap_px = guide_px + gap_px if guide_px else 0.0

    icon_commands, icon_width_px, icon_height_px = None, 0.0, 0.0
    if icon:
        icon_height_px = icon_height_in * PX_PER_IN
        icon_commands, icon_width_px = _icon_commands(icon, icon_height_px)
        if slot_px and icon_width_px > slot_px:
            icon_height_px *= slot_px / icon_width_px
            icon_commands, icon_width_px = _icon_commands(icon, icon_height_px)
            print(f"  shrank icon to fit the {icon_slot_in:g}in slot: "
                  f"{icon_height_px / PX_PER_IN:.3f}in tall")
        slot_px = max(slot_px, icon_width_px)
    else:
        slot_px = 0.0

    text_commands, cap_height_units = text_outline(text, font_path, tracking_em)

    def lay_out(cap_in):
        scale = (cap_in * PX_PER_IN) / cap_height_units
        ink_box = svgpath.bounding_box(text_commands) if text_commands else None
        width_px = (ink_box[2] - ink_box[0]) * scale if ink_box else 0.0
        return scale, ink_box, width_px

    scale, ink_box, text_width_px = lay_out(cap_height_in)
    icon_and_gap_px = slot_px + gap_px if icon_commands else 0.0
    fixed_px = frame_px * 2 + guide_and_gap_px + icon_and_gap_px

    if max_width_in is not None:
        total_px = fixed_px + text_width_px
        limit_px = max_width_in * PX_PER_IN
        if total_px > limit_px and text_width_px > 0:
            room_px = limit_px - fixed_px
            if room_px <= 0:
                raise SystemExit(f"--max-width {max_width_in}in leaves no room for text")
            cap_height_in *= room_px / text_width_px
            scale, ink_box, text_width_px = lay_out(cap_height_in)
            print(f"  shrank text to fit: cap height {cap_height_in:.3f}in")

    total_width_px = fixed_px + text_width_px

    # Reading order from the outer edge inward: guide bar, icon slot, text.
    if side == "primary":
        guide_x = frame_px
        slot_x = frame_px + guide_and_gap_px
        text_x = slot_x + icon_and_gap_px
    else:
        text_x = frame_px
        slot_x = text_x + text_width_px + gap_px
        guide_x = total_width_px - frame_px - guide_px
    slack_px = slot_px - icon_width_px
    icon_x = slot_x + {"left": 0.0, "center": slack_px / 2, "right": slack_px}[icon_align]

    paths = []
    if border:
        radius_px = corner_radius_in * PX_PER_IN
        paths.append(("cut-frame", _rounded_rect(
            pad_px + border / 2, pad_px + border / 2,
            total_width_px - 2 * pad_px - border, height_px - 2 * pad_px - border,
            radius_px,
        )))

    if guide_px:
        top = frame_px
        paths.append(("guide", f"M{guide_x:.3f},{top:.3f}L{guide_x + guide_px:.3f},{top:.3f}"
                               f"L{guide_x + guide_px:.3f},{height_px - frame_px:.3f}"
                               f"L{guide_x:.3f},{height_px - frame_px:.3f}Z"))

    if icon_commands:
        paths.append(("icon", svgpath.serialize(svgpath.translate(
            icon_commands, icon_x, (height_px - icon_height_px) / 2
        ))))

    if text_commands:
        baseline = (height_px + cap_height_in * PX_PER_IN) / 2
        paths.append(("text", svgpath.serialize(svgpath.transform(
            text_commands, scale, 0, 0, -scale, text_x - ink_box[0] * scale, baseline
        ))))

    width_in = total_width_px / PX_PER_IN
    height_in = height_px / PX_PER_IN
    svg = _svg_document(paths, width_in, height_in, total_width_px, height_px)
    return svg, paths, width_in, height_in
