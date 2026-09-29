def merge(intervals):
    merged = []
    for start, end in intervals:  # BUG: never sorts, never validates
        if merged and start < merged[-1][1]:  # BUG: touching intervals are not joined
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def total_covered(intervals):
    return sum(end - start for start, end in merge(intervals))


def gaps(intervals, lo, hi):
    result, cursor = [], lo
    for start, end in merge(intervals):
        if start > cursor:
            result.append((cursor, min(start, hi)))
        cursor = max(cursor, end)
    if cursor < hi:
        result.append((cursor, hi))
    return result
