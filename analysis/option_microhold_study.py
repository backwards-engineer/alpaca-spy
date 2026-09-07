from __future__ import annotations

import json
import math
import sqlite3
import statistics
from collections import defaultdict
from datetime import time
from pathlib import Path

from spy_macro_data.collector import eastern_time

ROOT = Path(__file__).resolve().parents[1]
connection = sqlite3.connect(ROOT / "data" / "market_data.sqlite")


def mean(values):
    return statistics.fmean(values) if values else None


def median(values):
    return statistics.median(values) if values else None


def trimmed_mean(values, proportion=.025):
    if not values:
        return None
    ordered = sorted(values)
    trim = int(len(ordered) * proportion)
    kept = ordered[trim:len(ordered) - trim] if trim else ordered
    return mean(kept)


stock = defaultdict(dict)
stock_open = {}
for timestamp, open_, close in connection.execute(
    "SELECT timestamp,open,close FROM stock_bars_1m WHERE symbol='SPY' ORDER BY timestamp"
):
    local = eastern_time(timestamp)
    clock = local.time().replace(tzinfo=None)
    if time(9, 30) <= clock < time(16):
        day = local.date().isoformat()
        minute = local.hour * 60 + local.minute
        stock[day][minute] = float(close)
        stock_open.setdefault(day, float(open_))

query = """
WITH selected AS (
  SELECT market_date,symbol,min(target_dte) target_dte,min(actual_dte) actual_dte,
         option_type,min(strike) strike,min(spot) spot
  FROM option_selection GROUP BY market_date,symbol
)
SELECT s.market_date,s.symbol,s.target_dte,s.actual_dte,s.option_type,s.strike,s.spot,
       b.timestamp,b.close,b.volume,b.trade_count
FROM selected s JOIN option_bars_5m b ON b.symbol=s.symbol AND date(b.timestamp)=s.market_date
JOIN download_log d ON d.job_key='rich-option:'||s.market_date||':5Min:v1'
ORDER BY s.market_date,s.symbol,b.timestamp
"""

series = defaultdict(dict)
meta = {}
for day, symbol, target, actual, kind, strike, spot, timestamp, close, volume, trades in connection.execute(query):
    local = eastern_time(timestamp)
    clock = local.time().replace(tzinfo=None)
    if not time(9, 30) <= clock < time(16):
        continue
    minute = local.hour * 60 + local.minute
    key = (day, symbol)
    series[key][minute] = (float(close), float(volume or 0), int(trades or 0))
    meta[key] = (int(target), int(actual), kind, float(strike), float(spot))

bins = [(-math.inf, -0.15, "≤−0.15%"), (-0.15, -0.05, "−0.15…−0.05%"),
        (-0.05, 0.05, "−0.05…+0.05%"), (0.05, 0.15, "+0.05…+0.15%"),
        (0.15, math.inf, ">+0.15%")]
day_bins = [(-math.inf, -0.50, "≤−0.50%"), (-0.50, -0.15, "−0.50…−0.15%"),
            (-0.15, 0.15, "−0.15…+0.15%"), (0.15, 0.50, "+0.15…+0.50%"),
            (0.50, math.inf, ">+0.50%")]


def bin_label(value):
    for low, high, label in bins:
        if low < value <= high:
            return label
    return bins[-1][2]


def day_bin_label(value):
    for low, high, label in day_bins:
        if low < value <= high:
            return label
    return day_bins[-1][2]


results = {}
for hold in (5, 10, 15):
    observations = []
    raw_pairs = 0
    liquid_pairs = 0
    for key, bars in series.items():
        day, symbol = key
        target, actual, kind, strike, selection_spot = meta[key]
        direction = 1 if kind == "call" else -1
        for minute, (entry, entry_volume, entry_trades) in bars.items():
            if minute < 585 or minute + hold >= 960 or (minute - 570) % hold != 0:
                continue
            if minute + hold not in bars:
                continue
            raw_pairs += 1
            if minute - 15 not in stock[day] or minute not in stock[day]:
                continue
            exit_price, exit_volume, exit_trades = bars[minute + hold]
            current_spot = stock[day][minute]
            if (min(entry, exit_price) < 1.00 or min(entry_volume, exit_volume) < 25 or
                    min(entry_trades, exit_trades) < 3 or abs(strike / current_spot - 1) > .02):
                continue
            liquid_pairs += 1
            aligned_15 = ((stock[day][minute] / stock[day][minute - 15] - 1) * 100) * direction
            aligned_day = ((stock[day][minute] / stock_open[day] - 1) * 100) * direction
            option_prior = None
            if minute - 15 in bars and bars[minute - 15][0] >= 0.25:
                option_prior = (entry / bars[minute - 15][0] - 1) * 100
            outcome = (exit_price / entry - 1) * 100
            observations.append({"day": day, "symbol": symbol, "target": target, "kind": kind,
                                 "minute": minute, "aligned_15": aligned_15, "aligned_day": aligned_day,
                                 "option_prior_15": option_prior, "return": outcome})
    by_bin = []
    for _, _, label in bins:
        values = [row["return"] for row in observations if bin_label(row["aligned_15"]) == label]
        days = {row["day"] for row in observations if bin_label(row["aligned_15"]) == label}
        by_bin.append({"bin": label, "n": len(values), "days": len(days), "mean": mean(values),
                       "trimmed_mean": trimmed_mean(values),
                       "median": median(values), "win_rate": sum(value > 0 for value in values) / len(values) * 100 if values else None})
    by_day_move = []
    day_move_groups = defaultdict(list)
    for row in observations:
        day_move_groups[(row["day"], day_bin_label(row["aligned_day"]))].append(row["return"])
    for _, _, label in day_bins:
        values = [row["return"] for row in observations if day_bin_label(row["aligned_day"]) == label]
        by_day_move.append({"bin": label, "n": len(values), "median": median(values),
                            "trimmed_mean": trimmed_mean(values),
                            "win_rate": sum(value > 0 for value in values) / len(values) * 100 if values else None})
    day_move_spreads = []
    for day in {row["day"] for row in observations}:
        low_values = day_move_groups.get((day, "≤−0.50%"), [])
        high_values = day_move_groups.get((day, ">+0.50%"), [])
        if low_values and high_values:
            day_move_spreads.append(median(high_values) - median(low_values))
    # Reduce cross-contract dependence: average each feature bin within each day, then compare extreme bins.
    daily_bin = defaultdict(list)
    for row in observations:
        daily_bin[(row["day"], bin_label(row["aligned_15"]))].append(row["return"])
    low_daily = [mean(values) for (day, label), values in daily_bin.items() if label == "≤−0.15%"]
    high_daily = [mean(values) for (day, label), values in daily_bin.items() if label == ">+0.15%"]
    paired_spreads = []
    paired_by_period = {"train": [], "test": []}
    cutoff_day = sorted({row["day"] for row in observations})[174]
    for day in sorted({row["day"] for row in observations}):
        low_values = daily_bin.get((day, "≤−0.15%"), [])
        high_values = daily_bin.get((day, ">+0.15%"), [])
        if low_values and high_values:
            spread = median(high_values) - median(low_values)
            paired_spreads.append(spread)
            paired_by_period["train" if day <= cutoff_day else "test"].append(spread)
    results[str(hold)] = {"raw_exact_pairs": raw_pairs, "filtered_pairs": liquid_pairs,
                          "observations": len(observations), "days": len({row["day"] for row in observations}),
                          "symbols": len({row["symbol"] for row in observations}), "bins": by_bin,
                          "day_move_bins": by_day_move,
                          "day_move_paired_spread": {"n": len(day_move_spreads), "mean": mean(day_move_spreads),
                                                     "median": median(day_move_spreads),
                                                     "positive_rate": sum(value > 0 for value in day_move_spreads) / len(day_move_spreads) * 100 if day_move_spreads else None},
                          "daily_extreme_spread": (mean(high_daily) - mean(low_daily)) if high_daily and low_daily else None,
                          "low_days": len(low_daily), "high_days": len(high_daily),
                          "paired_day_median_spread": {"n": len(paired_spreads), "mean": mean(paired_spreads),
                                                       "median": median(paired_spreads),
                                                       "positive_rate": sum(value > 0 for value in paired_spreads) / len(paired_spreads) * 100 if paired_spreads else None,
                                                       "train_mean": mean(paired_by_period["train"]),
                                                       "test_mean": mean(paired_by_period["test"])},
                          "by_target": {str(target): sum(row["target"] == target for row in observations)
                                        for target in (0, 30, 60, 120)}}

coverage = {
    "complete_days": connection.execute("SELECT count(*) FROM download_log WHERE job_key LIKE 'rich-option:%:5Min:v1'").fetchone()[0],
    "five_minute_rows": connection.execute("SELECT count(*) FROM option_bars_5m").fetchone()[0],
    "selected_day_symbols_with_bars": len(series),
}
print(json.dumps({"coverage": coverage, "holds": results}, indent=2))
