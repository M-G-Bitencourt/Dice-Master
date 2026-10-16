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
