"""Icon pipeline: generate a bold monochrome pictogram with OpenAI, vectorize with potrace.

Cached icons are stored normalized: the path is expressed in a coordinate space
1000 units tall with the ink box anchored at (0, 0), so a label only has to scale.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageOps

import svgpath

ICON_DIR = Path(__file__).resolve().parent / "icons"
CATALOG = ICON_DIR / "catalog.json"
NORM_HEIGHT = 1000.0

_COMMON = """
- Only two colors: pure solid black on a pure white background.
- No gray, no gradients, no shading, no texture, no drop shadow, no 3D, no perspective.
- No border, no frame, no circle or badge behind the subject. Plain white background.
- One single centered subject, viewed straight on, simple friendly cartoon style.
- Very bold and chunky. Every black shape and every white gap must be thick. No thin
  lines, no hairlines, no fine detail, no cross-hatching, no small dots, no small holes.
- Radically simplified so it reads instantly as a pictogram printed 3/4 inch tall.
- No text, no letters, no numbers, no watermark.
- Leave a small even white margin around the subject."""

_BIN_COMMON = """
- Only two colors: pure solid black on a pure white background.
- No gray, no gradients, no shading, no texture, no drop shadow, no 3D.
- No border, no frame, no circle or badge behind the subject. Plain white background.
- One single centered subject.
- The finished art is printed 3 inches tall, so it should carry real detail: draw the
  parts that identify the object, not a generic outline. Keep every black shape and
  every white gap at least as thick as 1/50th of the subject's height, so it survives
  being weeded out of cut vinyl by hand.
- No text, no letters, no numbers, no watermark.
- Leave a small even white margin around the subject."""

PROMPTS = {
    "solid": """Simple bold cartoon clip-art pictogram of {desc}.

Draw it as a SOLID FILLED BLACK SILHOUETTE, like a traffic sign symbol or a Material
Design glyph. The subject is one connected solid black mass. Use only a few thick white
cut-out gaps inside it to suggest the most important details. Do not draw it as an
outline drawing; do not leave the inside of the subject white.

STRICT REQUIREMENTS:"""
    + _COMMON,
    "outline": """Simple bold cartoon clip-art icon of {desc}.

Draw it as a heavy BLACK OUTLINE drawing with white interiors, like a thick-lined
coloring-book sticker. Every stroke must be extremely thick and uniform.

STRICT REQUIREMENTS:"""
    + _COMMON,
    "bin": """A two-color vinyl decal of {desc}.

Draw the subject as a PREDOMINANTLY SOLID BLACK MASS, with white shapes knocked out of
it to carry the detail. Do not draw a white subject with thin black outlines. The
silhouette should be accurate and specific to this exact object.

STRICT REQUIREMENTS:"""
    + _BIN_COMMON,
}


def load_api_key(env_file=None):
    key = os.environ.get("OPENAI_KEY") or os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    env_file = Path(env_file) if env_file else ICON_DIR.parent / "openapi.env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            m = re.match(r"\s*(?:export\s+)?(OPENAI_KEY|OPENAI_API_KEY)\s*=\s*(.+)", line)
            if m:
                return m.group(2).strip().strip("'\"")
    raise SystemExit("No OPENAI_KEY found (set the env var or put it in openapi.env)")


def read_catalog():
    return json.loads(CATALOG.read_text()) if CATALOG.exists() else {}


def write_catalog(cat):
    ICON_DIR.mkdir(exist_ok=True)
    CATALOG.write_text(json.dumps(cat, indent=2, sort_keys=True) + "\n")


def _request_image(desc, api_key, quality, size, style):
    r = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": "gpt-image-1",
            "prompt": PROMPTS[style].format(desc=desc),
            "size": size,
            "quality": quality,
            "background": "opaque",
            "output_format": "png",
            "n": 1,
        },
        timeout=600,
    )
    if r.status_code != 200:
        raise SystemExit(f"OpenAI image request failed ({r.status_code}): {r.text[:500]}")
    return base64.b64decode(r.json()["data"][0]["b64_json"])


def _binarize(png_bytes, threshold, invert=False):
    im = Image.open(BytesIO(png_bytes))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        # Transparent pixels are background, which is black in an inverted source.
        bg = Image.new("RGBA", im.size, (0, 0, 0, 255) if invert else (255,) * 4)
        im = Image.alpha_composite(bg, im)
    im = im.convert("L")
    if invert:
        im = ImageOps.invert(im)
    im = ImageOps.expand(im, border=max(8, im.width // 40), fill=255)
    return im.point(lambda p: 255 if p >= threshold else 0, "L").convert("1")


def _potrace(bw, turdsize, alphamax, opttolerance):
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "in.bmp", Path(td) / "out.svg"
        bw.save(src)
        subprocess.run(
            [
                "potrace", "-b", "svg", "-o", str(dst),
                "--turdsize", str(turdsize),
                "--alphamax", str(alphamax),
                "--opttolerance", str(opttolerance),
                str(src),
            ],
            check=True,
            capture_output=True,
        )
        return dst.read_text()


def _flatten_potrace(svg_text):
    """Pull the path data out of potrace's SVG and bake in its <g> transform."""
    ds = re.findall(r'<path[^>]*\bd="([^"]+)"', svg_text)
    if not ds:
        raise SystemExit("potrace produced no outlines (image may be blank)")
    m = re.search(
        r"translate\(([-\d.eE]+)[ ,]([-\d.eE]+)\)\s*scale\(([-\d.eE]+)[ ,]([-\d.eE]+)\)",
        svg_text,
    )
    tx, ty, sx, sy = (float(g) for g in m.groups()) if m else (0.0, 0.0, 1.0, 1.0)
    cmds = []
    for d in ds:
        cmds += svgpath.transform(svgpath.parse(d), sx, 0, 0, sy, tx, ty)
    return cmds


def _normalize(cmds):
    x0, y0, x1, y1 = svgpath.bbox(cmds)
    h = y1 - y0
    if h <= 0:
        raise SystemExit("traced icon has zero height")
    s = NORM_HEIGHT / h
    cmds = svgpath.transform(cmds, s, 0, 0, s, -x0 * s, -y0 * s)
    return cmds, (x1 - x0) / h


def vectorize(png_bytes, threshold=128, turdsize=150, alphamax=1.0, opttolerance=0.2,
              invert=False):
    bw = _binarize(png_bytes, threshold, invert)
    cmds, aspect = _normalize(_flatten_potrace(_potrace(bw, turdsize, alphamax, opttolerance)))
    return svgpath.serialize(cmds), aspect


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def portable_source(p):
    """Store the source path relative to the repo or home, so caches stay shareable."""
    p = Path(p).expanduser().resolve()
    for base, prefix in ((ICON_DIR.parent, ""), (Path.home(), "~/")):
        try:
            return prefix + str(p.relative_to(base))
        except ValueError:
            pass
    return str(p)


def resolve_source(s):
    p = Path(s).expanduser()
    return p if p.is_absolute() else ICON_DIR.parent / p


def stale_source(slug, meta=None):
    """Return the source path if an imported icon's file has changed since tracing."""
    meta = meta or load(slug)
    if not meta or not meta.get("source"):
        return None
    src = resolve_source(meta["source"])
    if not src.exists():
        return None
    return src if _digest(src) != meta.get("source_sha256") else None


def icon_files(slug):
    return (ICON_DIR / f"{slug}.json", ICON_DIR / f"{slug}.png", ICON_DIR / f"{slug}.svg")


def load(slug):
    meta, _, _ = icon_files(slug)
    if not meta.exists():
        return None
    return json.loads(meta.read_text())


def save(slug, desc, png_bytes, path_d, aspect, trace_opts, style,
         source=None, source_sha256=None):
    ICON_DIR.mkdir(exist_ok=True)
    meta, png, svg = icon_files(slug)
    if png_bytes is not None:
        png.write_bytes(png_bytes)
    record = {"slug": slug, "description": desc, "style": style, "aspect": aspect,
              "trace": trace_opts, "path": path_d}
    if source:
        record["source"] = source
        record["source_sha256"] = source_sha256
    meta.write_text(json.dumps(record, indent=2) + "\n")
    w = round(NORM_HEIGHT * aspect, 3)
    svg.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {NORM_HEIGHT:.0f}" '
        f'width="{w}" height="{NORM_HEIGHT:.0f}">'
        f'<path fill="#000" fill-rule="nonzero" d="{path_d}"/></svg>\n'
    )
    return meta


def import_file(slug, src, desc=None, **trace):
    """Trace a local image into the icon cache. No API call."""
    src = Path(src)
    if not src.exists():
        raise SystemExit(f"no such file: {src}")
    buf = BytesIO()
    Image.open(src).save(buf, "PNG")
    png_bytes = buf.getvalue()

    path_d, aspect = vectorize(png_bytes, **trace)
    cat = read_catalog()
    desc = desc or cat.get(slug) or f"traced from {src.name}"
    save(slug, desc, png_bytes, path_d, aspect, trace, "imported",
         source=portable_source(src), source_sha256=_digest(src))
    cat[slug] = desc
    write_catalog(cat)
    return load(slug)


def refresh(slug, meta=None):
    """Retrace an imported icon if its source file changed. Returns new meta, or None.

    The stored trace options are reused rather than whatever the caller passed, so a
    plain `bins` run can't silently re-cut an icon at different settings.
    """
    meta = meta or load(slug)
    src = stale_source(slug, meta)
    if not src:
        return None
    print(f"  source changed, retracing '{slug}' from {src.name}")
    return import_file(slug, src, meta.get("description"), **meta.get("trace", {}))


def ensure(slug, desc=None, regen=False, quality="high", size="1024x1024",
           style="solid", **trace):
    """Return icon metadata, generating and tracing it on a cache miss."""
    cat = read_catalog()
    desc = desc or cat.get(slug)
    existing = load(slug)

    if existing and not regen:
        return refresh(slug, existing) or existing
    if not desc:
        raise SystemExit(f"Icon '{slug}' is not cached and has no description. "
                         f"Pass --icon-desc or add it to icons/catalog.json.")

    _, png_path, _ = icon_files(slug)
    if regen == "retrace" and png_path.exists():
        png_bytes = png_path.read_bytes()
    else:
        print(f"  generating icon '{slug}' ...")
        png_bytes = _request_image(desc, load_api_key(), quality, size, style)

    path_d, aspect = vectorize(png_bytes, **trace)
    save(slug, desc, png_bytes, path_d, aspect, trace, style)
    cat[slug] = desc
    write_catalog(cat)
    return load(slug)
