from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone

from .alpaca import AlpacaClient
from .collector import TARGET_DTES, chunks, eastern_time
from .store import Store


def _number(item: dict, *keys: str):
    for key in keys:
        if item.get(key) is not None:
            return item[key]
    return None


class SnapshotRecorder:
    def __init__(self, client: AlpacaClient, store: Store, progress=print) -> None:
        self.client, self.store, self.progress = client, store, progress

    def selected_symbols(self, wings: int = 12) -> list[str]:
        spot_row = self.store.connection.execute(
            "SELECT close FROM stock_bars_1m WHERE symbol='SPY' ORDER BY timestamp DESC LIMIT 1").fetchone()
        if not spot_row:
            spot_row = self.store.connection.execute(
                "SELECT close FROM stock_bars WHERE symbol='SPY' ORDER BY timestamp DESC LIMIT 1").fetchone()
        if not spot_row:
            return []
        spot, today = float(spot_row[0]), date.today()
        expirations = [date.fromisoformat(row[0]) for row in self.store.connection.execute(
            "SELECT DISTINCT expiration_date FROM option_contracts WHERE expiration_date>=? ORDER BY expiration_date",
            (str(today),))]
        symbols: list[str] = []
        for target in TARGET_DTES:
            if not expirations:
                break
            expiry = min(expirations, key=lambda value: (abs((value - today).days - target), value))
            for kind in ("call", "put"):
                contracts = self.store.connection.execute(
                    "SELECT symbol,strike FROM option_contracts WHERE expiration_date=? AND option_type=? ORDER BY strike",
                    (str(expiry), kind)).fetchall()
                below = sorted((row for row in contracts if row[1] < spot), key=lambda row: row[1], reverse=True)[:wings]
                above = [row for row in contracts if row[1] >= spot][:wings]
                symbols.extend(row[0] for row in below + above)
        return list(dict.fromkeys(symbols))

    def capture_once(self) -> int:
        symbols = self.selected_symbols()
        captured = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        rows = []
        for batch in chunks(symbols):
            page = self.client.get(self.client.settings.data_endpoint, "/v1beta1/options/snapshots",
                                   {"symbols": ",".join(batch), "feed": self.client.settings.option_feed, "limit": 1000})
            for symbol, snapshot in page.get("snapshots", {}).items():
                quote = snapshot.get("latestQuote") or snapshot.get("latest_quote") or {}
                trade = snapshot.get("latestTrade") or snapshot.get("latest_trade") or {}
                greeks = snapshot.get("greeks") or {}
                rows.append((symbol, captured, _number(quote, "t", "timestamp"),
                             _number(quote, "bp", "bidPrice", "bid_price"), _number(quote, "bs", "bidSize", "bid_size"),
                             _number(quote, "ap", "askPrice", "ask_price"), _number(quote, "as", "askSize", "ask_size"),
                             _number(trade, "t", "timestamp"), _number(trade, "p", "price"), _number(trade, "s", "size"),
                             _number(snapshot, "impliedVolatility", "implied_volatility"), greeks.get("delta"),
                             greeks.get("gamma"), greeks.get("theta"), greeks.get("vega"),
                             json.dumps(snapshot, separators=(",", ":"))))
        self.store.connection.executemany(
            "INSERT OR REPLACE INTO live_option_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        self.store.connection.execute(
            "INSERT OR REPLACE INTO snapshot_runs VALUES (?, ?, ?)",
            (captured, self.client.settings.option_feed, len(rows)))
        self.store.connection.commit()
        self.progress(f"captured {len(rows)} {self.client.settings.option_feed} option snapshots at {captured}")
        return len(rows)

    def run(self, interval_seconds: int = 3600) -> None:
        while True:
            try:
                now = datetime.now(timezone.utc)
                local = eastern_time(now.isoformat())
                minute = local.hour * 60 + local.minute
                if local.weekday() < 5 and 565 <= minute <= 965:
                    self.capture_once()
            except Exception as exc:  # Keep a long-running recorder alive after transient failures.
                self.progress(f"snapshot capture failed: {exc}")
            time.sleep(max(interval_seconds, 60))
