from datetime import date

from spy_macro_data.collector import chunks, eastern_time


def test_chunks_respects_alpaca_symbol_limit():
    values = [str(i) for i in range(205)]
    result = chunks(values)
    assert [len(group) for group in result] == [100, 100, 5]
    assert [item for group in result for item in group] == values


def test_eastern_time_handles_dst():
    assert eastern_time("2026-01-05T15:00:00Z").hour == 10
    assert eastern_time("2026-07-06T14:00:00Z").hour == 10
