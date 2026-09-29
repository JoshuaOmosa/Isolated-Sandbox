from solution import aggregate, parse_line, top_errors

LOG = [
    "2024-05-01T12:00:01Z INFO api: GET /health",
    "2024-05-01T12:00:02Z ERROR db: timeout after 30s",
    "2024-05-01T12:00:03Z ERROR db: timeout after 45s",
    "2024-05-01T12:00:04Z CRITICAL payments: card declined (code=402)",
    "2024-05-01T12:00:05Z warning api: slow response",
    "not a log line",
    "",
]


def test_parse_valid_line():
    assert parse_line("2024-05-01T12:00:03Z ERROR payments: card declined (code=402)") == {
        "timestamp": "2024-05-01T12:00:03Z",
        "level": "ERROR",
        "component": "payments",
        "message": "card declined (code=402)",
    }


def test_level_is_case_insensitive_and_warning_normalised():
    assert parse_line("2024-05-01T12:00:03Z warning api: slow")["level"] == "WARN"
    assert parse_line("2024-05-01T12:00:03Z error api: boom")["level"] == "ERROR"


def test_malformed_lines_return_none():
    assert parse_line("garbage") is None
    assert parse_line("") is None
    assert parse_line("2024-05-01 12:00:03 ERROR x: y") is None
    assert parse_line("2024-05-01T12:00:03Z TRACE api: hi") is None


def test_only_first_colon_splits_the_message():
    record = parse_line("2024-05-01T12:00:03Z INFO api: GET /a?b=1: ok\n")
    assert record["component"] == "api"
    assert record["message"] == "GET /a?b=1: ok"


def test_aggregate_counts_levels_and_malformed():
    assert aggregate(LOG) == {"levels": {"INFO": 1, "ERROR": 2, "CRITICAL": 1, "WARN": 1}, "malformed": 1}


def test_top_errors_normalises_digits_and_ranks():
    assert top_errors(LOG, n=2) == [("timeout after #s", 2), ("card declined (code=#)", 1)]


def test_top_errors_ignores_non_errors_and_respects_limit():
    assert top_errors(LOG, n=1) == [("timeout after #s", 2)]
    assert top_errors(["2024-05-01T12:00:01Z INFO api: fine"]) == []


def test_top_errors_ties_break_alphabetically():
    lines = [
        "2024-05-01T12:00:01Z ERROR a: zebra",
        "2024-05-01T12:00:02Z ERROR a: apple",
    ]
    assert top_errors(lines) == [("apple", 1), ("zebra", 1)]
