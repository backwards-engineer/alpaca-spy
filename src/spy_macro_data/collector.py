from __future__ import annotations

import calendar
import itertools
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from .alpaca import AlpacaClient
from .store import Store

TARGET_DTES = (0, 30, 60, 120)


def _nth_sunday(year: int, month: int, occurrence: int) -> int:
    first_weekday, days = calendar.monthrange(year, month)
    first_sunday = 1 + ((6 - first_weekday) % 7)
    return min(days, first_sunday + 7 * (occurrence - 1))


def eastern_time(value: str) -> datetime:
    """Convert an RFC-3339 UTC timestamp to US Eastern without a tzdata package."""
    utc = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    year = utc.year
    dst_start = datetime(year, 3, _nth_sunday(year, 3, 2), 7, tzinfo=timezone.utc)
    dst_end = datetime(year, 11, _nth_sunday(year, 11, 1), 6, tzinfo=timezone.utc)
    offset = timedelta(hours=-4 if dst_start <= utc < dst_end else -5)
    return (utc + offset).replace(tzinfo=timezone(offset))


def local_to_utc(day: date, clock: time) -> datetime:
    """Convert a US Eastern wall-clock time to UTC without a tzdata package."""
    dst_start = date(day.year, 3, _nth_sunday(day.year, 3, 2))
    dst_end = date(day.year, 11, _nth_sunday(day.year, 11, 1))
    offset_hours = 4 if dst_start <= day < dst_end else 5
    return datetime.combine(day, clock, tzinfo=timezone.utc) + timedelta(hours=offset_hours)


def chunks(items: list[str], size: int = 100) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


class Collector:
    def __init__(self, client: AlpacaClient, store: Store, progress=print) -> None:
        self.client = client
        self.store = store
        self.progress = progress

    def stock_bars(self, start: date, end: date) -> int:
        job = f"stock:SPY:{start}:{end}:1Hour"
        if self.store.done(job):
            self.progress(f"cached {job}")
            return 0
        total = 0
        params = {"symbols": "SPY", "timeframe": "1Hour", "start": start,
                  "end": end + timedelta(days=1), "feed": "iex", "limit": 10000}
        for page in self.client.pages(self.client.settings.data_endpoint, "/v2/stocks/bars", params):
            total += self.store.upsert_bars("stock_bars", "SPY", page.get("bars", {}).get("SPY", []))
        self.store.finish(job, total)
        self.progress(f"saved {total} SPY hourly bars")
        return total

    def contract_catalog(self, start: date, end: date) -> int:
        # Contracts are current/inactive as of download time, so combine both statuses.
        total = 0
        for status in ("inactive", "active"):
            job = f"contracts:SPY:{start}:{end}:{status}"
            if self.store.done(job):
                self.progress(f"cached {job}")
                continue
            count = 0
            params = {"underlying_symbols": "SPY", "status": status,
                      "expiration_date_gte": start, "expiration_date_lte": end,
                      "limit": 10000}
            for page in self.client.pages(
                self.client.settings.trading_endpoint, "/v2/options/contracts", params,
                token_field="next_page_token",
            ):
                count += self.store.upsert_contracts(page.get("option_contracts", []))
            self.store.finish(job, count)
            self.progress(f"saved {count} {status} SPY contracts")
            total += count
        return total

    def select_contracts(self, start: date, end: date, wings: int = 12) -> int:
        bars = self.store.connection.execute(
            "SELECT timestamp, close FROM stock_bars WHERE symbol='SPY' AND date(timestamp) BETWEEN ? AND ? ORDER BY timestamp",
            (str(start), str(end)),
        ).fetchall()
        daily: dict[date, list[tuple[str, float]]] = {}
        for timestamp, close in bars:
            dt = eastern_time(timestamp)
            if dt.weekday() < 5 and (dt.hour, dt.minute) >= (9, 30) and dt.hour < 16:
                daily.setdefault(dt.date(), []).append((timestamp, close))
        inserted = 0
        for market_date, day_bars in daily.items():
            job = f"selection:v2:{market_date}:w{wings}"
            if self.store.done(job):
                continue
            spot = float(day_bars[0][1])
            expirations = [date.fromisoformat(row[0]) for row in self.store.connection.execute(
                "SELECT DISTINCT expiration_date FROM option_contracts WHERE expiration_date >= ? ORDER BY expiration_date",
                (str(market_date),),
            )]
            rows: list[tuple[Any, ...]] = []
            for target in TARGET_DTES:
                if not expirations:
                    continue
                expiry = min(expirations, key=lambda exp: (abs((exp - market_date).days - target), exp))
                actual = (expiry - market_date).days
                contracts = self.store.connection.execute(
                    "SELECT symbol, option_type, strike FROM option_contracts WHERE expiration_date=? ORDER BY option_type, strike",
                    (str(expiry),),
                ).fetchall()
                for option_type, group in itertools.groupby(contracts, key=lambda r: r[1]):
                    typed = list(group)
                    below = sorted((r for r in typed if r[2] < spot), key=lambda r: r[2], reverse=True)[:wings]
                    above = sorted((r for r in typed if r[2] >= spot), key=lambda r: r[2])[:wings]
                    for side_group, side in ((below, "below_spot"), (above, "above_spot")):
                        for rank, (symbol, kind, strike) in enumerate(side_group, 1):
                            rows.append((str(market_date), target, actual, str(expiry), symbol,
                                         kind, strike, spot, side, rank))
            self.store.connection.execute(
                "DELETE FROM option_selection WHERE market_date=?", (str(market_date),)
            )
            self.store.connection.executemany(
                "INSERT OR REPLACE INTO option_selection VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )
            self.store.connection.commit()
            self.store.finish(job, len(rows))
            inserted += len(rows)
            self.progress(f"selected {len(rows)} contracts for {market_date}")
        return inserted

    def option_bars(self, start: date, end: date) -> int:
        total = 0
        market_dates = [r[0] for r in self.store.connection.execute(
            "SELECT DISTINCT market_date FROM option_selection WHERE market_date BETWEEN ? AND ? ORDER BY market_date",
            (str(start), str(end)),
        )]
        for market_date in market_dates:
            job = f"option-bars:v2:{market_date}:1Hour"
            if self.store.done(job):
                continue
            symbols = [r[0] for r in self.store.connection.execute(
                "SELECT DISTINCT symbol FROM option_selection WHERE market_date=?", (market_date,)
            )]
            count = 0
            session_date = date.fromisoformat(market_date)
            session_start = local_to_utc(session_date, time(9, 30)).isoformat().replace("+00:00", "Z")
            session_end = local_to_utc(session_date, time(16)).isoformat().replace("+00:00", "Z")
            for batch in chunks(symbols):
                params = {"symbols": ",".join(batch), "timeframe": "1Hour",
                          "start": session_start, "end": session_end,
                          "limit": 10000}
                for page in self.client.pages(self.client.settings.data_endpoint, "/v1beta1/options/bars", params):
                    for symbol, bars in page.get("bars", {}).items():
                        count += self.store.upsert_bars("option_bars", symbol, bars)
            self.store.finish(job, count, f"symbols={len(symbols)}")
            total += count
            self.progress(f"saved {count} option bars for {market_date}")
        return total

    def collect(self, start: date, end: date) -> None:
        self.stock_bars(start, end)
        self.contract_catalog(start, end + timedelta(days=max(TARGET_DTES) + 14))
        self.select_contracts(start, end)
        self.option_bars(start, end)
