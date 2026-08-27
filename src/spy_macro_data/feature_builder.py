from __future__ import annotations

import bisect
import json
from collections import defaultdict
from datetime import date, datetime

from .collector import eastern_time
from .store import Store


def _percent(current: float, prior: float | None) -> float | None:
    return (current / prior - 1.0) * 100.0 if prior else None


class FeatureBuilder:
    def __init__(self, store: Store, progress=print) -> None:
        self.store, self.progress = store, progress

    def build(self, start: date, end: date, force: bool = False) -> int:
        days = [row[0] for row in self.store.connection.execute(
            """SELECT substr(job_key,13,10) FROM download_log
               WHERE job_key LIKE 'rich-option:%:5Min:v1'
                 AND substr(job_key,13,10) BETWEEN ? AND ? ORDER BY 1""", (str(start), str(end)))]
        total = 0
        for index, day in enumerate(days, 1):
            job = f"features:v1:{day}"
            if self.store.done(job) and not force:
                continue
            count = self._build_day(day)
            self.store.finish(job, count)
            total += count
            self.progress(f"[{index}/{len(days)}] materialized {count:,} feature rows for {day}")
        self.store.connection.execute("PRAGMA optimize")
        return total

    def _build_day(self, day: str) -> int:
        stock_rows = self.store.connection.execute(
            """SELECT timestamp,open,high,low,close,volume,vwap FROM stock_bars_1m
               WHERE symbol='SPY' AND date(timestamp)=? ORDER BY timestamp""", (day,)).fetchall()
        stock: dict[int, dict] = {}
        cumulative_value = cumulative_volume = 0.0
        intraday_high = float("-inf")
        intraday_low = float("inf")
        session_open = None
        for timestamp, open_, high, low, close, volume, vwap in stock_rows:
            local = eastern_time(timestamp)
            minute = local.hour * 60 + local.minute
            if minute < 570 or minute >= 960:
                continue
            session_open = float(open_) if session_open is None else session_open
            intraday_high = max(intraday_high, float(high))
            intraday_low = min(intraday_low, float(low))
            weight = float(volume or 0)
            cumulative_value += float(vwap if vwap is not None else close) * weight
            cumulative_volume += weight
            stock[minute] = {"price": float(close), "vwap": cumulative_value / cumulative_volume if cumulative_volume else float(close),
                             "high": intraday_high, "low": intraday_low, "open": session_open}
        if not stock:
            return 0

        news = []
        for published_at, categories_json in self.store.connection.execute(
            "SELECT published_at,categories_json FROM news_articles WHERE market_date=? ORDER BY published_at", (day,)):
            news.append((datetime.fromisoformat(published_at.replace("Z", "+00:00")), set(json.loads(categories_json))))

        snapshots: dict[str, list[tuple[datetime, tuple]]] = defaultdict(list)
        for row in self.store.connection.execute(
            """SELECT s.symbol,s.captured_at,s.quote_at,s.bid,s.bid_size,s.ask,s.ask_size,r.feed
               FROM live_option_snapshots s LEFT JOIN snapshot_runs r USING(captured_at)
               WHERE date(s.captured_at)=? ORDER BY s.symbol,s.captured_at""", (day,)):
            captured = datetime.fromisoformat(row[1].replace("Z", "+00:00"))
            snapshots[row[0]].append((captured, row[2:]))

        option_rows = self.store.connection.execute(
            """SELECT s.target_dte,s.actual_dte,s.expiration_date,s.symbol,s.option_type,s.strike,
                      b.timestamp,b.close,b.volume,b.trade_count,m.implied_volatility
               FROM option_selection s JOIN option_bars_5m b
                 ON b.symbol=s.symbol AND date(b.timestamp)=s.market_date
               LEFT JOIN option_metrics_5m m ON m.symbol=b.symbol AND m.timestamp=b.timestamp
               WHERE s.market_date=? ORDER BY s.symbol,b.timestamp,s.target_dte""", (day,)).fetchall()
        history: dict[str, dict[str, tuple[float, float | None]]] = defaultdict(dict)
        for target, actual, expiry, symbol, kind, strike, timestamp, close, volume, trades, iv in option_rows:
            history[symbol][timestamp] = (float(close), float(iv) if iv is not None else None)

        rows = []
        for target, actual, expiry, symbol, kind, strike, timestamp, close, volume, trades, iv in option_rows:
            instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            local = eastern_time(timestamp)
            minute = local.hour * 60 + local.minute
            if minute < 570 or minute >= 960:
                continue
            state = stock.get(minute)
            if state is None:
                prior_minutes = [value for value in stock if value <= minute]
                state = stock[max(prior_minutes)] if prior_minutes else None
            if state is None:
                continue
            price = state["price"]
            prior5 = stock.get(minute - 5, {}).get("price")
            prior15 = stock.get(minute - 15, {}).get("price")
            prior30 = stock.get(minute - 30, {}).get("price")
            symbol_history = history[symbol]
            prior_timestamp5 = (instant.replace()).timestamp() - 300
            prior_timestamp15 = instant.timestamp() - 900
            def historical(epoch: float):
                key = datetime.fromtimestamp(epoch, tz=instant.tzinfo).isoformat().replace("+00:00", "Z")
                return symbol_history.get(key)
            old5, old15 = historical(prior_timestamp5), historical(prior_timestamp15)
            close_value = float(close)
            iv_value = float(iv) if iv is not None else None
            active_categories: set[str] = set()
            latest_age = None
            for published, categories in news:
                age = (instant - published).total_seconds() / 60.0
                if 0 <= age <= 60:
                    active_categories.update(categories)
                    latest_age = age if latest_age is None else min(latest_age, age)

            quote = None
            quote_age = None
            candidates = snapshots.get(symbol, [])
            if candidates:
                times = [item[0] for item in candidates]
                position = bisect.bisect_right(times, instant) - 1
                if position >= 0:
                    captured, quote_values = candidates[position]
                    quote_age = (instant - captured).total_seconds()
                    if 0 <= quote_age <= 90:
                        quote = quote_values
            quote_at = bid = bid_size = ask = ask_size = mid = spread = spread_pct = quote_feed = None
            if quote:
                quote_at, bid, bid_size, ask, ask_size, quote_feed = quote
                if bid is not None and ask is not None and float(ask) >= float(bid):
                    bid, ask = float(bid), float(ask)
                    mid = (bid + ask) / 2.0
                    spread = ask - bid
                    spread_pct = spread / mid * 100.0 if mid else None
            moneyness = ((price - float(strike)) / price if kind == "call" else (float(strike) - price) / price) * 100.0
            rows.append((day, target, symbol, timestamp, actual, expiry, kind, strike, minute,
                         close_value, _percent(close_value, old5[0] if old5 else None),
                         _percent(close_value, old15[0] if old15 else None), price,
                         _percent(price, prior5), _percent(price, prior15), _percent(price, prior30),
                         _percent(price, state["open"]), state["vwap"], _percent(price, state["vwap"]),
                         state["high"], state["low"], _percent(price, state["high"]), _percent(price, state["low"]),
                         iv_value, (iv_value - old5[1]) if iv_value is not None and old5 and old5[1] is not None else None,
                         (iv_value - old15[1]) if iv_value is not None and old15 and old15[1] is not None else None,
                         moneyness, volume, trades, json.dumps(sorted(active_categories)), latest_age,
                         quote_at, bid, bid_size, ask, ask_size, mid, spread, spread_pct, quote_age,
                         f"alpaca_{quote_feed}" if quote_feed else ("alpaca_indicative" if quote else None)))
        self.store.connection.execute("DELETE FROM option_features_5m WHERE market_date=?", (day,))
        self.store.connection.executemany(
            "INSERT INTO option_features_5m VALUES (" + ",".join("?" for _ in range(41)) + ")", rows)
        self.store.connection.commit()
        return len(rows)
