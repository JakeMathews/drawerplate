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

_SHARED_RULES = """
- Only two colors: pure solid black on a pure white background.
- No gray, no gradients, no shading, no texture, no drop shadow, no 3D, no perspective.
- No border, no frame, no circle or badge behind the subject. Plain white background.
- One single centered subject, viewed straight on, simple friendly cartoon style.
- Very bold and chunky. Every black shape and every white gap must be thick. No thin
  lines, no hairlines, no fine detail, no cross-hatching, no small dots, no small holes.
- Radically simplified so it reads instantly as a pictogram printed 3/4 inch tall.
- No text, no letters, no numbers, no watermark.
- Leave a small even white margin around the subject."""

_BIN_RULES = """
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
    + _SHARED_RULES,
    "outline": """Simple bold cartoon clip-art icon of {desc}.

Draw it as a heavy BLACK OUTLINE drawing with white interiors, like a thick-lined
coloring-book sticker. Every stroke must be extremely thick and uniform.

STRICT REQUIREMENTS:"""
    + _SHARED_RULES,
    "bin": """A two-color vinyl decal of {desc}.

Draw the subject as a PREDOMINANTLY SOLID BLACK MASS, with white shapes knocked out of
it to carry the detail. Do not draw a white subject with thin black outlines. The
silhouette should be accurate and specific to this exact object.

STRICT REQUIREMENTS:"""
    + _BIN_RULES,
}


def load_api_key(env_file=None):
    key = os.environ.get("OPENAI_KEY") or os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    env_file = Path(env_file) if env_file else ICON_DIR.parent / "openapi.env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            match = re.match(
                r"\s*(?:export\s+)?(OPENAI_KEY|OPENAI_API_KEY)\s*=\s*(.+)", line
            )
            if match:
                return match.group(2).strip().strip("'\"")
    raise SystemExit("No OPENAI_KEY found (set the env var or put it in openapi.env)")


def read_catalog():
    return json.loads(CATALOG.read_text()) if CATALOG.exists() else {}


def write_catalog(catalog):
    ICON_DIR.mkdir(exist_ok=True)
    CATALOG.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n")


def _request_image(description, api_key, quality, size, style):
    response = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-image-1",
            "prompt": PROMPTS[style].format(desc=description),
            "size": size,
            "quality": quality,
            "background": "opaque",
            "output_format": "png",
            "n": 1,
        },
        timeout=600,
    )
    if response.status_code != 200:
        raise SystemExit(
            f"OpenAI image request failed ({response.status_code}): {response.text[:500]}"
        )
    return base64.b64decode(response.json()["data"][0]["b64_json"])


def _binarize(png_bytes, threshold, invert=False):
    image = Image.open(BytesIO(png_bytes))
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        # Transparent pixels are background, which is black in an inverted source.
        background_color = (0, 0, 0, 255) if invert else (255,) * 4
        background = Image.new("RGBA", image.size, background_color)
        image = Image.alpha_composite(background, image)
    image = image.convert("L")
    if invert:
        image = ImageOps.invert(image)
    image = ImageOps.expand(image, border=max(8, image.width // 40), fill=255)
    return image.point(lambda level: 255 if level >= threshold else 0, "L").convert("1")


def _potrace(bitmap, turdsize, alphamax, opttolerance):
    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / "in.bmp"
        traced = Path(temp_dir) / "out.svg"
        bitmap.save(source)
        subprocess.run(
            [
                "potrace", "-b", "svg", "-o", str(traced),
                "--turdsize", str(turdsize),
                "--alphamax", str(alphamax),
                "--opttolerance", str(opttolerance),
                str(source),
            ],
            check=True,
            capture_output=True,
        )
        return traced.read_text()


def _flatten_potrace(svg_text):
    """Pull the path data out of potrace's SVG and bake in its <g> transform."""
    path_datas = re.findall(r'<path[^>]*\bd="([^"]+)"', svg_text)
    if not path_datas:
        raise SystemExit("potrace produced no outlines (image may be blank)")
    match = re.search(
        r"translate\(([-\d.eE]+)[ ,]([-\d.eE]+)\)\s*scale\(([-\d.eE]+)[ ,]([-\d.eE]+)\)",
        svg_text,
    )
    if match:
        translate_x, translate_y, scale_x, scale_y = (
            float(value) for value in match.groups()
        )
    else:
        translate_x, translate_y, scale_x, scale_y = 0.0, 0.0, 1.0, 1.0
    commands = []
    for path_data in path_datas:
        commands += svgpath.transform(
            svgpath.parse(path_data), scale_x, 0, 0, scale_y, translate_x, translate_y
        )
    return commands


def _normalize(commands):
    left, top, right, bottom = svgpath.bounding_box(commands)
    height = bottom - top
    if height <= 0:
        raise SystemExit("traced icon has zero height")
    scale = NORM_HEIGHT / height
    commands = svgpath.transform(
        commands, scale, 0, 0, scale, -left * scale, -top * scale
    )
    return commands, (right - left) / height


def vectorize(png_bytes, threshold=128, turdsize=150, alphamax=1.0, opttolerance=0.2,
              invert=False):
    bitmap = _binarize(png_bytes, threshold, invert)
    traced = _potrace(bitmap, turdsize, alphamax, opttolerance)
    commands, aspect = _normalize(_flatten_potrace(traced))
    return svgpath.serialize(commands), aspect


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def portable_source(path):
    """Store the source path relative to the repo or home, so caches stay shareable."""
    path = Path(path).expanduser().resolve()
    for base, prefix in ((ICON_DIR.parent, ""), (Path.home(), "~/")):
        try:
            return prefix + str(path.relative_to(base))
        except ValueError:
            pass
    return str(path)


def resolve_source(stored_path):
    path = Path(stored_path).expanduser()
    return path if path.is_absolute() else ICON_DIR.parent / path


def stale_source(slug, meta=None):
    """Return the source path if an imported icon's file has changed since tracing."""
    meta = meta or load(slug)
    if not meta or not meta.get("source"):
        return None
    source = resolve_source(meta["source"])
    if not source.exists():
        return None
    return source if _digest(source) != meta.get("source_sha256") else None


def icon_files(slug):
    return (ICON_DIR / f"{slug}.json", ICON_DIR / f"{slug}.png", ICON_DIR / f"{slug}.svg")


def load(slug):
    meta_path, _, _ = icon_files(slug)
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text())


def save(slug, description, png_bytes, path_data, aspect, trace_options, style,
         source=None, source_sha256=None):
    ICON_DIR.mkdir(exist_ok=True)
    meta_path, png_path, svg_path = icon_files(slug)
    if png_bytes is not None:
        png_path.write_bytes(png_bytes)
    record = {"slug": slug, "description": description, "style": style, "aspect": aspect,
              "trace": trace_options, "path": path_data}
    if source:
        record["source"] = source
        record["source_sha256"] = source_sha256
    meta_path.write_text(json.dumps(record, indent=2) + "\n")
    width = round(NORM_HEIGHT * aspect, 3)
    svg_path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} '
        f'{NORM_HEIGHT:.0f}" '
        f'width="{width}" height="{NORM_HEIGHT:.0f}">'
        f'<path fill="#000" fill-rule="nonzero" d="{path_data}"/></svg>\n'
    )
    return meta_path


def import_file(slug, source, description=None, **trace_options):
    """Trace a local image into the icon cache. No API call."""
    source = Path(source)
    if not source.exists():
        raise SystemExit(f"no such file: {source}")
    buffer = BytesIO()
    Image.open(source).save(buffer, "PNG")
    png_bytes = buffer.getvalue()

    path_data, aspect = vectorize(png_bytes, **trace_options)
    catalog = read_catalog()
    description = description or catalog.get(slug) or f"traced from {source.name}"
    save(slug, description, png_bytes, path_data, aspect, trace_options, "imported",
         source=portable_source(source), source_sha256=_digest(source))
    catalog[slug] = description
    write_catalog(catalog)
    return load(slug)


def refresh(slug, meta=None):
    """Retrace an imported icon if its source file changed. Returns new meta, or None.

    The stored trace options are reused rather than whatever the caller passed, so a
    plain `bins` run can't silently re-cut an icon at different settings.
    """
    meta = meta or load(slug)
    source = stale_source(slug, meta)
    if not source:
        return None
    print(f"  source changed, retracing '{slug}' from {source.name}")
    return import_file(slug, source, meta.get("description"), **meta.get("trace", {}))


def ensure(slug, description=None, regen=False, quality="high", size="1024x1024",
           style="solid", **trace_options):
    """Return icon metadata, generating and tracing it on a cache miss."""
    catalog = read_catalog()
    description = description or catalog.get(slug)
    existing = load(slug)

    if existing and not regen:
        return refresh(slug, existing) or existing
    if not description:
        raise SystemExit(f"Icon '{slug}' is not cached and has no description. "
                         f"Pass --icon-desc or add it to icons/catalog.json.")

    _, png_path, _ = icon_files(slug)
    if regen == "retrace" and png_path.exists():
        png_bytes = png_path.read_bytes()
    else:
        print(f"  generating icon '{slug}' ...")
        png_bytes = _request_image(description, load_api_key(), quality, size, style)

    path_data, aspect = vectorize(png_bytes, **trace_options)
    save(slug, description, png_bytes, path_data, aspect, trace_options, style)
    catalog[slug] = description
    write_catalog(catalog)
    return load(slug)
