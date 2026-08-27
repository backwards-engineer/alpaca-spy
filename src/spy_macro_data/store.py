from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS stock_bars (
  symbol TEXT NOT NULL, timestamp TEXT NOT NULL, open REAL, high REAL, low REAL,
  close REAL, volume REAL, trade_count INTEGER, vwap REAL,
  PRIMARY KEY (symbol, timestamp)
);
CREATE TABLE IF NOT EXISTS stock_bars_1m (
  symbol TEXT NOT NULL, timestamp TEXT NOT NULL, open REAL, high REAL, low REAL,
  close REAL, volume REAL, trade_count INTEGER, vwap REAL,
  PRIMARY KEY (symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_stock_bars_1m_date ON stock_bars_1m(date(timestamp));
CREATE TABLE IF NOT EXISTS option_contracts (
  symbol TEXT PRIMARY KEY, expiration_date TEXT NOT NULL, option_type TEXT NOT NULL,
  strike REAL NOT NULL, status TEXT, raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contract_lookup
  ON option_contracts(expiration_date, option_type, strike);
CREATE TABLE IF NOT EXISTS option_selection (
  market_date TEXT NOT NULL, target_dte INTEGER NOT NULL, actual_dte INTEGER NOT NULL,
  expiration_date TEXT NOT NULL, symbol TEXT NOT NULL, option_type TEXT NOT NULL,
  strike REAL NOT NULL, spot REAL NOT NULL, side TEXT NOT NULL, rank_from_spot INTEGER NOT NULL,
  PRIMARY KEY (market_date, target_dte, symbol)
);
CREATE TABLE IF NOT EXISTS option_bars (
  symbol TEXT NOT NULL, timestamp TEXT NOT NULL, open REAL, high REAL, low REAL,
  close REAL, volume REAL, trade_count INTEGER, vwap REAL,
  PRIMARY KEY (symbol, timestamp)
);
CREATE TABLE IF NOT EXISTS option_bars_5m (
  symbol TEXT NOT NULL, timestamp TEXT NOT NULL, open REAL, high REAL, low REAL,
  close REAL, volume REAL, trade_count INTEGER, vwap REAL,
  PRIMARY KEY (symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_option_bars_5m_date ON option_bars_5m(date(timestamp));
CREATE TABLE IF NOT EXISTS option_contract_metrics (
  symbol TEXT PRIMARY KEY,
  open_interest INTEGER,
  open_interest_date TEXT,
  close_price REAL,
  close_price_date TEXT
);
CREATE TABLE IF NOT EXISTS option_metrics_5m (
  symbol TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  underlying_price REAL NOT NULL,
  implied_volatility REAL,
  delta REAL,
  gamma REAL,
  theta REAL,
  vega REAL,
  risk_free_rate REAL NOT NULL,
  dividend_yield REAL NOT NULL,
  model TEXT NOT NULL,
  PRIMARY KEY (symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_option_metrics_5m_date ON option_metrics_5m(date(timestamp));
CREATE TABLE IF NOT EXISTS live_option_snapshots (
  symbol TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  quote_at TEXT,
  bid REAL,
  bid_size REAL,
  ask REAL,
  ask_size REAL,
  trade_at TEXT,
  trade_price REAL,
  trade_size REAL,
  implied_volatility REAL,
  delta REAL,
  gamma REAL,
  theta REAL,
  vega REAL,
  raw_json TEXT NOT NULL,
  PRIMARY KEY (symbol, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_live_snapshots_captured
  ON live_option_snapshots(captured_at, symbol);
CREATE INDEX IF NOT EXISTS idx_live_snapshots_symbol_captured
  ON live_option_snapshots(symbol, captured_at);
CREATE TABLE IF NOT EXISTS snapshot_runs (
  captured_at TEXT PRIMARY KEY,
  feed TEXT NOT NULL,
  symbol_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS option_features_5m (
  market_date TEXT NOT NULL,
  target_dte INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  actual_dte INTEGER NOT NULL,
  expiration_date TEXT NOT NULL,
  option_type TEXT NOT NULL,
  strike REAL NOT NULL,
  session_minute INTEGER NOT NULL,
  option_close REAL NOT NULL,
  option_momentum_5m REAL,
  option_momentum_15m REAL,
  underlying_price REAL NOT NULL,
  spy_momentum_5m REAL,
  spy_momentum_15m REAL,
  spy_momentum_30m REAL,
  spy_from_open_pct REAL,
  spy_vwap REAL,
  spy_vwap_distance_pct REAL,
  spy_intraday_high REAL,
  spy_intraday_low REAL,
  spy_high_distance_pct REAL,
  spy_low_distance_pct REAL,
  implied_volatility REAL,
  iv_change_5m REAL,
  iv_change_15m REAL,
  moneyness_pct REAL NOT NULL,
  volume REAL,
  trade_count INTEGER,
  catalyst_types_json TEXT NOT NULL DEFAULT '[]',
  catalyst_age_minutes REAL,
  quote_at TEXT,
  bid REAL,
  bid_size REAL,
  ask REAL,
  ask_size REAL,
  mid REAL,
  spread REAL,
  spread_pct REAL,
  quote_age_seconds REAL,
  quote_source TEXT,
  PRIMARY KEY (market_date, target_dte, symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_option_features_day_time
  ON option_features_5m(market_date, timestamp, target_dte);
CREATE INDEX IF NOT EXISTS idx_option_features_symbol_time
  ON option_features_5m(symbol, timestamp);
CREATE TABLE IF NOT EXISTS download_log (
  job_key TEXT PRIMARY KEY, completed_at TEXT NOT NULL, row_count INTEGER NOT NULL,
  details TEXT
);
CREATE TABLE IF NOT EXISTS day_notes (
  market_date TEXT PRIMARY KEY,
  note TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS news_articles (
  article_id TEXT PRIMARY KEY,
  market_date TEXT NOT NULL,
  window_key TEXT NOT NULL,
  window_rank INTEGER NOT NULL,
  published_at TEXT NOT NULL,
  updated_at TEXT,
  headline TEXT NOT NULL,
  summary TEXT,
  author TEXT,
  source TEXT,
  url TEXT,
  symbols_json TEXT NOT NULL DEFAULT '[]',
  categories_json TEXT NOT NULL,
  matched_keywords_json TEXT NOT NULL,
  relevance_score INTEGER NOT NULL,
  content_text TEXT
);
CREATE INDEX IF NOT EXISTS idx_news_market_window_score
  ON news_articles(market_date, window_key, relevance_score DESC);
CREATE TABLE IF NOT EXISTS news_download_log (
  market_date TEXT PRIMARY KEY,
  completed_at TEXT NOT NULL,
  candidates_scanned INTEGER NOT NULL,
  articles_saved INTEGER NOT NULL
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30)
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def done(self, job_key: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM download_log WHERE job_key = ?", (job_key,)
        ).fetchone() is not None

    def finish(self, job_key: str, count: int, details: str = "") -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO download_log VALUES (?, datetime('now'), ?, ?)",
            (job_key, count, details),
        )
        self.connection.commit()

    def upsert_bars(self, table: str, symbol: str, bars: list[dict[str, Any]]) -> int:
        if table not in {"stock_bars", "option_bars", "stock_bars_1m", "option_bars_5m"}:
            raise ValueError("invalid bar table")
        rows = [
            (symbol, b["t"], b.get("o"), b.get("h"), b.get("l"), b.get("c"),
             b.get("v"), b.get("n"), b.get("vw"))
            for b in bars
        ]
        self.connection.executemany(
            f"INSERT OR REPLACE INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
        self.connection.commit()
        return len(rows)

    def upsert_bar_map(self, table: str, bars_by_symbol: dict[str, list[dict[str, Any]]]) -> int:
        if table not in {"stock_bars", "option_bars", "stock_bars_1m", "option_bars_5m"}:
            raise ValueError("invalid bar table")
        rows = [
            (symbol, bar["t"], bar.get("o"), bar.get("h"), bar.get("l"), bar.get("c"),
             bar.get("v"), bar.get("n"), bar.get("vw"))
            for symbol, bars in bars_by_symbol.items() for bar in bars
        ]
        self.connection.executemany(
            f"INSERT OR REPLACE INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
        self.connection.commit()
        return len(rows)

    def upsert_contracts(self, contracts: list[dict[str, Any]]) -> int:
        rows = [
            (c["symbol"], c["expiration_date"], c["type"], float(c["strike_price"]),
             c.get("status"), json.dumps(c, separators=(",", ":")))
            for c in contracts
        ]
        self.connection.executemany(
            "INSERT OR REPLACE INTO option_contracts VALUES (?, ?, ?, ?, ?, ?)", rows
        )
        self.connection.commit()
        return len(rows)
