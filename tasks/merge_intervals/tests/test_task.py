import pytest

from solution import gaps, merge, total_covered


def test_merge_overlapping():
    assert merge([(1, 3), (2, 6), (8, 10), (15, 18)]) == [(1, 6), (8, 10), (15, 18)]


def test_merge_touching_intervals_are_joined():
    assert merge([(1, 4), (4, 5)]) == [(1, 5)]


def test_merge_handles_unsorted_and_nested():
    assert merge([(5, 6), (1, 10), (2, 3)]) == [(1, 10)]


def test_merge_empty_and_single():
    assert merge([]) == []
    assert merge([(2, 2)]) == [(2, 2)]


def test_merge_does_not_mutate_input():
    data = [(5, 6), (1, 3)]
    merge(data)
    assert data == [(5, 6), (1, 3)]


def test_merge_rejects_inverted_interval():
    with pytest.raises(ValueError):
        merge([(5, 1)])


def test_total_covered_counts_union_once():
    assert total_covered([(1, 3), (2, 6), (8, 10)]) == 7


def test_gaps_between_intervals():
    assert gaps([(2, 4), (6, 8)], 0, 10) == [(0, 2), (4, 6), (8, 10)]


def test_gaps_are_clipped_to_window():
    assert gaps([(-5, 3), (9, 20)], 0, 10) == [(3, 9)]


def test_gaps_fully_covered_window():
    assert gaps([(0, 10)], 0, 10) == []
