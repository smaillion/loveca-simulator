"""Caching must not change exact-text parsing or share mutable results."""

import pytest

from loveca.simulation import effect_candidates as candidates


@pytest.mark.parametrize("text", [
    "", "plain text", "  plain text  ",
    "【登場】カードを1枚引く。",
    "【登場】/【ライブ開始時】カードを1枚引く。",
    "【登場】 / 【ライブ開始時】カードを1枚引く。",
    "【自動】【ターン1回】自分のステージにコスト10のメンバーが登場したとき、カードを1枚引く。",
    "【常時】テキスト。\n【起動】テキスト。\n【ライブ成功時】テキスト。",
])
def test_cached_segments_match_uncached_algorithm_and_return_independent_lists(text):
    cache = candidates._cached_timing_segments_with_markers
    cache.cache_clear()
    expected = list(cache.__wrapped__(text))
    first = candidates._timing_segments_with_markers(text)
    assert first == expected
    first.append((999, "mutated", "not official text"))
    second = candidates._timing_segments_with_markers(text)
    assert second == expected and first is not second
    second.clear()
    assert candidates._timing_segments_with_markers(text) == expected
    assert cache.cache_info().misses == 1
    assert cache.cache_info().hits == 2


def test_changed_text_is_a_distinct_key_even_for_the_same_card():
    cache = candidates._cached_timing_segments_with_markers
    cache.cache_clear()
    old = {"raw_effect_text_ja": "【登場】カードを1枚引く。"}
    new = {"raw_effect_text_ja": "【登場】カードを2枚引く。"}
    assert candidates._timing_segments(old) != candidates._timing_segments(new)
    assert cache.cache_info().misses == 2


def test_bounded_cache_evicts_without_changing_the_result():
    cache = candidates._cached_timing_segments_with_markers
    cache.cache_clear()
    text = "【登場】カードを1枚引く。"
    expected = candidates._timing_segments_with_markers(text)
    for index in range(2049):
        candidates._timing_segments_with_markers(f"plain-{index}")
    assert cache.cache_info().currsize == cache.cache_info().maxsize == 2048
    misses = cache.cache_info().misses
    assert candidates._timing_segments_with_markers(text) == expected
    assert cache.cache_info().misses == misses + 1
