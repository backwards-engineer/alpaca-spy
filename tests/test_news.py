from datetime import date

from spy_macro_data.news_collector import article_window, score_article


def test_article_windows_use_eastern_time():
    assert article_window(date(2026, 8, 3), "2026-08-03T12:00:00Z") == "pre_market"
    assert article_window(date(2026, 1, 5), "2026-01-05T19:30:00Z") == "afternoon"
    assert article_window(date(2026, 8, 3), "2026-08-03T14:00:00Z") == "pre_market"
    assert article_window(date(2026, 8, 3), "2026-08-03T14:30:00Z") == "late_morning"
    assert article_window(date(2026, 8, 3), "2026-08-03T17:00:00Z") == "afternoon"
    assert article_window(date(2026, 8, 3), "2026-08-03T19:30:00Z") == "after_close"


def test_fomc_headline_is_relevant():
    result = score_article(date(2026, 8, 3), {
        "created_at": "2026-08-03T12:00:00Z",
        "headline": "FOMC officials signal patience before the next rate cut",
        "summary": "Federal Reserve policymakers discussed inflation.",
        "content": "Jerome Powell will speak later in the week.",
    })
    assert result is not None
    assert "fed" in result.categories


def test_incidental_corporate_tariff_reference_is_rejected():
    result = score_article(date(2026, 8, 3), {
        "created_at": "2026-08-03T12:00:00Z",
        "headline": "Manufacturer reports quarterly earnings",
        "summary": "Revenue increased from last year.",
        "content": "Management briefly mentioned tariffs during the call.",
    })
    assert result is None
