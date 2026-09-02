"""Minimal SVG path engine: parse -> absolute M/L/C/Z, affine transform, exact bounds."""

import re

_COMMAND_PATTERN = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])([^MmLlHhVvCcSsQqTtAaZz]*)")
_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def _groups_of(values, size):
    for start in range(0, len(values) - size + 1, size):
        yield values[start : start + size]


def parse(path_data):
    """Return a flat list of absolute commands: ('M',p) ('L',p) ('C',c1,c2,p) ('Z',)."""
    commands = []
    current = subpath_start = (0.0, 0.0)
    previous_cubic_control = None
    previous_quadratic_control = None

    for match in _COMMAND_PATTERN.finditer(path_data):
        letter = match.group(1)
        numbers = [float(text) for text in _NUMBER_PATTERN.findall(match.group(2))]
        is_relative = letter.islower()
        kind = letter.upper()

        if kind == "Z":
            commands.append(("Z",))
            current = subpath_start
            previous_cubic_control = previous_quadratic_control = None
            continue

        if kind == "M":
            for index, (x, y) in enumerate(_groups_of(numbers, 2)):
                if is_relative:
                    x, y = current[0] + x, current[1] + y
                commands.append(("M", (x, y)) if index == 0 else ("L", (x, y)))
                if index == 0:
                    subpath_start = (x, y)
                current = (x, y)
            previous_cubic_control = previous_quadratic_control = None

        elif kind == "L":
            for x, y in _groups_of(numbers, 2):
                if is_relative:
                    x, y = current[0] + x, current[1] + y
                commands.append(("L", (x, y)))
                current = (x, y)
            previous_cubic_control = previous_quadratic_control = None

        elif kind in "HV":
            for (distance,) in _groups_of(numbers, 1):
                if kind == "H":
                    x = current[0] + distance if is_relative else distance
                    y = current[1]
                else:
                    x = current[0]
                    y = current[1] + distance if is_relative else distance
                commands.append(("L", (x, y)))
                current = (x, y)
            previous_cubic_control = previous_quadratic_control = None

        elif kind == "C":
            for x1, y1, x2, y2, x, y in _groups_of(numbers, 6):
                if is_relative:
                    x1, y1 = current[0] + x1, current[1] + y1
                    x2, y2 = current[0] + x2, current[1] + y2
                    x, y = current[0] + x, current[1] + y
                commands.append(("C", (x1, y1), (x2, y2), (x, y)))
                current, previous_cubic_control = (x, y), (x2, y2)
            previous_quadratic_control = None

        elif kind == "S":
            for x2, y2, x, y in _groups_of(numbers, 4):
                if is_relative:
                    x2, y2 = current[0] + x2, current[1] + y2
                    x, y = current[0] + x, current[1] + y
                if previous_cubic_control is None:
                    x1, y1 = current
                else:
                    x1 = 2 * current[0] - previous_cubic_control[0]
                    y1 = 2 * current[1] - previous_cubic_control[1]
                commands.append(("C", (x1, y1), (x2, y2), (x, y)))
                current, previous_cubic_control = (x, y), (x2, y2)
            previous_quadratic_control = None

        elif kind in "QT":
            values_per_curve = 4 if kind == "Q" else 2
            for values in _groups_of(numbers, values_per_curve):
                if kind == "Q":
                    control_x, control_y, x, y = values
                    if is_relative:
                        control_x = current[0] + control_x
                        control_y = current[1] + control_y
                        x, y = current[0] + x, current[1] + y
                else:
                    x, y = values
                    if is_relative:
                        x, y = current[0] + x, current[1] + y
                    if previous_quadratic_control is None:
                        control_x, control_y = current
                    else:
                        control_x = 2 * current[0] - previous_quadratic_control[0]
                        control_y = 2 * current[1] - previous_quadratic_control[1]
                first = (
                    current[0] + 2 / 3 * (control_x - current[0]),
                    current[1] + 2 / 3 * (control_y - current[1]),
                )
                second = (x + 2 / 3 * (control_x - x), y + 2 / 3 * (control_y - y))
                commands.append(("C", first, second, (x, y)))
                current, previous_quadratic_control = (x, y), (control_x, control_y)
            previous_cubic_control = None

        elif kind == "A":
            raise ValueError("elliptical arcs are not supported")

    return commands


def transform(commands, scale_x, skew_y, skew_x, scale_y, translate_x, translate_y):
    """Apply an SVG affine matrix. Cubics are affine-invariant, so only points move."""

    def move(point):
        return (
            scale_x * point[0] + skew_x * point[1] + translate_x,
            skew_y * point[0] + scale_y * point[1] + translate_y,
        )

    return [
        (command[0],) + tuple(move(point) for point in command[1:])
        for command in commands
    ]


def translate(commands, x_offset, y_offset):
    return transform(commands, 1, 0, 0, 1, x_offset, y_offset)


def _cubic_axis_extrema(start, control_one, control_two, end):
    """One axis' values at the cubic's endpoints plus any interior turning point."""
    values = [start, end]
    # The derivative is the quadratic second_order*t^2 + first_order*t + constant.
    second_order = -start + 3 * control_one - 3 * control_two + end
    first_order = 2 * (start - 2 * control_one + control_two)
    constant = control_one - start

    if abs(second_order) < 1e-12:
        roots = [-constant / first_order] if abs(first_order) > 1e-12 else []
    else:
        discriminant = first_order * first_order - 4 * second_order * constant
        if discriminant < 0:
            roots = []
        else:
            spread = discriminant**0.5
            roots = [
                (-first_order + spread) / (2 * second_order),
                (-first_order - spread) / (2 * second_order),
            ]

    for parameter in roots:
        if 0 < parameter < 1:
            remaining = 1 - parameter
            values.append(
                remaining**3 * start
                + 3 * remaining * remaining * parameter * control_one
                + 3 * remaining * parameter * parameter * control_two
                + parameter**3 * end
            )
    return values


def bounding_box(commands):
    x_values, y_values = [], []
    current = (0.0, 0.0)
    for command in commands:
        if command[0] == "Z":
            continue
        if command[0] in ("M", "L"):
            x_values.append(command[1][0])
            y_values.append(command[1][1])
            current = command[1]
        else:
            _, control_one, control_two, end = command
            x_values += _cubic_axis_extrema(
                current[0], control_one[0], control_two[0], end[0]
            )
            y_values += _cubic_axis_extrema(
                current[1], control_one[1], control_two[1], end[1]
            )
            current = end
    if not x_values:
        return None
    return (min(x_values), min(y_values), max(x_values), max(y_values))


def _format_number(value, precision):
    text = f"{value:.{precision}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def serialize(commands, precision=3):
    parts = []
    for command in commands:
        if command[0] == "Z":
            parts.append("Z")
        else:
            numbers = " ".join(
                f"{_format_number(point[0], precision)} "
                f"{_format_number(point[1], precision)}"
                for point in command[1:]
            )
            parts.append(f"{command[0]}{numbers}")
    return "".join(parts)
