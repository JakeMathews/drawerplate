"""Icon pipeline: generate a bold monochrome pictogram with OpenAI, vectorize with potrace.

Cached icons are stored normalized: the path is expressed in a coordinate space
1000 units tall with the ink box anchored at (0, 0), so a label only has to scale.
"""

import base64
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


def _binarize(png_bytes, threshold):
    im = Image.open(BytesIO(png_bytes)).convert("L")
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


def vectorize(png_bytes, threshold=128, turdsize=150, alphamax=1.0, opttolerance=0.2):
    bw = _binarize(png_bytes, threshold)
    cmds, aspect = _normalize(_flatten_potrace(_potrace(bw, turdsize, alphamax, opttolerance)))
    return svgpath.serialize(cmds), aspect


def icon_files(slug):
    return (ICON_DIR / f"{slug}.json", ICON_DIR / f"{slug}.png", ICON_DIR / f"{slug}.svg")


def load(slug):
    meta, _, _ = icon_files(slug)
    if not meta.exists():
        return None
    return json.loads(meta.read_text())


def save(slug, desc, png_bytes, path_d, aspect, trace_opts, style):
    ICON_DIR.mkdir(exist_ok=True)
    meta, png, svg = icon_files(slug)
    if png_bytes is not None:
        png.write_bytes(png_bytes)
    meta.write_text(
        json.dumps(
            {"slug": slug, "description": desc, "style": style, "aspect": aspect,
             "trace": trace_opts, "path": path_d},
            indent=2,
        )
        + "\n"
    )
    w = round(NORM_HEIGHT * aspect, 3)
    svg.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {NORM_HEIGHT:.0f}" '
        f'width="{w}" height="{NORM_HEIGHT:.0f}">'
        f'<path fill="#000" fill-rule="nonzero" d="{path_d}"/></svg>\n'
    )
    return meta


def ensure(slug, desc=None, regen=False, quality="high", size="1024x1024",
           style="solid", **trace):
    """Return icon metadata, generating and tracing it on a cache miss."""
    cat = read_catalog()
    desc = desc or cat.get(slug)
    existing = load(slug)

    if existing and not regen:
        return existing
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
