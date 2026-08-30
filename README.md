# drawerplate

Generates exact-size SVG labels for tool chest drawers, ready to import into
**Easy Cut Studio 6** and cut on a vinyl plotter.

Drawer labels are **0.75 in tall**; shelf-bin labels are a **6 x 4 in** cell with
the text stacked over the icon. Every label carries a pictogram plus text set in
**JetBrains Mono Bold**. The icons are generated with OpenAI, vectorized with
`potrace`, and cached — so drawing a new icon costs an API call once, and every
label after that renders offline in milliseconds.

```
╭─────────────╮                                      ╭──────────────╮
│ ▮ SOCKETS   │                                      │  3/8 DRIVE ▮ │
╰─────────────╯                                      ╰──────────────╯
 primary: left justified, icon prefix    secondary: right justified, icon suffix
```

Each drawer label is ringed by a 1 px rounded frame held 5 px clear of the content, so
the label reads as a plate and can be weeded as a positive or used as a stencil. Icon
and cap height are equal and sized to whatever the frame leaves.

## Why the output is safe to cut

- **Text is converted to outlines.** No font is referenced in the SVG, so Easy Cut
  Studio can't substitute a different face or reflow the metrics.
- **Physically sized.** The SVG carries `width="4.1383in" height="0.7500in"` with a
  matching 96 dpi `viewBox`. Verified by rendering at 1200 dpi and measuring: the
  label comes out 0.750 in tall to the pixel, and the frame 0.010 in wide.
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

### Shelf bins

HDX-style bins on a shelf want a different shape: one big label per bin, text
stacked over a large icon, centered in a fixed cell rather than trimmed to the
ink. `bin` renders exactly that.

```sh
./label bin "Honda Rebel 500" --icon rebel500 \
        --icon-desc "a Honda Rebel 500 cruiser motorcycle seen from the side, facing left"
```

The cell defaults to **6 x 4 in**, and labels are tiled onto **12 in** sheets —
two across — matching stock vinyl width. Writes `out/bins/<name>.svg` for each
label plus `sheet-NN.svg` (what you cut) and `sheet-NN.png` (white-on-black
preview).

```sh
./label bins bins.json
```

See [`bins.example.json`](bins.example.json). Unlike drawer labels, bins keep
the text as typed — `Honda Rebel 500`, not `HONDA REBEL 500` — since a bin label
reads more like a title than a stencil. Pass `--upper` if you want otherwise.

Content is centered in the cell in both directions, so a shelf of bins lines up
without measuring anything on import. If the text is too wide it shrinks to fit;
if the stack is taller than the cell you get an error rather than a clipped cut.

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
./label icon import xsr900 ~/art.png --invert   # trace your own art, no API call
```

`icon import` traces a local image into the cache, so art you already have never
costs a generation. Two knobs matter:

- **`--invert`** — potrace cuts the *black* regions, so the ink you want must be
  black going in. Pass `--invert` when the source is light-on-dark. Which way
  round a given image wants is not always obvious: art with a light halo around
  the subject often traces better *without* inverting, because the halo is what
  separates the subject from a dark background. Try both and look.
- **`--turdsize`** — the despeckle threshold, and on photographic or shaded
  sources this is the main quality dial. Raise it to kill threshold noise, but
  raise it too far and real detail (small lettering, badges) goes with it.

An imported icon records its source path and a SHA-256 of the file. If you edit
or replace that file, the next `drawer` / `batch` / `bin` / `bins` run notices
and retraces before rendering, so labels and sheets can't go stale behind your
back. The retrace reuses the **stored** trace options, not whatever the current
command line says — otherwise a plain `./label bins` would silently re-cut an
icon tuned at `--turdsize 800` using the default 150.

```sh
./label icon list       # marks changed sources as STALE
./label icon refresh    # retrace everything stale, without rendering labels
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
| `<slug>.png` | raw generation or import, kept so `--retrace` never re-bills you |
| `<slug>.svg` | traced outline, for eyeballing |
| `<slug>.json` | normalized path, aspect ratio, trace settings, and source hash for imports |
| `catalog.json` | slug → description |

## Tuning

| flag | default | what it does |
| --- | --- | --- |
| `--cap-height` | fills the frame | height of a capital letter |
| `--icon-height` | matches cap height | icon height |
| `--label-height` | `0.75in` | canvas height, i.e. usable drawer height |
| `--border` | `1px` | width of the rounded frame; `0` omits it |
| `--inset` | `5px` | clearance between the frame and the content |
| `--corner-radius` | `0.09in` | corner rounding on the frame |
| `--gap` | `0.12in` | space between icon and text |
| `--pad` | `0` | blank margin outside the frame |
| `--tracking` | `0` | extra letter spacing, in em |
| `--max-width` | — | shrink the text until the label fits this width |
| `--no-upper` | — | keep text as typed instead of uppercasing |
| `--turdsize` | `150` | drop traced specks/holes below this source-pixel area |
| `--threshold` | `128` | black/white cutoff when binarizing a generated icon |
| `--invert` | — | source art is light-on-dark; flip it before tracing |

`bin` takes the same flags but with defaults sized for a shelf bin: `--cap-height
0.4`, `--icon-height 2.6`, `--gap 0.25`, `--pad 0.25`, plus `--bin-width 6`,
`--bin-height 4`, and `--sheet-width 12`. It also defaults to `--icon-style
outline` rather than `solid` — at 2.6 in tall the narrow white channels that make
outline art unweedable on a 0.75 in drawer label are wide enough to lift cleanly.

Cap height is taken from the font's metrics, not from each string's bounding box,
so every label in a set shares one baseline and one letter size. Round letters
like `O` and `S` overshoot the cap line slightly — that's correct typography, not
a bug.

Text is uppercased by default. `--no-upper` works, but lowercase descenders can
drop past the 0.75 in canvas at the default cap height; lower `--cap-height` to
about `0.38` if you want mixed case.

## Layout

```
drawer primary:    ╭─ border ────────────────────────────╮
                   │ inset [ icon ][ gap ][ text ] inset │  0.75in
                   ╰─────────────────────────────────────╯
drawer secondary:  ╭─ border ────────────────────────────╮
                   │ inset [ text ][ gap ][ icon ] inset │
                   ╰─────────────────────────────────────╯

bin:  ┌──────── 6in ────────┐
      │        text         │
      │         gap         │  4in, content centered
      │        icon         │
      └─────────────────────┘
```

For drawer labels, width is whatever the content needs and height is always the
label height. The frame is emitted as a filled ring — an outer rounded rectangle
plus a reversed inner one — not a stroke, so it stays an outline like everything
else and Easy Cut Studio cuts both contours. Bin labels are the opposite shape and
carry no frame: a fixed cell with the content centered inside it.

## Repo layout

| file | role |
| --- | --- |
| `label` | wrapper that runs the CLI in the venv |
| `toolbox_labels.py` | CLI: `label`, `drawer`, `batch`, `bin`, `bins`, `icon` |
| `labels.py` | text→outline layout, exact-inch SVG, drawer/bin preview |
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
