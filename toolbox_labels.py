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


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "label"


def add_style_args(p):
    g = p.add_argument_group("sizing")
    g.add_argument("--label-height", type=float, default=0.75, metavar="IN")
    g.add_argument("--cap-height", type=float, default=0.5, metavar="IN",
                   help="height of a capital letter (default 0.5)")
    g.add_argument("--icon-height", type=float, default=0.75, metavar="IN")
    g.add_argument("--gap", type=float, default=0.12, metavar="IN",
                   help="space between icon and text (default 0.12)")
    g.add_argument("--pad", type=float, default=0.0, metavar="IN",
                   help="blank margin on the outer edges (default 0)")
    g.add_argument("--tracking", type=float, default=0.0, metavar="EM",
                   help="extra letter spacing in em (default 0)")
    g.add_argument("--max-width", type=float, default=None, metavar="IN",
                   help="shrink text if the label would exceed this width")
    g.add_argument("--font", default=str(labels.FONT_PATH))
    g.add_argument("--no-upper", action="store_true", help="keep text as typed")
    g.add_argument("--drawer-width", type=float, default=None, metavar="IN",
                   help="drawer front width; sizes the preview and warns on crowding")

    add_trace_args(p)


def add_bin_args(p):
    g = p.add_argument_group("sizing")
    g.add_argument("--bin-width", type=float, default=6.0, metavar="IN",
                   help="width of one label cell (default 6)")
    g.add_argument("--bin-height", type=float, default=4.0, metavar="IN",
                   help="height of one label cell (default 4)")
    g.add_argument("--cap-height", type=float, default=0.4, metavar="IN")
    g.add_argument("--icon-height", type=float, default=2.6, metavar="IN")
    g.add_argument("--gap", type=float, default=0.25, metavar="IN",
                   help="space between text and icon (default 0.25)")
    g.add_argument("--pad", type=float, default=0.25, metavar="IN",
                   help="keep-out margin inside the cell (default 0.25)")
    g.add_argument("--tracking", type=float, default=0.0, metavar="EM")
    g.add_argument("--font", default=str(labels.FONT_PATH))
    g.add_argument("--upper", action="store_true", help="uppercase the text")
    g.add_argument("--sheet-width", type=float, default=12.0, metavar="IN",
                   help="stock vinyl width to tile labels across (default 12)")
    add_trace_args(p, icon_style="outline")


def add_trace_args(p, icon_style="solid"):
    t = p.add_argument_group("icon tracing")
    t.add_argument("--threshold", type=int, default=128)
    t.add_argument("--turdsize", type=int, default=150,
                   help="drop traced specks/holes smaller than this area in source px "
                        "(default 150, about 0.01in on the finished label)")
    t.add_argument("--alphamax", type=float, default=1.0)
    t.add_argument("--opttolerance", type=float, default=0.2)
    t.add_argument("--invert", action="store_true",
                   help="source art is light-on-dark; flip it before tracing")
    t.add_argument("--quality", default="high", choices=["low", "medium", "high"])
    t.add_argument("--icon-style", default=icon_style, choices=sorted(icons.PROMPTS),
                   help="solid silhouette (weeds best) or heavy outline drawing")
    t.add_argument("--regen", action="store_true", help="regenerate cached icons")
    t.add_argument("--retrace", action="store_true",
                   help="re-vectorize cached PNGs without calling OpenAI")


def style_from(args):
    return dict(
        label_height_in=args.label_height,
        cap_height_in=args.cap_height,
        icon_height_in=args.icon_height,
        gap_in=args.gap,
        pad_in=args.pad,
        tracking_em=args.tracking,
        max_width_in=args.max_width,
        font_path=args.font,
    )


def trace_from(args):
    return dict(
        threshold=args.threshold,
        turdsize=args.turdsize,
        alphamax=args.alphamax,
        opttolerance=args.opttolerance,
        invert=args.invert,
    )


def resolve_icon(slug, desc, args):
    if not slug:
        return None
    regen = "retrace" if args.retrace else args.regen
    return icons.ensure(slug, desc, regen=regen, quality=args.quality,
                        style=args.icon_style, **trace_from(args))


def emit(text, icon, side, args, out_path):
    if not args.no_upper:
        text = text.upper()
    svg, paths, w, h = labels.build_label(text, icon=icon, side=side, **style_from(args))
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg)
    try:
        shown = out_path.relative_to(ROOT)
    except ValueError:
        shown = out_path
    print(f"  {side:<9} {w:6.3f} x {h:.3f} in  {text!r}  -> {shown}")
    return side, paths, w


def write_preview(entries, args, png_path):
    if not entries:
        return
    used = sum(w for _, _, w in entries)
    width = args.drawer_width or (used + 0.6)
    svg = labels.drawer_preview(entries, width, label_height_in=args.label_height)
    tmp = png_path.with_suffix(".preview.svg")
    tmp.write_text(svg)
    try:
        subprocess.run(["rsvg-convert", "-z", "3", str(tmp), "-o", str(png_path)],
                       check=True, capture_output=True)
        tmp.unlink()
        print(f"  preview   -> {png_path.relative_to(ROOT)}")
    except (FileNotFoundError, subprocess.CalledProcessError):
        print(f"  preview   -> {tmp.relative_to(ROOT)} (install librsvg for PNG)")
    if args.drawer_width and used + 0.45 > args.drawer_width:
        print(f"  WARNING: labels total {used:.2f}in, drawer is "
              f"{args.drawer_width:.2f}in — they will crowd or overlap")


def cmd_label(args):
    icon = resolve_icon(args.icon, args.icon_desc, args)
    out = Path(args.out) if args.out else OUT_DIR / f"{slugify(args.text)}-{args.side}.svg"
    entry = emit(args.text, icon, args.side, args, out)
    write_preview([entry], args, Path(out).resolve().with_suffix(".png"))


def render_drawer(name, primary, secondary, args):
    print(f"drawer {name}:")
    d = OUT_DIR / name
    entries = [emit(primary["text"],
                    resolve_icon(primary.get("icon"), primary.get("icon_desc"), args),
                    "primary", args, d / "primary.svg")]
    if secondary and secondary.get("text"):
        entries.append(emit(secondary["text"],
                            resolve_icon(secondary.get("icon"),
                                         secondary.get("icon_desc"), args),
                            "secondary", args, d / "secondary.svg"))
    write_preview(entries, args, d / "preview.png")


def cmd_drawer(args):
    render_drawer(
        args.name or slugify(args.primary),
        {"text": args.primary, "icon": args.icon, "icon_desc": args.icon_desc},
        {"text": args.secondary, "icon": args.secondary_icon,
         "icon_desc": args.secondary_icon_desc},
        args,
    )


def cmd_batch(args):
    data = json.loads(Path(args.file).read_text())
    drawers = data["drawers"] if isinstance(data, dict) else data
    if isinstance(data, dict) and data.get("drawer_width") and not args.drawer_width:
        args.drawer_width = data["drawer_width"]
    for d in drawers:
        render_drawer(d.get("name") or slugify(d["primary"]["text"]),
                      d["primary"], d.get("secondary"), args)


def bin_style_from(args):
    return dict(
        width_in=args.bin_width,
        height_in=args.bin_height,
        cap_height_in=args.cap_height,
        icon_height_in=args.icon_height,
        gap_in=args.gap,
        pad_in=args.pad,
        tracking_em=args.tracking,
        font_path=args.font,
    )


def emit_bin(spec, args, out_path):
    text = spec["text"].upper() if args.upper else spec["text"]
    icon = resolve_icon(spec.get("icon"), spec.get("icon_desc"), args)
    svg, paths, w, h = labels.build_bin_label(text, icon=icon, **bin_style_from(args))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg)
    print(f"  bin       {w:6.3f} x {h:.3f} in  {text!r}  -> {out_path.relative_to(ROOT)}")
    return paths


def write_bin_sheets(cells, args, stem):
    cols = max(1, int(args.sheet_width // args.bin_width))
    for i in range(0, len(cells), cols):
        chunk = cells[i:i + cols]
        n = i // cols + 1
        sheet = stem.parent / f"{stem.name}-{n:02d}.svg"
        sheet.write_text(
            labels.tile_sheet(chunk, args.bin_width, args.bin_height, cols)
        )
        print(f"  sheet     -> {sheet.relative_to(ROOT)}")
        png = sheet.with_suffix(".png")
        tmp = sheet.with_suffix(".preview.svg")
        tmp.write_text(
            labels.tile_sheet(chunk, args.bin_width, args.bin_height, cols, invert=True)
        )
        try:
            subprocess.run(["rsvg-convert", "-z", "2", str(tmp), "-o", str(png)],
                           check=True, capture_output=True)
            tmp.unlink()
            print(f"  preview   -> {png.relative_to(ROOT)}")
        except (FileNotFoundError, subprocess.CalledProcessError):
            print(f"  preview   -> {tmp.relative_to(ROOT)} (install librsvg for PNG)")


def cmd_bin(args):
    spec = {"text": args.text, "icon": args.icon, "icon_desc": args.icon_desc}
    name = args.name or slugify(args.text)
    print(f"bin {name}:")
    cells = [emit_bin(spec, args, OUT_DIR / "bins" / f"{name}.svg")]
    write_bin_sheets(cells, args, OUT_DIR / "bins" / f"{name}-sheet")


def cmd_bins(args):
    data = json.loads(Path(args.file).read_text())
    specs = data["bins"] if isinstance(data, dict) else data
    if isinstance(data, dict):
        for key in ("bin_width", "bin_height", "sheet_width"):
            if data.get(key):
                setattr(args, key, data[key])
    cells = []
    for spec in specs:
        name = spec.get("name") or slugify(spec["text"])
        print(f"bin {name}:")
        cells.append(emit_bin(spec, args, OUT_DIR / "bins" / f"{name}.svg"))
    write_bin_sheets(cells, args, OUT_DIR / "bins" / "sheet")


def cmd_icon(args):
    if args.icon_cmd == "list":
        cat = icons.read_catalog()
        if not cat:
            print("no icons yet")
        for slug, desc in sorted(cat.items()):
            meta = icons.load(slug)
            if not meta:
                state = "NOT TRACED"
            elif icons.stale_source(slug, meta):
                state = f"STALE (aspect {meta['aspect']:.2f})"
            else:
                state = f"cached (aspect {meta['aspect']:.2f})"
            print(f"  {slug:<20} {state:<24} {desc}")
    elif args.icon_cmd == "gen":
        regen = "retrace" if args.retrace else True
        for slug in args.slugs:
            icons.ensure(slug, args.desc, regen=regen, quality=args.quality,
                         style=args.icon_style, **trace_from(args))
            print(f"  wrote icons/{slug}.svg")
    elif args.icon_cmd == "import":
        meta = icons.import_file(args.slug, args.file, args.desc, **trace_from(args))
        print(f"  wrote icons/{args.slug}.svg  (aspect {meta['aspect']:.2f})")
    elif args.icon_cmd == "refresh":
        changed = [s for s in sorted(icons.read_catalog()) if icons.refresh(s)]
        print(f"  retraced {len(changed)}" if changed else "  all icons up to date")
    elif args.icon_cmd == "sheet":
        cmd_icon_sheet(args)


def cmd_icon_sheet(args):
    cat = sorted(icons.read_catalog())
    cells = [(s, icons.load(s)) for s in cat]
    cells = [(s, m) for s, m in cells if m]
    if not cells:
        raise SystemExit("no cached icons")
    cols, cell, pad = 6, 140, 10
    rows = (len(cells) + cols - 1) // cols
    parts = []
    for i, (slug, meta) in enumerate(cells):
        cx, cy = (i % cols) * cell, (i // cols) * cell
        box_h, box_w = cell - 2 * pad - 24, cell - 2 * pad
        s = min(box_h / 1000.0, box_w / (1000.0 * meta["aspect"]))
        w, h = 1000 * meta["aspect"] * s, 1000 * s
        ox, oy = cx + (cell - w) / 2, cy + pad + (box_h - h) / 2
        parts.append(
            f'<g transform="translate({ox:.2f},{oy:.2f}) scale({s:.5f})">'
            f'<path d="{meta["path"]}"/></g>'
            f'<text x="{cx + cell / 2:.1f}" y="{cy + cell - 6:.1f}" font-size="11" '
            f'text-anchor="middle" font-family="monospace">{slug}</text>'
        )
    out = ROOT / "icons" / "_sheet.svg"
    out.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{cols * cell}" '
        f'height="{rows * cell}" viewBox="0 0 {cols * cell} {rows * cell}">'
        f'<rect width="100%" height="100%" fill="#fff"/>'
        f'<g fill="#000" fill-rule="nonzero">{"".join(parts)}</g></svg>\n'
    )
    print(f"wrote {out.relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser(prog="toolbox_labels.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("label", help="render a single label")
    p.add_argument("text")
    p.add_argument("--icon", help="icon slug (cached or generated on demand)")
    p.add_argument("--icon-desc", help="what the icon should depict")
    p.add_argument("--side", choices=["primary", "secondary"], default="primary")
    p.add_argument("--out")
    add_style_args(p)
    p.set_defaults(func=cmd_label)

    p = sub.add_parser("drawer", help="render a drawer's primary (+ optional secondary)")
    p.add_argument("primary")
    p.add_argument("--icon")
    p.add_argument("--icon-desc")
    p.add_argument("--secondary")
    p.add_argument("--secondary-icon")
    p.add_argument("--secondary-icon-desc")
    p.add_argument("--name", help="output folder name (default: slug of primary text)")
    add_style_args(p)
    p.set_defaults(func=cmd_drawer)

    p = sub.add_parser("batch", help="render every drawer described in a JSON file")
    p.add_argument("file")
    add_style_args(p)
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("bin", help="render one shelf-bin label (text stacked over icon)")
    p.add_argument("text")
    p.add_argument("--icon")
    p.add_argument("--icon-desc")
    p.add_argument("--name", help="output file name (default: slug of text)")
    add_bin_args(p)
    p.set_defaults(func=cmd_bin)

    p = sub.add_parser("bins", help="render every bin described in a JSON file")
    p.add_argument("file")
    add_bin_args(p)
    p.set_defaults(func=cmd_bins)

    p = sub.add_parser("icon", help="manage the icon cache")
    isub = p.add_subparsers(dest="icon_cmd", required=True)
    ip = isub.add_parser("list")
    ip = isub.add_parser("gen")
    ip.add_argument("slugs", nargs="+")
    ip.add_argument("--desc")
    ip.add_argument("--retrace", action="store_true")
    ip.add_argument("--quality", default="high", choices=["low", "medium", "high"])
    ip.add_argument("--icon-style", default="solid", choices=sorted(icons.PROMPTS))
    ip.add_argument("--threshold", type=int, default=128)
    ip.add_argument("--turdsize", type=int, default=150)
    ip.add_argument("--alphamax", type=float, default=1.0)
    ip.add_argument("--opttolerance", type=float, default=0.2)
    ip.add_argument("--invert", action="store_true")

    ip = isub.add_parser("import", help="trace a local image into the cache (no API call)")
    ip.add_argument("slug")
    ip.add_argument("file")
    ip.add_argument("--desc")
    ip.add_argument("--invert", action="store_true",
                    help="source art is light-on-dark; flip it before tracing")
    ip.add_argument("--threshold", type=int, default=128)
    ip.add_argument("--turdsize", type=int, default=150)
    ip.add_argument("--alphamax", type=float, default=1.0)
    ip.add_argument("--opttolerance", type=float, default=0.2)

    isub.add_parser("refresh", help="retrace any imported icon whose source changed")
    isub.add_parser("sheet", help="contact sheet of every cached icon")
    p.set_defaults(func=cmd_icon)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
