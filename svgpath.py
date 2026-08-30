"""Minimal SVG path engine: parse -> absolute M/L/C/Z, affine transform, exact bbox."""

import re

_TOKEN_RE = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])([^MmLlHhVvCcSsQqTtAaZz]*)")
_NUM_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def _chunks(seq, n):
    for i in range(0, len(seq) - n + 1, n):
        yield seq[i : i + n]


def parse(d):
    """Return a flat list of absolute commands: ('M',p) ('L',p) ('C',c1,c2,p) ('Z',)."""
    out = []
    cur = start = (0.0, 0.0)
    prev_cubic_ctrl = None
    prev_quad_ctrl = None

    for m in _TOKEN_RE.finditer(d):
        cmd = m.group(1)
        nums = [float(x) for x in _NUM_RE.findall(m.group(2))]
        rel = cmd.islower()
        c = cmd.upper()

        if c == "Z":
            out.append(("Z",))
            cur = start
            prev_cubic_ctrl = prev_quad_ctrl = None
            continue

        if c == "M":
            for i, (x, y) in enumerate(_chunks(nums, 2)):
                if rel:
                    x, y = cur[0] + x, cur[1] + y
                out.append(("M", (x, y)) if i == 0 else ("L", (x, y)))
                if i == 0:
                    start = (x, y)
                cur = (x, y)
            prev_cubic_ctrl = prev_quad_ctrl = None

        elif c == "L":
            for x, y in _chunks(nums, 2):
                if rel:
                    x, y = cur[0] + x, cur[1] + y
                out.append(("L", (x, y)))
                cur = (x, y)
            prev_cubic_ctrl = prev_quad_ctrl = None

        elif c in "HV":
            for (v,) in _chunks(nums, 1):
                if c == "H":
                    x = cur[0] + v if rel else v
                    y = cur[1]
                else:
                    x = cur[0]
                    y = cur[1] + v if rel else v
                out.append(("L", (x, y)))
                cur = (x, y)
            prev_cubic_ctrl = prev_quad_ctrl = None

        elif c == "C":
            for x1, y1, x2, y2, x, y in _chunks(nums, 6):
                if rel:
                    x1, y1 = cur[0] + x1, cur[1] + y1
                    x2, y2 = cur[0] + x2, cur[1] + y2
                    x, y = cur[0] + x, cur[1] + y
                out.append(("C", (x1, y1), (x2, y2), (x, y)))
                cur, prev_cubic_ctrl = (x, y), (x2, y2)
            prev_quad_ctrl = None

        elif c == "S":
            for x2, y2, x, y in _chunks(nums, 4):
                if rel:
                    x2, y2 = cur[0] + x2, cur[1] + y2
                    x, y = cur[0] + x, cur[1] + y
                if prev_cubic_ctrl is None:
                    x1, y1 = cur
                else:
                    x1 = 2 * cur[0] - prev_cubic_ctrl[0]
                    y1 = 2 * cur[1] - prev_cubic_ctrl[1]
                out.append(("C", (x1, y1), (x2, y2), (x, y)))
                cur, prev_cubic_ctrl = (x, y), (x2, y2)
            prev_quad_ctrl = None

        elif c in "QT":
            step = 4 if c == "Q" else 2
            for vals in _chunks(nums, step):
                if c == "Q":
                    qx, qy, x, y = vals
                    if rel:
                        qx, qy = cur[0] + qx, cur[1] + qy
                        x, y = cur[0] + x, cur[1] + y
                else:
                    x, y = vals
                    if rel:
                        x, y = cur[0] + x, cur[1] + y
                    if prev_quad_ctrl is None:
                        qx, qy = cur
                    else:
                        qx = 2 * cur[0] - prev_quad_ctrl[0]
                        qy = 2 * cur[1] - prev_quad_ctrl[1]
                c1 = (cur[0] + 2 / 3 * (qx - cur[0]), cur[1] + 2 / 3 * (qy - cur[1]))
                c2 = (x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y))
                out.append(("C", c1, c2, (x, y)))
                cur, prev_quad_ctrl = (x, y), (qx, qy)
            prev_cubic_ctrl = None

        elif c == "A":
            raise ValueError("elliptical arcs are not supported")

    return out


def transform(cmds, a, b, c, d, e, f):
    """Apply the affine matrix [a b c d e f]. Cubics are affine-invariant."""

    def pt(p):
        return (a * p[0] + c * p[1] + e, b * p[0] + d * p[1] + f)

    return [(k[0],) + tuple(pt(p) for p in k[1:]) for k in cmds]


def _cubic_axis_extrema(p0, p1, p2, p3):
    vals = [p0, p3]
    A = -p0 + 3 * p1 - 3 * p2 + p3
    B = 2 * (p0 - 2 * p1 + p2)
    C = p1 - p0
    if abs(A) < 1e-12:
        if abs(B) > 1e-12:
            roots = [-C / B]
        else:
            roots = []
    else:
        disc = B * B - 4 * A * C
        if disc < 0:
            roots = []
        else:
            s = disc**0.5
            roots = [(-B + s) / (2 * A), (-B - s) / (2 * A)]
    for t in roots:
        if 0 < t < 1:
            u = 1 - t
            vals.append(u**3 * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t**3 * p3)
    return vals


def bbox(cmds):
    xs, ys = [], []
    cur = (0.0, 0.0)
    for k in cmds:
        if k[0] == "Z":
            continue
        if k[0] in ("M", "L"):
            xs.append(k[1][0])
            ys.append(k[1][1])
            cur = k[1]
        else:
            _, c1, c2, p = k
            xs += _cubic_axis_extrema(cur[0], c1[0], c2[0], p[0])
            ys += _cubic_axis_extrema(cur[1], c1[1], c2[1], p[1])
            cur = p
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _n(v, prec):
    s = f"{v:.{prec}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def serialize(cmds, prec=3):
    parts = []
    for k in cmds:
        if k[0] == "Z":
            parts.append("Z")
        else:
            nums = " ".join(f"{_n(p[0], prec)} {_n(p[1], prec)}" for p in k[1:])
            parts.append(f"{k[0]}{nums}")
    return "".join(parts)
