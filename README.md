# drawerplate

Generates exact-size SVG labels for tool chest drawers, ready to import into
**Easy Cut Studio 6** and cut on a vinyl plotter.

Each label is **0.75 in tall** and carries a cartoon pictogram plus text set in
**JetBrains Mono Bold**. The icons are generated with OpenAI, vectorized with
`potrace`, and cached — so drawing a new icon costs an API call once, and every
label after that renders offline in milliseconds.

```
▮ SOCKETS                                              3/8 DRIVE ▮
└ primary: left justified, icon prefix    secondary: right justified, icon suffix ┘
```

## Why the output is safe to cut

- **Text is converted to outlines.** No font is referenced in the SVG, so Easy Cut
  Studio can't substitute a different face or reflow the metrics.
- **Physically sized.** The SVG carries `width="3.3933in" height="0.7500in"` with a
  matching 96 dpi `viewBox`. Verified by rendering at 300 dpi and measuring: the
  label comes out 0.750 in tall to the pixel.
- **Transforms are baked flat.** Every path is absolute `M`/`L`/`C`/`Z` in the
  label's own coordinate space — no nested `<g transform>` for the importer to
  mishandle.
- **Sub-weedable detail is dropped.** Anything smaller than roughly 0.01 in of
  finished area is discarded during tracing, because you couldn't weed it anyway.

## Setup

Requires Python 3.10+, [`potrace`](https://potrace.sourceforge.net/), and
JetBrains Mono Bold installed at `~/Library/Fonts/JetBrainsMono-Bold.ttf`.
`librsvg` is optional and only used to rasterize previews.

```sh
brew install potrace librsvg

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp openapi.env.example openapi.env   # then paste in your real key
```

`./label` is a thin wrapper that runs the tool with the project venv, so there is
nothing to activate.

## Usage

### One drawer

```sh
./label drawer "SOCKETS" --icon socket \
        --secondary "3/8 DRIVE" --secondary-icon ratchet \
        --drawer-width 22
```

Writes `out/sockets/primary.svg`, `out/sockets/secondary.svg`, and a
`preview.png` mocking both up **white on black** at true size — which is what the
finished drawer actually looks like. Pass `--drawer-width` and you also get a
warning when the two labels would crowd each other.

Prefer one label per drawer. The secondary is optional; skip `--secondary`
entirely and you just get `primary.svg`.

### A whole toolbox

```sh
./label batch drawers.json
```

See [`drawers.example.json`](drawers.example.json). `drawer_width` applies to
every drawer unless overridden on the command line, and `name` sets the output
folder:

```json
{
  "drawer_width": 22.0,
  "drawers": [
    {
      "name": "01-sockets",
      "primary": { "text": "SOCKETS", "icon": "socket",
                   "icon_desc": "a hex socket standing upright, opening toward the viewer" },
      "secondary": { "text": "3/8 DRIVE", "icon": "ratchet" }
    }
  ]
}
```

`icon_desc` is only read the first time a slug is generated; afterwards the slug
resolves straight from the cache. Descriptions are remembered in
`icons/catalog.json`, so later drawers can reference `"icon": "socket"` alone.

### A single loose label

```sh
./label label "SHOP RAGS" --icon rag \
        --icon-desc "a folded shop rag" --out out/rags.svg
```

## Icons

```sh
./label icon list                     # what's cached, and each icon's aspect ratio
./label icon sheet                    # contact sheet of every icon -> icons/_sheet.svg
./label icon gen socket --desc "a hex socket standing upright"
./label icon gen socket --retrace     # re-vectorize the cached PNG, no API call
```

Icons default to `--icon-style solid`: a filled black silhouette, like a traffic
sign glyph. That is deliberate. The alternative, `--icon-style outline`, produces
a heavy coloring-book line drawing that looks great on screen but leaves narrow
white channels that are miserable to weed at 0.75 in.

Because the labels are white vinyl on a black chest, black in the SVG is the
vinyl that stays and white is what gets weeded away. Solid shapes therefore read
as bold white pictograms on the drawer.

Icon generation is the only part that costs money and the only part that is
non-deterministic. When one comes out wrong, rerun `icon gen <slug>` with a
sharper description — every label using that slug picks up the new art on the
next render. Review the batch with `./label icon sheet` before cutting.

Cached art lives in `icons/`:

| file | purpose |
| --- | --- |
| `<slug>.png` | raw generation, kept so `--retrace` never re-bills you |
| `<slug>.svg` | traced outline, for eyeballing |
| `<slug>.json` | normalized path + aspect ratio, what the renderer actually reads |
| `catalog.json` | slug → description |

## Tuning

| flag | default | what it does |
| --- | --- | --- |
| `--cap-height` | `0.5in` | height of a capital letter |
| `--icon-height` | `0.75in` | icon height |
| `--label-height` | `0.75in` | canvas height, i.e. usable drawer height |
| `--gap` | `0.12in` | space between icon and text |
| `--pad` | `0` | blank margin on the outer edges |
| `--tracking` | `0` | extra letter spacing, in em |
| `--max-width` | — | shrink the text until the label fits this width |
| `--no-upper` | — | keep text as typed instead of uppercasing |
| `--turdsize` | `150` | drop traced specks/holes below this source-pixel area |
| `--threshold` | `128` | black/white cutoff when binarizing a generated icon |

Cap height is taken from the font's metrics, not from each string's bounding box,
so every label in a set shares one baseline and one letter size. Round letters
like `O` and `S` overshoot the cap line slightly — that's correct typography, not
a bug.

Text is uppercased by default. `--no-upper` works, but lowercase descenders can
drop past the 0.75 in canvas at the default cap height; lower `--cap-height` to
about `0.38` if you want mixed case.

## Layout

```
primary:    [ pad ][ icon ][ gap ][ text ][ pad ]
secondary:  [ pad ][ text ][ gap ][ icon ][ pad ]
```

Width is whatever the content needs; height is always the label height. Content
is trimmed to the ink, so `--pad 0` gives a label with no dead space at the ends.

## Repo layout

| file | role |
| --- | --- |
| `label` | wrapper that runs the CLI in the venv |
| `toolbox_labels.py` | CLI: `label`, `drawer`, `batch`, `icon` |
| `labels.py` | text→outline layout, exact-inch SVG, drawer preview |
| `icons.py` | OpenAI generation → threshold → potrace → normalized cached path |
| `svgpath.py` | path parsing, affine transforms, exact Bézier bounding boxes |

## License

MIT — see [LICENSE](LICENSE). This covers the code.

The icons in `icons/` are generated with OpenAI's image model. OpenAI assigns
output ownership to the generating user and permits commercial use, so they are
free to publish and cut. Be aware, though, that purely AI-generated images
likely aren't copyrightable in the first place — so treat the icons as
effectively public domain rather than as MIT-licensed work you control. The
cached `.png` files carry C2PA provenance metadata identifying them as
AI-generated; the traced `.svg` files do not, since the paths are rebuilt from
scratch.
