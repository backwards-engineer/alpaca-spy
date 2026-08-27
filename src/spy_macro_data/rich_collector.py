from __future__ import annotations

import bisect
import json
from datetime import date, datetime, time, timedelta, timezone

from .alpaca import AlpacaClient, AlpacaError
from .collector import chunks
from .news_collector import local_to_utc
from .option_math import implied_vol_and_greeks
from .store import Store


class RichCollector:
    def __init__(self, client: AlpacaClient, store: Store, progress=print) -> None:
        self.client, self.store, self.progress = client, store, progress

    def normalize_contract_metrics(self) -> int:
        rows = []
        for symbol, raw in self.store.connection.execute("SELECT symbol, raw_json FROM option_contracts"):
            item = json.loads(raw)
            rows.append((symbol, item.get("open_interest"), item.get("open_interest_date"),
                         item.get("close_price"), item.get("close_price_date")))
        self.store.connection.executemany(
            "INSERT OR REPLACE INTO option_contract_metrics VALUES (?, ?, ?, ?, ?)", rows)
        self.store.connection.commit()
        self.progress(f"normalized {len(rows)} contract records")
        return len(rows)

    def stock_minutes(self, start: date, end: date) -> int:
        job = f"rich-stock:SPY:{start}:{end}:1Min:SIP:v1"
        if self.store.done(job):
            self.progress(f"cached {job}")
            return 0
        total = 0
        requested_end = datetime.combine(end + timedelta(days=1), time(), tzinfo=timezone.utc)
        delayed_boundary = datetime.now(timezone.utc) - timedelta(minutes=30)
        safe_end = min(requested_end, delayed_boundary).isoformat().replace("+00:00", "Z")
        params = {"symbols": "SPY", "timeframe": "1Min", "start": start,
                  "end": safe_end, "feed": "sip", "limit": 10000}
        for page in self.client.pages(self.client.settings.data_endpoint, "/v2/stocks/bars", params):
            total += self.store.upsert_bar_map("stock_bars_1m", page.get("bars", {}))
            self.progress(f"saved {total:,} SPY minute bars so far")
        self.store.finish(job, total, "feed=sip")
        return total

    def option_five_minutes(self, start: date, end: date) -> int:
        total = 0
        dates = [row[0] for row in self.store.connection.execute(
            "SELECT DISTINCT market_date FROM option_selection WHERE market_date BETWEEN ? AND ? ORDER BY market_date",
            (str(start), str(end)))]
        for index, market_date in enumerate(dates, 1):
            job = f"rich-option:{market_date}:5Min:v1"
            if self.store.done(job):
                continue
            symbols = [row[0] for row in self.store.connection.execute(
                "SELECT DISTINCT symbol FROM option_selection WHERE market_date=?", (market_date,))]
            count = 0
            try:
                session_date = date.fromisoformat(market_date)
                session_start = local_to_utc(session_date, time(9, 30)).isoformat().replace("+00:00", "Z")
                session_end = local_to_utc(session_date, time(16)).isoformat().replace("+00:00", "Z")
                for batch in chunks(symbols):
                    params = {"symbols": ",".join(batch), "timeframe": "5Min", "start": session_start,
                              "end": session_end, "limit": 10000}
                    for page in self.client.pages(self.client.settings.data_endpoint, "/v1beta1/options/bars", params):
                        count += self.store.upsert_bar_map("option_bars_5m", page.get("bars", {}))
            except AlpacaError as exc:
                if "OPRA agreement is not signed" in str(exc):
                    self.progress(f"[{index}/{len(dates)}] deferred {market_date}: recent OPRA entitlement required")
                    continue
                raise
            self.store.finish(job, count, f"symbols={len(symbols)}")
            total += count
            self.progress(f"[{index}/{len(dates)}] saved {count:,} five-minute option bars for {market_date}")
        return total

    def metrics(self, start: date, end: date, rate: float = 0.0425, dividend: float = 0.012) -> int:
        total = 0
        dates = [row[0] for row in self.store.connection.execute(
            "SELECT DISTINCT market_date FROM option_selection WHERE market_date BETWEEN ? AND ? ORDER BY market_date",
            (str(start), str(end)))]
        for index, market_date in enumerate(dates, 1):
            job = f"rich-metrics:{market_date}:bs-v1-r{rate}-q{dividend}"
            if self.store.done(job):
                continue
            if not self.store.done(f"rich-option:{market_date}:5Min:v1"):
                self.progress(f"[{index}/{len(dates)}] deferred metrics for {market_date}: option day incomplete")
                continue
            stock = self.store.connection.execute(
                "SELECT timestamp, close FROM stock_bars_1m WHERE symbol='SPY' AND date(timestamp)=? ORDER BY timestamp",
                (market_date,)).fetchall()
            stock_times = [datetime.fromisoformat(row[0].replace("Z", "+00:00")) for row in stock]
            stock_prices = [float(row[1]) for row in stock]
            option_rows = self.store.connection.execute(
                """SELECT b.symbol,b.timestamp,b.close,s.option_type,s.strike,s.expiration_date
                   FROM option_bars_5m b JOIN option_selection s ON s.symbol=b.symbol
                     AND s.market_date=date(b.timestamp)
                   WHERE s.market_date=? GROUP BY b.symbol,b.timestamp ORDER BY b.timestamp""", (market_date,)).fetchall()
            if not option_rows:
                self.progress(f"[{index}/{len(dates)}] deferred metrics for {market_date}: no five-minute bars")
                continue
            rows = []
            for symbol, timestamp, close, kind, strike, expiration in option_rows:
                instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                position = bisect.bisect_right(stock_times, instant) - 1
                if position < 0:
                    continue
                spot = stock_prices[position]
                expiry = local_to_utc(date.fromisoformat(expiration), time(16))
                years = max((expiry - instant).total_seconds(), 60.0) / (365.0 * 86400.0)
                result = implied_vol_and_greeks(kind, spot, float(strike), years, float(close), rate, dividend)
                values = result or {}
                rows.append((symbol, timestamp, spot, values.get("implied_volatility"), values.get("delta"),
                             values.get("gamma"), values.get("theta"), values.get("vega"), rate, dividend,
                             "black_scholes_estimate"))
            self.store.connection.executemany(
                "INSERT OR REPLACE INTO option_metrics_5m VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            self.store.connection.commit()
            self.store.finish(job, len(rows))
            total += len(rows)
            self.progress(f"[{index}/{len(dates)}] calculated {len(rows):,} option metrics for {market_date}")
        return total

    def collect(self, start: date, end: date) -> None:
        self.normalize_contract_metrics()
        self.stock_minutes(start, end)
        self.option_five_minutes(start, end)
        self.metrics(start, end)
