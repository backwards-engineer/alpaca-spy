from __future__ import annotations

import argparse
import json
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .store import Store
from .collector import eastern_time


def regular_session(timestamp: str) -> bool:
    local = eastern_time(timestamp)
    return (local.hour, local.minute) >= (9, 30) and (local.hour, local.minute) < (16, 0)


def latest_regular_close(rows: list[dict]) -> float | None:
    for row in reversed(rows):
        if regular_session(row["timestamp"]):
            return row["close"]
    return None


def row_dicts(cursor: sqlite3.Cursor) -> list[dict]:
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


class MarketDataAPI(BaseHTTPRequestHandler):
    database: Path

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            self._json({"ok": True})
            return
        if parsed.path == "/api/year":
            year = params.get("year", [""])[0]
            if len(year) != 4 or not year.isdigit():
                self._json({"error": "year must be YYYY"}, HTTPStatus.BAD_REQUEST)
                return
            with self._connection() as connection:
                bars = row_dicts(connection.execute(
                    """SELECT timestamp,open,high,low,close FROM stock_bars
                       WHERE symbol='SPY' AND substr(timestamp,1,4)=? ORDER BY timestamp""", (year,)))
                news_counts = dict(connection.execute(
                    """SELECT substr(market_date,1,7),count(*) FROM news_articles
                       WHERE substr(market_date,1,4)=? GROUP BY 1""", (year,)).fetchall())
            by_month: dict[str, list[dict]] = {}
            for bar in bars:
                local = eastern_time(bar["timestamp"])
                if (local.hour, local.minute) >= (9, 30) and (local.hour, local.minute) < (16, 0):
                    by_month.setdefault(local.date().isoformat()[:7], []).append(bar)
            months = []
            for month, month_bars in sorted(by_month.items()):
                by_day: dict[str, list[dict]] = {}
                for bar in month_bars:
                    by_day.setdefault(eastern_time(bar["timestamp"]).date().isoformat(), []).append(bar)
                daily = list(by_day.values())
                opens = [items[0]["open"] for items in daily]
                closes = [items[-1]["close"] for items in daily]
                candles = [{"timestamp": eastern_time(items[0]["timestamp"]).date().isoformat(),
                            "open": items[0]["open"], "high": max(item["high"] for item in items),
                            "low": min(item["low"] for item in items), "close": items[-1]["close"]}
                           for items in daily]
                months.append({"month": month, "sessions": len(daily), "open": opens[0],
                               "close": closes[-1], "high": max(item["high"] for item in month_bars),
                               "low": min(item["low"] for item in month_bars),
                               "change_pct": round((closes[-1] / opens[0] - 1) * 100, 2),
                               "up_days": sum(close >= open_ for open_, close in zip(opens, closes)),
                               "closes": closes, "candles": candles, "news_count": news_counts.get(month, 0)})
            self._json({"year": year, "months": months})
            return
        if parsed.path == "/api/calendar":
            month = params.get("month", [""])[0]
            if len(month) != 7:
                self._json({"error": "month must be YYYY-MM"}, HTTPStatus.BAD_REQUEST)
                return
            with self._connection() as connection:
                bars = row_dicts(connection.execute(
                    """SELECT timestamp,open,high,low,close,volume FROM stock_bars_1m
                       WHERE symbol='SPY' AND substr(timestamp,1,7)=? ORDER BY timestamp""", (month,)))
                prior_bars = row_dicts(connection.execute(
                    """SELECT timestamp,close FROM (
                         SELECT timestamp,close FROM stock_bars_1m
                         WHERE symbol='SPY' AND timestamp < ? ORDER BY timestamp DESC LIMIT 1000
                       ) ORDER BY timestamp""", (f"{month}-01",)))
                notes = {row[0] for row in connection.execute(
                    "SELECT market_date FROM day_notes WHERE substr(market_date,1,7)=? AND trim(note)!=''", (month,))}
                news_counts = dict(connection.execute(
                    "SELECT market_date,count(*) FROM news_articles WHERE substr(market_date,1,7)=? GROUP BY market_date",
                    (month,)).fetchall())
                rich_jobs = {row[0] for row in connection.execute(
                    "SELECT substr(job_key,13,10) FROM download_log WHERE job_key LIKE ?",
                    (f"rich-option:{month}-%:5Min:v1",)).fetchall()}
                rich_coverage = {row[0]: row[1:] for row in connection.execute(
                    """SELECT s.market_date,count(DISTINCT s.symbol),
                              count(DISTINCT CASE WHEN b.symbol IS NOT NULL THEN s.symbol END),count(b.timestamp)
                       FROM option_selection s LEFT JOIN option_bars_5m b
                         ON b.symbol=s.symbol AND date(b.timestamp)=s.market_date
                       WHERE substr(s.market_date,1,7)=? GROUP BY s.market_date""", (month,)).fetchall()}
                hourly_coverage = {row[0]: row[1:] for row in connection.execute(
                    """SELECT s.market_date,count(DISTINCT s.symbol),
                              count(DISTINCT CASE WHEN b.symbol IS NOT NULL THEN s.symbol END),count(b.timestamp)
                       FROM option_selection s LEFT JOIN option_bars b
                         ON b.symbol=s.symbol AND date(b.timestamp)=s.market_date
                       WHERE substr(s.market_date,1,7)=? GROUP BY s.market_date""", (month,)).fetchall()}
            grouped_bars: dict[str, list[dict]] = {}
            for bar in bars:
                if regular_session(bar["timestamp"]):
                    local = eastern_time(bar["timestamp"])
                    grouped_bars.setdefault(local.date().isoformat(), []).append(bar)
            rows = []
            previous_close = latest_regular_close(prior_bars)
            for market_date, day_bars in sorted(grouped_bars.items()):
                sample_step = max(1, len(day_bars) // 48)
                candles = []
                for offset in range(0, len(day_bars), sample_step):
                    chunk = day_bars[offset:offset + sample_step]
                    candles.append({"timestamp": chunk[0]["timestamp"], "open": chunk[0]["open"],
                                    "high": max(bar["high"] for bar in chunk),
                                    "low": min(bar["low"] for bar in chunk), "close": chunk[-1]["close"]})
                sampled = [bar["close"] for bar in candles]
                expected, with_bars, bar_count = (rich_coverage if market_date in rich_jobs else hourly_coverage).get(
                    market_date, (0, 0, 0))
                first, last = day_bars[0], day_bars[-1]
                change_base = previous_close if previous_close is not None else first["open"]
                rows.append({"market_date": market_date, "open": first["open"], "close": last["close"],
                             "previous_close": previous_close,
                             "high": max(bar["high"] for bar in day_bars), "low": min(bar["low"] for bar in day_bars),
                             "volume": sum(bar["volume"] or 0 for bar in day_bars), "closes": sampled,
                             "candles": candles,
                             "change_pct": round((last["close"] / change_base - 1) * 100, 2),
                             "option_bars": bar_count, "option_series": with_bars,
                             "expected_option_series": expected, "option_resolution": "5m" if market_date in rich_jobs else "1h",
                             "news_count": news_counts.get(market_date, 0), "has_note": int(market_date in notes)})
                previous_close = last["close"]
            self._json({"month": month, "days": rows})
            return
        if parsed.path.startswith("/api/day/"):
            market_date = parsed.path.removeprefix("/api/day/")
            self._day(market_date)
            return
        if parsed.path.startswith("/api/features/"):
            market_date = parsed.path.removeprefix("/api/features/")
            with self._connection() as connection:
                rows = row_dicts(connection.execute(
                    """SELECT timestamp,target_dte,actual_dte,expiration_date,symbol,option_type,strike,
                              session_minute,option_close,option_momentum_5m,option_momentum_15m,
                              underlying_price,spy_momentum_5m,spy_momentum_15m,spy_momentum_30m,
                              spy_from_open_pct,spy_vwap,spy_vwap_distance_pct,spy_intraday_high,
                              spy_intraday_low,spy_high_distance_pct,spy_low_distance_pct,
                              implied_volatility,iv_change_5m,iv_change_15m,moneyness_pct,
                              volume,trade_count,catalyst_types_json,catalyst_age_minutes,
                              quote_at,bid,bid_size,ask,ask_size,mid,spread,spread_pct,
                              quote_age_seconds,quote_source
                       FROM option_features_5m WHERE market_date=?
                       ORDER BY timestamp,target_dte,option_type,strike""", (market_date,)))
                latest_capture = connection.execute(
                    "SELECT max(captured_at) FROM live_option_snapshots WHERE date(captured_at)=?", (market_date,)
                ).fetchone()[0]
            for row in rows:
                row["catalyst_types"] = json.loads(row.pop("catalyst_types_json"))
            quoted = sum(row["bid"] is not None and row["ask"] is not None for row in rows)
            self._json({"market_date": market_date, "rows": rows, "quoted_rows": quoted,
                        "latest_quote_capture": latest_capture,
                        "quote_status": "captured" if quoted else "historical_unavailable"})
            return
        if parsed.path.startswith("/api/notes/"):
            market_date = parsed.path.removeprefix("/api/notes/")
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT note, updated_at FROM day_notes WHERE market_date=?", (market_date,)
                ).fetchone()
            self._json({"market_date": market_date, "note": row[0] if row else "",
                        "updated_at": row[1] if row else None})
            return
        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def _day(self, market_date: str) -> None:
        with self._connection() as connection:
            rich_underlying = connection.execute(
                "SELECT 1 FROM stock_bars_1m WHERE symbol='SPY' AND date(timestamp)=? LIMIT 1",
                (market_date,)).fetchone() is not None
            stock_table = "stock_bars_1m" if rich_underlying else "stock_bars"
            underlying = row_dicts(connection.execute(
                f"""SELECT timestamp, open, high, low, close, volume
                   FROM {stock_table} WHERE symbol='SPY' AND date(timestamp)=?
                   ORDER BY timestamp""", (market_date,)))
            prior_underlying = row_dicts(connection.execute(
                f"""SELECT timestamp,close FROM (
                     SELECT timestamp,close FROM {stock_table}
                     WHERE symbol='SPY' AND date(timestamp) < ? ORDER BY timestamp DESC LIMIT 1000
                   ) ORDER BY timestamp""", (market_date,)))
            previous_close = latest_regular_close(prior_underlying)
            if previous_close is None and stock_table != "stock_bars":
                fallback_prior = row_dicts(connection.execute(
                    """SELECT timestamp,close FROM (
                         SELECT timestamp,close FROM stock_bars
                         WHERE symbol='SPY' AND date(timestamp) < ? ORDER BY timestamp DESC LIMIT 1000
                       ) ORDER BY timestamp""", (market_date,)))
                previous_close = latest_regular_close(fallback_prior)
            rich_options = connection.execute(
                "SELECT 1 FROM download_log WHERE job_key=? LIMIT 1",
                (f"rich-option:{market_date}:5Min:v1",)
            ).fetchone() is not None
            if rich_options:
                options = row_dicts(connection.execute(
                    """
                SELECT s.target_dte, s.actual_dte, s.expiration_date, s.symbol,
                       s.option_type, s.strike, s.spot, s.side, s.rank_from_spot,
                       b.timestamp, b.open, b.high, b.low, b.close, b.volume,
                       m.underlying_price, m.implied_volatility, m.delta, m.gamma, m.theta, m.vega,
                       cm.open_interest, cm.open_interest_date, cm.close_price contract_close,
                       cm.close_price_date contract_close_date
                FROM option_selection s
                LEFT JOIN option_bars_5m b ON b.symbol=s.symbol AND date(b.timestamp)=s.market_date
                LEFT JOIN option_metrics_5m m ON m.symbol=b.symbol AND m.timestamp=b.timestamp
                LEFT JOIN option_contract_metrics cm ON cm.symbol=s.symbol
                WHERE s.market_date=?
                ORDER BY s.target_dte, s.option_type, s.strike, b.timestamp
                """, (market_date,)))
            else:
                options = row_dicts(connection.execute(
                    """
                SELECT s.target_dte, s.actual_dte, s.expiration_date, s.symbol,
                       s.option_type, s.strike, s.spot, s.side, s.rank_from_spot,
                       b.timestamp, b.open, b.high, b.low, b.close, b.volume,
                       NULL underlying_price, NULL implied_volatility, NULL delta, NULL gamma,
                       NULL theta, NULL vega, cm.open_interest, cm.open_interest_date,
                       cm.close_price contract_close, cm.close_price_date contract_close_date
                FROM option_selection s
                LEFT JOIN option_bars b ON b.symbol=s.symbol AND date(b.timestamp)=s.market_date
                LEFT JOIN option_contract_metrics cm ON cm.symbol=s.symbol
                WHERE s.market_date=?
                ORDER BY s.target_dte, s.option_type, s.strike, b.timestamp
                """, (market_date,)))
            note = connection.execute(
                "SELECT note, updated_at FROM day_notes WHERE market_date=?", (market_date,)
            ).fetchone()
            adjacent = connection.execute(
                """SELECT
                     max(CASE WHEN market_date < ? THEN market_date END) previous_day,
                     min(CASE WHEN market_date > ? THEN market_date END) next_day
                   FROM (SELECT DISTINCT market_date FROM option_selection)""",
                (market_date, market_date),
            ).fetchone()
            news = row_dicts(connection.execute(
                """SELECT article_id, window_key, window_rank, published_at, headline,
                          summary, author, source, url, categories_json,
                          matched_keywords_json, relevance_score
                   FROM news_articles WHERE market_date=?
                   ORDER BY CASE window_key
                     WHEN 'pre_market' THEN 1 WHEN 'late_morning' THEN 2
                     WHEN 'afternoon' THEN 3 ELSE 4 END, window_rank""",
                (market_date,),
            ))
        underlying = [row for row in underlying if regular_session(row["timestamp"])]
        grouped: dict[str, dict] = {}
        for row in options:
            symbol = row["symbol"]
            item = grouped.setdefault(symbol, {
                key: row[key] for key in (
                    "target_dte", "actual_dte", "expiration_date", "symbol", "option_type",
                    "strike", "spot", "side", "rank_from_spot", "open_interest",
                    "open_interest_date", "contract_close", "contract_close_date"
                )
            })
            item.setdefault("bars", [])
            if row["timestamp"] and regular_session(row["timestamp"]):
                item["bars"].append({key: row[key] for key in (
                    "timestamp", "open", "high", "low", "close", "volume", "underlying_price",
                    "implied_volatility", "delta", "gamma", "theta", "vega"
                )})
        for item in news:
            item["categories"] = json.loads(item.pop("categories_json"))
            item["matched_keywords"] = json.loads(item.pop("matched_keywords_json"))
        self._json({
            "market_date": market_date,
            "underlying": underlying,
            "previous_close": previous_close,
            "options": list(grouped.values()),
            "note": note[0] if note else "",
            "note_updated_at": note[1] if note else None,
            "previous_day": adjacent[0], "next_day": adjacent[1],
            "news": news,
            "resolution": {"underlying": "1Min SIP" if rich_underlying else "1Hour IEX",
                           "options": "5Min trades" if rich_options else "1Hour trades"},
        })

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/notes/"):
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        market_date = parsed.path.removeprefix("/api/notes/")
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 100_000)
            payload = json.loads(self.rfile.read(length) or b"{}")
            note = str(payload.get("note", ""))
        except (ValueError, json.JSONDecodeError):
            self._json({"error": "invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO day_notes(market_date, note, updated_at) VALUES (?, ?, datetime('now'))
                   ON CONFLICT(market_date) DO UPDATE SET note=excluded.note, updated_at=datetime('now')""",
                (market_date, note),
            )
            connection.commit()
            updated = connection.execute(
                "SELECT updated_at FROM day_notes WHERE market_date=?", (market_date,)
            ).fetchone()[0]
        self._json({"market_date": market_date, "note": note, "updated_at": updated})

    def log_message(self, format: str, *args: object) -> None:
        print(f"api {self.address_string()} {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local SPY research API")
    parser.add_argument("--db", type=Path, default=Path("data/market_data.sqlite"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    Store(args.db).close()  # Apply schema upgrades before serving.
    MarketDataAPI.database = args.db.resolve()
    server = ThreadingHTTPServer((args.host, args.port), MarketDataAPI)
    print(f"SPY research API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
