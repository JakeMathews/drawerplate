#!/usr/bin/env python3
"""Generate exact-size toolbox drawer label SVGs for Easy Cut Studio 6 / vinyl plotters.

Labels are 0.75in tall. A primary label is left justified on the drawer and gets an
icon prefix; an optional secondary label sits on the right and gets an icon suffix.
Text is converted to outlines so no font substitution can happen on import.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

import icons
import labels

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "out"


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "label"


def add_style_arguments(parser):
    group = parser.add_argument_group("sizing")
    group.add_argument("--label-height", type=float, default=0.75, metavar="IN")
    group.add_argument("--cap-height", type=float, default=None, metavar="IN",
                       help="height of a capital letter (default: fill inside the frame)")
    group.add_argument("--icon-height", type=float, default=None, metavar="IN",
                       help="icon height (default: match the cap height)")
    group.add_argument("--border", type=float, default=1.0, metavar="PX",
                       help="width of the rounded frame around the label "
                            "(default 1, 0 omits it)")
    group.add_argument("--inset", type=float, default=5.0, metavar="PX",
                       help="clearance between the frame and the content (default 5)")
    group.add_argument("--corner-radius", type=float, default=0.09, metavar="IN",
                       help="corner rounding on the frame (default 0.09)")
    group.add_argument("--gap", type=float, default=0.12, metavar="IN",
                       help="space between icon and text (default 0.12)")
    group.add_argument("--icon-slot", type=float, default=0.75, metavar="IN",
                       help="fixed width reserved for the icon so text lines up across "
                            "drawers; wider icons shrink to fit (default 0.75, 0 hugs "
                            "the icon)")
    group.add_argument("--icon-align", default="center", choices=["left", "center", "right"],
                       help="where the icon sits inside its slot (default center)")
    group.add_argument("--guide", type=float, default=0.1, metavar="IN",
                       help="width of the peel-off alignment bar on the label's outer "
                            "edge (default 0.1, 0 omits it)")
    group.add_argument("--pad", type=float, default=0.0, metavar="IN",
                       help="blank margin outside the frame (default 0)")
    group.add_argument("--tracking", type=float, default=0.0, metavar="EM",
                       help="extra letter spacing in em (default 0)")
    group.add_argument("--max-width", type=float, default=None, metavar="IN",
                       help="shrink text if the label would exceed this width")
    group.add_argument("--font", default=str(labels.FONT_PATH))
    group.add_argument("--no-upper", action="store_true", help="keep text as typed")
    group.add_argument("--drawer-width", type=float, default=None, metavar="IN",
                       help="drawer front width; sizes the preview and warns on crowding")

    add_trace_arguments(parser)


def add_sheet_arguments(parser):
    group = parser.add_argument_group("sheets")
    group.add_argument("--sheet-width", type=float, default=12.0, metavar="IN",
                       help="stock vinyl width to nest labels onto (default 12)")
    group.add_argument("--sheet-height", type=float, default=12.0, metavar="IN",
                       help="sheet height (default 12)")
    group.add_argument("--gutter", type=float, default=0.125, metavar="IN",
                       help="space between nested labels (default 0.125)")
    group.add_argument("--sheet-margin", type=float, default=0.25, metavar="IN",
                       help="blank margin around the sheet edge (default 0.25)")
    group.add_argument("--no-sheets", action="store_true",
                       help="render the labels but skip the nested sheets")


def add_bin_arguments(parser):
    group = parser.add_argument_group("sizing")
    group.add_argument("--bin-width", type=float, default=6.0, metavar="IN",
                       help="width of one label cell (default 6)")
    group.add_argument("--bin-height", type=float, default=4.0, metavar="IN",
                       help="height of one label cell (default 4)")
    group.add_argument("--cap-height", type=float, default=None, metavar="IN",
                       help="default 0.0922 of the cell height, per the reference label")
    group.add_argument("--icon-height", type=float, default=None, metavar="IN",
                       help="default 0.753 of the cell height, per the reference label")
    group.add_argument("--pad", type=float, default=0.25, metavar="IN",
                       help="keep-out margin inside the cell (default 0.25)")
    group.add_argument("--tracking", type=float, default=0.0, metavar="EM")
    group.add_argument("--font", default=str(labels.FONT_PATH))
    group.add_argument("--upper", action="store_true", help="uppercase the text")
    group.add_argument("--border", type=float, default=1.0, metavar="PX",
                       help="drawn weight of the frame cut line; 0 omits frame and divider")
    group.add_argument("--corner-radius", type=float, default=0.25, metavar="IN",
                       help="corner rounding on the frame (default 0.25)")
    group.add_argument("--no-divider", action="store_true",
                       help="skip the cut line between the text and the subject")
    group.add_argument("--sheet-width", type=float, default=12.0, metavar="IN",
                       help="stock vinyl width to tile labels across (default 12)")
    group.add_argument("--sheet-height", type=float, default=14.0, metavar="IN",
                       help="stock vinyl height to tile labels down (default 14)")
    group.add_argument("--sheet-margin", type=float, default=0.25, metavar="IN",
                       help="blank margin around the sheet edge (default 0.25)")
    group.add_argument("--gutter", type=float, default=0.25, metavar="IN",
                       help="blank space between tiled labels (default 0.25)")
    add_trace_arguments(parser, icon_style="bin")


def add_trace_arguments(parser, icon_style="solid"):
    group = parser.add_argument_group("icon tracing")
    group.add_argument("--threshold", type=int, default=128)
    group.add_argument("--turdsize", type=int, default=150,
                       help="drop traced specks/holes smaller than this area in source "
                            "px (default 150, about 0.01in on the finished label)")
    group.add_argument("--alphamax", type=float, default=1.0)
    group.add_argument("--opttolerance", type=float, default=0.2)
    group.add_argument("--invert", action="store_true",
                       help="source art is light-on-dark; flip it before tracing")
    group.add_argument("--quality", default="high", choices=["low", "medium", "high"])
    group.add_argument("--icon-style", default=icon_style, choices=sorted(icons.PROMPTS),
                       help="solid silhouette (weeds best) or heavy outline drawing")
    group.add_argument("--max-pieces", type=int, default=3, metavar="N",
                       help="reroll a generated icon that traces to more than N separate "
                            "black pieces; islands fall off transfer tape (default 3)")
    group.add_argument("--attempts", type=int, default=2, metavar="N",
                       help="image generations to try before keeping the one with the "
                            "fewest pieces (default 2)")
    group.add_argument("--regen", action="store_true",
                       help="regenerate cached icons (imported ones are retraced instead)")
    group.add_argument("--retrace", action="store_true",
                       help="re-vectorize cached PNGs without calling OpenAI")


def style_options(args):
    return dict(
        label_height_in=args.label_height,
        cap_height_in=args.cap_height,
        icon_height_in=args.icon_height,
        gap_in=args.gap,
        pad_in=args.pad,
        tracking_em=args.tracking,
        max_width_in=args.max_width,
        border_px=args.border,
        inset_px=args.inset,
        corner_radius_in=args.corner_radius,
        icon_slot_in=args.icon_slot,
        icon_align=args.icon_align,
        guide_in=args.guide,
        font_path=args.font,
    )


def bin_style_options(args):
    return dict(
        width_in=args.bin_width,
        height_in=args.bin_height,
        cap_height_in=args.cap_height,
        icon_height_in=args.icon_height,
        pad_in=args.pad,
        tracking_em=args.tracking,
        border_px=args.border,
        corner_radius_in=args.corner_radius,
        divider=not args.no_divider,
        font_path=args.font,
    )


def trace_options(args):
    return dict(
        threshold=args.threshold,
        turdsize=args.turdsize,
        alphamax=args.alphamax,
        opttolerance=args.opttolerance,
        invert=args.invert,
    )


def resolve_icon(slug, description, args):
    if not slug:
        return None
    regen = "retrace" if args.retrace else args.regen
    return icons.ensure(slug, description, regen=regen, quality=args.quality,
                        style=args.icon_style, max_pieces=args.max_pieces,
                        attempts=args.attempts, **trace_options(args))


def relative_to_root(path):
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


def rasterize(svg, png_path, zoom=2):
    temp_svg = png_path.with_suffix(".preview.svg")
    temp_svg.parent.mkdir(parents=True, exist_ok=True)
    temp_svg.write_text(svg)
    try:
        subprocess.run(
            ["rsvg-convert", "-z", str(zoom), str(temp_svg), "-o", str(png_path)],
            check=True, capture_output=True,
        )
        temp_svg.unlink()
        print(f"  preview   -> {relative_to_root(png_path)}")
    except (FileNotFoundError, subprocess.CalledProcessError):
        print(f"  preview   -> {relative_to_root(temp_svg)} (install librsvg for PNG)")


def write_label(text, icon, side, args, out_path):
    if not args.no_upper:
        text = text.upper()
    svg, paths, width_in, height_in = labels.build_label(
        text, icon=icon, side=side, **style_options(args)
    )
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg)
    print(f"  {side:<9} {width_in:6.3f} x {height_in:.3f} in  {text!r}"
          f"  -> {relative_to_root(out_path)}")
    return side, paths, width_in


def write_preview(entries, args, png_path):
    if not entries:
        return
    used_in = sum(width_in for _, _, width_in in entries)
    drawer_width_in = args.drawer_width or (used_in + 0.6)
    rasterize(
        labels.drawer_preview(entries, drawer_width_in,
                              label_height_in=args.label_height),
        png_path, zoom=3,
    )
    if args.drawer_width and used_in + 0.45 > args.drawer_width:
        print(f"  WARNING: labels total {used_in:.2f}in, drawer is "
              f"{args.drawer_width:.2f}in — they will crowd or overlap")


def render_drawer(name, primary, secondary, args):
    print(f"drawer {name}:")
    drawer_dir = OUT_DIR / name
    entries = [write_label(primary["text"],
                           resolve_icon(primary.get("icon"),
                                        primary.get("icon_desc"), args),
                           "primary", args, drawer_dir / "primary.svg")]
    if secondary and secondary.get("text"):
        entries.append(write_label(secondary["text"],
                                   resolve_icon(secondary.get("icon"),
                                                secondary.get("icon_desc"), args),
                                   "secondary", args, drawer_dir / "secondary.svg"))
    write_preview(entries, args, drawer_dir / "preview.png")
    return [(f"{name}/{side}", paths, width_in) for side, paths, width_in in entries]


def _clear_stale_sheets(stem):
    # A shorter run leaves higher-numbered sheets behind; they'd look cuttable.
    for old in stem.parent.glob(f"{stem.name}-[0-9][0-9].*"):
        if old.suffix in (".svg", ".png"):
            old.unlink()


def write_sheets(items, args, stem):
    if getattr(args, "no_sheets", False):
        return
    print(f"sheets ({args.sheet_width:g} x {args.sheet_height:g} in):")
    stem.parent.mkdir(parents=True, exist_ok=True)
    _clear_stale_sheets(stem)
    if not items:
        print("  nothing left to nest")
        return
    sheets = labels.nest(items, args.sheet_width, args.sheet_height,
                         args.label_height, args.gutter, args.sheet_margin)
    for number, placed in enumerate(sheets, 1):
        path = stem.parent / f"{stem.name}-{number:02d}.svg"
        path.write_text(labels.nest_sheet(placed, args.sheet_width, args.sheet_height))
        print(f"  sheet {number:02d}  {len(placed):2d} labels"
              f"  -> {relative_to_root(path)}")
        rasterize(
            labels.nest_sheet(placed, args.sheet_width, args.sheet_height, invert=True),
            path.with_suffix(".png"),
        )


def write_bin_label(spec, args, out_path):
    text = spec["text"].upper() if args.upper else spec["text"]
    icon = resolve_icon(spec.get("icon"), spec.get("icon_desc"), args)
    svg, paths, width_in, height_in = labels.build_bin_label(
        text, icon=icon, **bin_style_options(args)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg)
    print(f"  bin       {width_in:6.3f} x {height_in:.3f} in  {text!r}"
          f"  -> {relative_to_root(out_path)}")
    return paths


def write_bin_sheets(cells, args, stem):
    margin_in, gutter_in = args.sheet_margin, args.gutter

    def cells_across(stock_in, cell_in):
        usable_in = stock_in - 2 * margin_in + gutter_in + 1e-9
        return max(1, int(usable_in // (cell_in + gutter_in)))

    columns = cells_across(args.sheet_width, args.bin_width)
    rows = cells_across(args.sheet_height, args.bin_height)
    per_sheet = columns * rows
    print(f"sheets ({args.sheet_width:g} x {args.sheet_height:g} in, {margin_in:g}in "
          f"margin, {gutter_in:g}in gutter, {columns} x {rows} bins):")
    stem.parent.mkdir(parents=True, exist_ok=True)
    _clear_stale_sheets(stem)
    for first_cell in range(0, len(cells), per_sheet):
        chunk = cells[first_cell : first_cell + per_sheet]
        number = first_cell // per_sheet + 1
        sheet_path = stem.parent / f"{stem.name}-{number:02d}.svg"
        sheet_path.write_text(
            labels.tile_sheet(chunk, args.bin_width, args.bin_height, columns,
                              args.sheet_width, args.sheet_height,
                              margin_in=margin_in, gutter_in=gutter_in)
        )
        print(f"  sheet {number:02d}  {len(chunk):2d} labels"
              f"  -> {relative_to_root(sheet_path)}")
        rasterize(
            labels.tile_sheet(chunk, args.bin_width, args.bin_height, columns,
                              args.sheet_width, args.sheet_height,
                              invert=True, margin_in=margin_in, gutter_in=gutter_in),
            sheet_path.with_suffix(".png"),
        )


def _apply_file_defaults(data, args, keys):
    if not isinstance(data, dict):
        return
    for key in keys:
        if data.get(key):
            setattr(args, key, data[key])


def run_label(args):
    icon = resolve_icon(args.icon, args.icon_desc, args)
    out_path = (Path(args.out) if args.out
                else OUT_DIR / f"{slugify(args.text)}-{args.side}.svg")
    entry = write_label(args.text, icon, args.side, args, out_path)
    write_preview([entry], args, Path(out_path).resolve().with_suffix(".png"))


def run_drawer(args):
    render_drawer(
        args.name or slugify(args.primary),
        {"text": args.primary, "icon": args.icon, "icon_desc": args.icon_desc},
        {"text": args.secondary, "icon": args.secondary_icon,
         "icon_desc": args.secondary_icon_desc},
        args,
    )


def run_batch(args):
    data = json.loads(Path(args.file).read_text())
    drawers = data["drawers"] if isinstance(data, dict) else data
    if isinstance(data, dict) and data.get("drawer_width") and not args.drawer_width:
        args.drawer_width = data["drawer_width"]
    _apply_file_defaults(data, args, ("sheet_width", "sheet_height"))
    items = []
    for drawer in drawers:
        entries = render_drawer(drawer.get("name") or slugify(drawer["primary"]["text"]),
                                drawer["primary"], drawer.get("secondary"), args)
        if drawer.get("cut", True):
            items += entries
        else:
            print("  (already cut, kept off the sheets)")
    write_sheets(items, args, OUT_DIR / "sheets" / "sheet")


def run_bin(args):
    spec = {"text": args.text, "icon": args.icon, "icon_desc": args.icon_desc}
    name = args.name or slugify(args.text)
    print(f"bin {name}:")
    cells = [write_bin_label(spec, args, OUT_DIR / "bins" / f"{name}.svg")]
    write_bin_sheets(cells, args, OUT_DIR / "bin-sheets" / f"{name}-sheet")


def run_bins(args):
    data = json.loads(Path(args.file).read_text())
    specs = data["bins"] if isinstance(data, dict) else data
    _apply_file_defaults(data, args, ("bin_width", "bin_height", "sheet_width",
                                      "sheet_height", "sheet_margin", "gutter"))
    cells = []
    for spec in specs:
        name = spec.get("name") or slugify(spec["text"])
        print(f"bin {name}:")
        cell = write_bin_label(spec, args, OUT_DIR / "bins" / f"{name}.svg")
        if spec.get("cut", True):
            cells.append(cell)
        else:
            print("  (already cut, kept off the sheets)")
    write_bin_sheets(cells, args, OUT_DIR / "bin-sheets" / "sheet")


def run_icon(args):
    if args.icon_command == "list":
        catalog = icons.read_catalog()
        if not catalog:
            print("no icons yet")
        for slug, description in sorted(catalog.items()):
            meta = icons.load(slug)
            if not meta:
                state = "NOT TRACED"
            elif icons.stale_source(slug, meta):
                state = f"STALE (aspect {meta['aspect']:.2f})"
            else:
                state = f"cached (aspect {meta['aspect']:.2f})"
            print(f"  {slug:<20} {state:<24} {description}")
    elif args.icon_command == "gen":
        regen = "retrace" if args.retrace else True
        for slug in args.slugs:
            icons.ensure(slug, args.desc, regen=regen, quality=args.quality,
                         style=args.icon_style, max_pieces=args.max_pieces,
                         attempts=args.attempts, **trace_options(args))
            print(f"  wrote icons/{slug}.svg")
    elif args.icon_command == "import":
        meta = icons.import_file(args.slug, args.file, args.desc, **trace_options(args))
        print(f"  wrote icons/{args.slug}.svg  (aspect {meta['aspect']:.2f})")
    elif args.icon_command == "refresh":
        changed = [slug for slug in sorted(icons.read_catalog()) if icons.refresh(slug)]
        print(f"  retraced {len(changed)}" if changed else "  all icons up to date")
    elif args.icon_command == "sheet":
        run_icon_sheet(args)


def run_icon_sheet(args):
    cells = [(slug, icons.load(slug)) for slug in sorted(icons.read_catalog())]
    cells = [(slug, meta) for slug, meta in cells if meta]
    if not cells:
        raise SystemExit("no cached icons")
    columns, cell_px, padding_px = 6, 140, 10
    rows = (len(cells) + columns - 1) // columns
    parts = []
    for index, (slug, meta) in enumerate(cells):
        cell_x = (index % columns) * cell_px
        cell_y = (index // columns) * cell_px
        box_height = cell_px - 2 * padding_px - 24
        box_width = cell_px - 2 * padding_px
        scale = min(box_height / 1000.0, box_width / (1000.0 * meta["aspect"]))
        width, height = 1000 * meta["aspect"] * scale, 1000 * scale
        origin_x = cell_x + (cell_px - width) / 2
        origin_y = cell_y + padding_px + (box_height - height) / 2
        parts.append(
            f'<g transform="translate({origin_x:.2f},{origin_y:.2f}) '
            f'scale({scale:.5f})">'
            f'<path d="{meta["path"]}"/></g>'
            f'<text x="{cell_x + cell_px / 2:.1f}" y="{cell_y + cell_px - 6:.1f}" '
            f'font-size="11" '
            f'text-anchor="middle" font-family="monospace">{slug}</text>'
        )
    out_path = ROOT / "icons" / "_sheet.svg"
    out_path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{columns * cell_px}" '
        f'height="{rows * cell_px}" '
        f'viewBox="0 0 {columns * cell_px} {rows * cell_px}">'
        f'<rect width="100%" height="100%" fill="#fff"/>'
        f'<g fill="#000" fill-rule="nonzero">{"".join(parts)}</g></svg>\n'
    )
    print(f"wrote {relative_to_root(out_path)}")


def main():
    parser = argparse.ArgumentParser(
        prog="toolbox_labels.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    label_parser = subcommands.add_parser("label", help="render a single label")
    label_parser.add_argument("text")
    label_parser.add_argument("--icon", help="icon slug (cached or generated on demand)")
    label_parser.add_argument("--icon-desc", help="what the icon should depict")
    label_parser.add_argument("--side", choices=["primary", "secondary"],
                              default="primary")
    label_parser.add_argument("--out")
    add_style_arguments(label_parser)
    label_parser.set_defaults(func=run_label)

    drawer_parser = subcommands.add_parser(
        "drawer", help="render a drawer's primary (+ optional secondary)"
    )
    drawer_parser.add_argument("primary")
    drawer_parser.add_argument("--icon")
    drawer_parser.add_argument("--icon-desc")
    drawer_parser.add_argument("--secondary")
    drawer_parser.add_argument("--secondary-icon")
    drawer_parser.add_argument("--secondary-icon-desc")
    drawer_parser.add_argument("--name",
                               help="output folder name (default: slug of primary text)")
    add_style_arguments(drawer_parser)
    drawer_parser.set_defaults(func=run_drawer)

    batch_parser = subcommands.add_parser(
        "batch", help="render every drawer described in a JSON file"
    )
    batch_parser.add_argument("file")
    add_style_arguments(batch_parser)
    add_sheet_arguments(batch_parser)
    batch_parser.set_defaults(func=run_batch)

    bin_parser = subcommands.add_parser(
        "bin", help="render one shelf-bin label (text stacked over icon)"
    )
    bin_parser.add_argument("text")
    bin_parser.add_argument("--icon")
    bin_parser.add_argument("--icon-desc")
    bin_parser.add_argument("--name", help="output file name (default: slug of text)")
    add_bin_arguments(bin_parser)
    bin_parser.set_defaults(func=run_bin)

    bins_parser = subcommands.add_parser(
        "bins", help="render every bin described in a JSON file"
    )
    bins_parser.add_argument("file")
    add_bin_arguments(bins_parser)
    bins_parser.set_defaults(func=run_bins)

    icon_parser = subcommands.add_parser("icon", help="manage the icon cache")
    icon_subcommands = icon_parser.add_subparsers(dest="icon_command", required=True)
    icon_subcommands.add_parser("list")

    generate_parser = icon_subcommands.add_parser("gen")
    generate_parser.add_argument("slugs", nargs="+")
    generate_parser.add_argument("--desc")
    generate_parser.add_argument("--retrace", action="store_true")
    generate_parser.add_argument("--quality", default="high",
                                 choices=["low", "medium", "high"])
    generate_parser.add_argument("--icon-style", default="solid",
                                 choices=sorted(icons.PROMPTS))
    generate_parser.add_argument("--threshold", type=int, default=128)
    generate_parser.add_argument("--turdsize", type=int, default=150)
    generate_parser.add_argument("--alphamax", type=float, default=1.0)
    generate_parser.add_argument("--opttolerance", type=float, default=0.2)
    generate_parser.add_argument("--invert", action="store_true")

    import_parser = icon_subcommands.add_parser(
        "import", help="trace a local image into the cache (no API call)"
    )
    import_parser.add_argument("slug")
    import_parser.add_argument("file")
    import_parser.add_argument("--desc")
    import_parser.add_argument("--invert", action="store_true",
                               help="source art is light-on-dark; flip it before tracing")
    import_parser.add_argument("--threshold", type=int, default=128)
    import_parser.add_argument("--turdsize", type=int, default=150)
    import_parser.add_argument("--alphamax", type=float, default=1.0)
    import_parser.add_argument("--opttolerance", type=float, default=0.2)

    icon_subcommands.add_parser("refresh",
                                help="retrace any imported icon whose source changed")
    icon_subcommands.add_parser("sheet", help="contact sheet of every cached icon")
    icon_parser.set_defaults(func=run_icon)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
