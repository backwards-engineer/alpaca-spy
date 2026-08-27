from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from .alpaca import AlpacaClient
from .collector import Collector
from .config import load_settings
from .store import Store
from .news_collector import NewsCollector
from .rich_collector import RichCollector
from .snapshot_recorder import SnapshotRecorder
from .feature_builder import FeatureBuilder


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Cache historical SPY/options data locally")
    result.add_argument("command", choices=("check", "collect", "rich", "features", "snapshot", "news", "summary"))
    result.add_argument("--start", type=date.fromisoformat, default=date.today() - timedelta(days=365))
    result.add_argument("--end", type=date.fromisoformat, default=date.today())
    result.add_argument("--secrets", type=Path, default=Path("secrets.txt"))
    result.add_argument("--db", type=Path, default=Path("data/market_data.sqlite"))
    result.add_argument("--force", action="store_true", help="Redownload completed news days")
    result.add_argument("--interval", type=int, default=0, help="Snapshot interval in seconds; zero captures once")
    return result


def main() -> None:
    args = parser().parse_args()
    store = Store(args.db)
    try:
        if args.command == "summary":
            for table in ("stock_bars", "stock_bars_1m", "option_contracts", "option_contract_metrics",
                          "option_selection", "option_bars", "option_bars_5m", "option_metrics_5m",
                          "option_features_5m", "live_option_snapshots", "download_log"):
                count = store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                print(f"{table}: {count:,}")
            return
        settings = load_settings(args.secrets)
        client = AlpacaClient(settings)
        if args.command == "check":
            account = client.get(settings.trading_endpoint, "/v2/account", {})
            print(f"credentials valid; account status={account.get('status', 'unknown')}")
            return
        if args.command == "news":
            NewsCollector(client, store).collect(args.start, args.end, force=args.force)
            return
        if args.command == "rich":
            RichCollector(client, store).collect(args.start, args.end)
            return
        if args.command == "snapshot":
            recorder = SnapshotRecorder(client, store)
            recorder.run(args.interval) if args.interval else recorder.capture_once()
            return
        if args.command == "features":
            FeatureBuilder(store).build(args.start, args.end, force=args.force)
            return
        Collector(client, store).collect(args.start, args.end)
    finally:
        store.close()


if __name__ == "__main__":
    main()
