"""Reference solution: structured log parsing, aggregation and error ranking."""
import re
from collections import Counter

_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+"
    r"(?P<level>[A-Za-z]+)\s+"
    r"(?P<component>[\w.\-]+):\s+"
    r"(?P<message>.*\S)$"
)
_LEVELS = {"DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL"}


def parse_line(line):
    match = _LINE.match(line.strip())
    if not match:
        return None
    level = match["level"].upper()
    if level not in _LEVELS:
        return None
    if level == "WARNING":
        level = "WARN"
    return {
        "timestamp": match["ts"],
        "level": level,
        "component": match["component"],
        "message": match["message"],
    }


def aggregate(lines):
    levels = Counter()
    malformed = 0
    for line in lines:
        record = parse_line(line)
        if record is None:
            if line.strip():
                malformed += 1
            continue
        levels[record["level"]] += 1
    return {"levels": dict(levels), "malformed": malformed}


def _normalise(message):
    return re.sub(r"\d+", "#", message)


def top_errors(lines, n=3):
    counts = Counter()
    for line in lines:
        record = parse_line(line)
        if record and record["level"] in {"ERROR", "CRITICAL"}:
            counts[_normalise(record["message"])] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:n]
