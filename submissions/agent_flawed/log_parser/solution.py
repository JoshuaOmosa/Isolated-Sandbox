import re
from collections import Counter

_LINE = re.compile(r"^(\S+) (DEBUG|INFO|WARN|ERROR|CRITICAL) ([\w.\-]+): (.+)$")  # BUG: case-sensitive, no WARNING


def parse_line(line):
    match = _LINE.match(line.strip())
    if not match:
        return None
    ts, level, component, message = match.groups()
    return {"timestamp": ts, "level": level, "component": component, "message": message}


def aggregate(lines):
    levels, malformed = Counter(), 0
    for line in lines:
        record = parse_line(line)
        if record is None:
            if line.strip():
                malformed += 1
            continue
        levels[record["level"]] += 1
    return {"levels": dict(levels), "malformed": malformed}


def top_errors(lines, n=3):
    counts = Counter()
    for line in lines:
        record = parse_line(line)
        if record and record["level"] in ("ERROR", "CRITICAL"):
            counts[record["message"]] += 1  # BUG: digits are not normalised
    return counts.most_common(n)
