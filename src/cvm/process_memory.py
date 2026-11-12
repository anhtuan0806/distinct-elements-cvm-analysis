"""Read the Core's opt-in per-process RSS message without losing diagnostics."""

PEAK_MARKER = "cvm-tv3-peak-rss-v1:"


def peak_memory(stderr: str) -> tuple[int | None, str]:
    lines = stderr.splitlines(keepends=True)
    markers = [line[len(PEAK_MARKER) :].strip() for line in lines if line.startswith(PEAK_MARKER)]
    diagnostics = "".join(line for line in lines if not line.startswith(PEAK_MARKER))
    if len(markers) != 1 or not markers[0].isascii() or not markers[0].isdigit():
        return None, diagnostics
    try:
        return int(markers[0]) or None, diagnostics
    except ValueError:
        return None, diagnostics
