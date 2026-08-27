from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from .alpaca import AlpacaClient
from .collector import _nth_sunday
from .store import Store


WINDOWS = (
    # Gaps are split at their midpoint and assigned to the closest original
    # requested window: 10:15, 13:00, and 15:30 Eastern.
    ("pre_market", time(7, 0), time(10, 15)),
    ("late_morning", time(10, 15), time(13, 0)),
    ("afternoon", time(13, 0), time(15, 30)),
    ("after_close", time(15, 30), time(20, 0)),
)

CATEGORY_TERMS: dict[str, tuple[str, ...]] = {
    "fed": (
        "federal reserve", "fomc", "fed chair", "jerome powell", "powell",
        "interest rate", "rate cut", "rate hike", "monetary policy",
        "fed governor", "fed president", "central bank",
    ),
    "trump": (
        "donald trump", "president trump", "trump", "truth social",
        "tariff", "trade war", "executive order", "white house",
    ),
    "inflation": (
        "inflation", "consumer price index", "producer price index", "core pce",
        "pce price", "cpi", "ppi", "core prices",
    ),
    "jobs": (
        "nonfarm payroll", "non-farm payroll", "payrolls", "jobs report",
        "employment report", "unemployment", "jobless claims", "labor market",
        "jolts", "adp employment",
    ),
}

TRUMP_CONTEXT = (
    "tweet", "post", "truth social", "tariff", "trade", "market", "stock",
    "bond", "fed", "rate", "dollar", "china", "sanction", "economy",
)

FED_CORE = (
    "federal reserve", "fomc", "fed chair", "jerome powell", "powell",
    "fed governor", "fed president", "monetary policy",
)
TRUMP_CORE = ("donald trump", "president trump", "trump", "truth social")


@dataclass(frozen=True)
class ScoredArticle:
    article: dict[str, Any]
    window_key: str
    categories: tuple[str, ...]
    matched: tuple[str, ...]
    score: int


def strip_html(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def eastern_offset(day: date) -> timedelta:
    dst_start = date(day.year, 3, _nth_sunday(day.year, 3, 2))
    dst_end = date(day.year, 11, _nth_sunday(day.year, 11, 1))
    return timedelta(hours=-4 if dst_start <= day < dst_end else -5)


def local_to_utc(day: date, clock: time) -> datetime:
    local = datetime.combine(day, clock).replace(tzinfo=timezone(eastern_offset(day)))
    return local.astimezone(timezone.utc)


def article_window(day: date, timestamp: str) -> str | None:
    utc = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    local = (utc + eastern_offset(day)).time().replace(tzinfo=None)
    for key, start, end in WINDOWS:
        if start <= local < end:
            return key
    return None


def score_article(day: date, article: dict[str, Any]) -> ScoredArticle | None:
    window = article_window(day, article.get("created_at", ""))
    if not window:
        return None
    headline = strip_html(article.get("headline")).lower()
    summary = strip_html(article.get("summary")).lower()
    content = strip_html(article.get("content")).lower()
    fields = ((headline, 4), (summary, 2), (content, 1))
    categories: list[str] = []
    matched: set[str] = set()
    score = 0
    for category, terms in CATEGORY_TERMS.items():
        category_hits: set[str] = set()
        visible_hits: set[str] = set()
        category_score = 0
        for term in terms:
            pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
            for field_index, (text, weight) in enumerate(fields):
                if re.search(pattern, text):
                    category_hits.add(term)
                    if field_index < 2:
                        visible_hits.add(term)
                    category_score += weight
                    break
        if category_hits:
            combined_visible = f"{headline} {summary}"
            combined = f"{combined_visible} {content}"
            if category == "fed" and not (
                any(term in combined_visible for term in FED_CORE)
                or (any(term in content for term in FED_CORE) and len(category_hits) >= 2)
            ):
                continue
            if category == "trump":
                if not any(term in combined_visible for term in TRUMP_CORE):
                    continue
                if not any(context in combined for context in TRUMP_CONTEXT):
                    continue
            if category in {"inflation", "jobs"} and not visible_hits:
                continue
            categories.append(category)
            matched.update(category_hits)
            score += category_score
    if not categories:
        return None
    score += max(0, len(categories) - 1) * 3
    return ScoredArticle(article, window, tuple(categories), tuple(sorted(matched)), score)


class NewsCollector:
    def __init__(self, client: AlpacaClient, store: Store, progress=print) -> None:
        self.client = client
        self.store = store
        self.progress = progress

    def collect(self, start: date, end: date, force: bool = False) -> None:
        market_days = [date.fromisoformat(row[0]) for row in self.store.connection.execute(
            "SELECT DISTINCT market_date FROM option_selection WHERE market_date BETWEEN ? AND ? ORDER BY market_date",
            (str(start), str(end)),
        )]
        for market_day in market_days:
            if not force and self.store.connection.execute(
                "SELECT 1 FROM news_download_log WHERE market_date=?", (str(market_day),)
            ).fetchone():
                self.progress(f"cached news {market_day}")
                continue
            candidates: list[dict[str, Any]] = []
            for _, window_start, window_end in WINDOWS:
                params = {
                    "start": local_to_utc(market_day, window_start).isoformat().replace("+00:00", "Z"),
                    "end": local_to_utc(market_day, window_end).isoformat().replace("+00:00", "Z"),
                    "sort": "desc", "limit": 50, "include_content": "true",
                }
                page = self.client.get(
                    self.client.settings.data_endpoint, "/v1beta1/news", params
                )
                candidates.extend(page.get("news", []))
            scored = [item for article in candidates if (item := score_article(market_day, article))]
            selected: list[ScoredArticle] = []
            for key, _, _ in WINDOWS:
                window_items = [item for item in scored if item.window_key == key]
                window_items.sort(key=lambda item: (-item.score, item.article.get("created_at", "")))
                selected.extend(window_items[:10])
            with self.store.connection:
                self.store.connection.execute(
                    "DELETE FROM news_articles WHERE market_date=?", (str(market_day),)
                )
                ranks: dict[str, int] = {}
                for item in selected:
                    ranks[item.window_key] = ranks.get(item.window_key, 0) + 1
                    article = item.article
                    self.store.connection.execute(
                        """INSERT OR REPLACE INTO news_articles VALUES
                           (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(article.get("id")), str(market_day), item.window_key,
                            ranks[item.window_key], article.get("created_at"), article.get("updated_at"),
                            strip_html(article.get("headline")), strip_html(article.get("summary")),
                            article.get("author"), article.get("source"), article.get("url"),
                            json.dumps(article.get("symbols", []), separators=(",", ":")),
                            json.dumps(item.categories, separators=(",", ":")),
                            json.dumps(item.matched, separators=(",", ":")), item.score,
                            strip_html(article.get("content"))[:20_000],
                        ),
                    )
                self.store.connection.execute(
                    """INSERT OR REPLACE INTO news_download_log
                       VALUES (?, datetime('now'), ?, ?)""",
                    (str(market_day), len(candidates), len(selected)),
                )
            self.progress(
                f"news {market_day}: scanned {len(candidates)}, saved {len(selected)}"
            )
        self.store.connection.execute("PRAGMA optimize")
