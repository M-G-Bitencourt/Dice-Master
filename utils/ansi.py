import re

RESET = "\u001b[0m"

LABEL_COLOR = "1;38;2;255;200;87"
MODE_COLOR = "1;38;2;230;237;243"
SUCCESS_COLOR = "1;38;2;126;231;135"
DANGER_COLOR = "1;38;2;255;123;114"
ACCENT_COLOR = "1;38;2;86;212;221"
INFO_COLOR = "1;38;2;121;192;255"
WARN_COLOR = "1;38;2;242;204;96"
NEUTRAL_COLOR = "1;38;2;230;237;243"

BAR_FILLED = "#"
BAR_EMPTY = "-"

_ESCAPE_END = re.compile("\u001b\\[[0-9;]*m")


def sanitize(text: str) -> str:
    """Replaces backticks so dynamic text can never break the ansi fence."""
    return text.replace("`", "'")


def ansi(text: str, code: str) -> str:
    """Wraps a fence-sanitized text fragment in an ANSI SGR color sequence."""
    return f"\u001b[{code}m{sanitize(text)}{RESET}"


def code_block(lines: list[str]) -> str:
    """Builds a fenced ANSI code block from pre-colored lines."""
    return "```ansi\n" + "\n".join(lines) + "\n```"


def visible_len(text: str) -> int:
    """Returns the printed length of a string ignoring ANSI sequences."""
    return len(_ESCAPE_END.sub("", text))


def truncate_visible(text: str, width: int) -> str:
    """Truncates sanitized plain text to a visible width with an ASCII ellipsis."""
    plain = sanitize(text)

    if len(plain) <= width:
        return plain

    if width <= 3:
        return plain[:width]

    return plain[: width - 3] + "..."


def pad(text: str, width: int) -> str:
    """Pads a possibly colored string with spaces based on its visible width."""
    return text + " " * max(0, width - visible_len(text))


def severity_color(current: int, maximum: int) -> str:
    """Maps a resource ratio to a severity color from the palette."""
    if maximum <= 0:
        return NEUTRAL_COLOR

    ratio = current / maximum

    if ratio >= 2 / 3:
        return SUCCESS_COLOR
    if ratio >= 1 / 3:
        return WARN_COLOR
    return DANGER_COLOR


def bar_segments(current: int, maximum: int, width: int = 20) -> tuple[str, str]:
    """Splits a resource bar into filled and empty ASCII segments."""
    if maximum <= 0:
        ratio = 0.0
    else:
        ratio = min(max(current / maximum, 0.0), 1.0)

    filled = round(ratio * width)
    return BAR_FILLED * filled, BAR_EMPTY * (width - filled)


def resource_bar(label: str, current: int, maximum: int, width: int = 20) -> str:
    """Builds a colored resource bar line with label and current/maximum values."""
    filled, empty = bar_segments(current, maximum, width)
    color = severity_color(current, maximum)
    values = f"{current}/{maximum}"

    colored_bar = ansi(filled, color) if filled else ""
    colored_track = ansi(empty, NEUTRAL_COLOR) if empty else ""

    return (
        f"{ansi(label, LABEL_COLOR)} "
        f"[{colored_bar}{colored_track}] "
        f"{ansi(values, color)}"
    )


def clamp_code_block(value: str, limit: int) -> str:
    """Clamps a payload while preserving or closing its ANSI code block fence."""
    if len(value) <= limit:
        return value

    cut = value[:limit]

    if cut.count("```") % 2 == 1:
        suffix = f"{RESET}\n```"
        cut = cut[: limit - len(suffix)]
        matches = list(_ESCAPE_END.finditer(cut))

        if matches:
            cut = cut[: matches[-1].end()]

        return cut + suffix

    return cut


def paginate_rows(
    rows: list[tuple[object, str]],
    base_length: int,
    budget: int = 1850,
    max_rows: int = 25,
) -> list[list[tuple[object, str]]]:
    """Splits (payload, line) rows into pages respecting length and row budgets."""
    pages: list[list[tuple[object, str]]] = []
    current: list[tuple[object, str]] = []
    used = base_length

    for payload, line in rows:
        size = len(line) + 1

        if current and (len(current) >= max_rows or used + size > budget):
            pages.append(current)
            current = []
            used = base_length

        current.append((payload, line))
        used += size

    if current:
        pages.append(current)

    return pages
