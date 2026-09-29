"""Reference solution: interval merging, coverage and gaps."""


def _validated_sorted(intervals):
    checked = []
    for start, end in intervals:
        if start > end:
            raise ValueError(f"invalid interval: ({start}, {end})")
        checked.append((start, end))
    return sorted(checked)


def merge(intervals):
    merged = []
    for start, end in _validated_sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def total_covered(intervals):
    return sum(end - start for start, end in merge(intervals))


def gaps(intervals, lo, hi):
    result = []
    cursor = lo
    for start, end in merge(intervals):
        if end <= cursor:
            continue
        if start >= hi:
            break
        if start > cursor:
            result.append((cursor, start))
        cursor = max(cursor, end)
        if cursor >= hi:
            break
    if cursor < hi:
        result.append((cursor, hi))
    return result
