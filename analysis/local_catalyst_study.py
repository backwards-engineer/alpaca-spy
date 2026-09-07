from __future__ import annotations

import json
import math
import random
import sqlite3
import statistics
from collections import defaultdict
from datetime import date, time
from pathlib import Path

from spy_macro_data.collector import eastern_time

ROOT = Path(__file__).resolve().parents[1]
connection = sqlite3.connect(ROOT / "data" / "market_data.sqlite")


def mean(values):
    return statistics.fmean(values) if values else math.nan


def median(values):
    return statistics.median(values) if values else math.nan


def bootstrap_ci(values, iterations=5000):
    if len(values) < 3:
        return [math.nan, math.nan]
    rng = random.Random(7331 + len(values))
    means = sorted(mean(rng.choices(values, k=len(values))) for _ in range(iterations))
    return [means[int(iterations * .025)], means[int(iterations * .975)]]


def permutation_p(a, b, iterations=5000):
    if len(a) < 2 or len(b) < 2:
        return math.nan
    observed = abs(mean(a) - mean(b))
    joined = list(a) + list(b)
    rng = random.Random(991 + len(a))
    hits = 0
    for _ in range(iterations):
        rng.shuffle(joined)
        if abs(mean(joined[:len(a)]) - mean(joined[len(a):])) >= observed:
            hits += 1
    return (hits + 1) / (iterations + 1)


bars_by_day = defaultdict(list)
for row in connection.execute(
    "SELECT timestamp,open,high,low,close,volume FROM stock_bars_1m WHERE symbol='SPY' ORDER BY timestamp"
):
    local = eastern_time(row[0])
    if time(9, 30) <= local.time().replace(tzinfo=None) < time(16):
        bars_by_day[local.date().isoformat()].append((local.hour * 60 + local.minute, *map(float, row[1:])))

daily = {}
minute_close = {}
for day, bars in bars_by_day.items():
    bars.sort()
    daily[day] = {
        "open": bars[0][1], "close": bars[-1][4],
        "return": (bars[-1][4] / bars[0][1] - 1) * 100,
        "range": (max(row[2] for row in bars) / min(row[3] for row in bars) - 1) * 100,
    }
    minute_close[day] = {row[0]: row[4] for row in bars}

market_days = sorted(daily)
next_day = {day: market_days[index + 1] for index, day in enumerate(market_days[:-1])}
previous_day = {day: market_days[index - 1] for index, day in enumerate(market_days) if index > 0}
for day in market_days:
    prior = previous_day.get(day)
    if prior:
        daily[day]["overnight"] = (daily[day]["open"] / daily[prior]["close"] - 1) * 100
        daily[day]["close_to_close"] = (daily[day]["close"] / daily[prior]["close"] - 1) * 100


def catalyst_groups(categories, keywords, text):
    result = set(categories)
    lower = text.lower()
    keyword_set = {item.lower() for item in keywords}
    if "tariff" in lower or "trade war" in lower or "tariff" in keyword_set:
        result.add("tariff")
    if "rate cut" in lower or "rate cut" in keyword_set:
        result.add("rate_cut")
    if "fomc" in lower or "fomc" in keyword_set:
        result.add("fomc")
    if keyword_set & {"cpi", "consumer price index", "ppi", "producer price index", "pce price", "core pce"}:
        result.add("price_data")
    if keyword_set & {"jobs report", "payrolls", "nonfarm payroll", "jobless claims", "jolts", "adp employment", "unemployment"}:
        result.add("jobs_data")
    return result


events = []
for row in connection.execute(
    "SELECT market_date,published_at,headline,summary,categories_json,matched_keywords_json FROM news_articles"
):
    day, timestamp, headline, summary, categories_json, keywords_json = row
    local = eastern_time(timestamp)
    groups = catalyst_groups(json.loads(categories_json), json.loads(keywords_json), f"{headline} {summary or ''}")
    events.append({"day": day, "minute": local.hour * 60 + local.minute,
                   "groups": groups, "headline": headline})

labels = {
    "fed": "Fed / Powell", "fomc": "FOMC", "rate_cut": "Rate-cut talk",
    "inflation": "Inflation", "price_data": "CPI / PCE / PPI",
    "jobs": "Labor market", "jobs_data": "Jobs releases", "trump": "Trump",
    "tariff": "Tariffs / trade",
}

# Presence by day, regardless of publication time (descriptive association only).
presence = defaultdict(set)
for event in events:
    presence[event["day"]].update(event["groups"])

daily_results = []
all_returns = [daily[day]["return"] for day in market_days]
for key, label in labels.items():
    event_returns = [daily[day]["return"] for day in market_days if key in presence[day]]
    other_returns = [daily[day]["return"] for day in market_days if key not in presence[day]]
    daily_results.append({"key": key, "label": label, "n": len(event_returns),
                          "mean": mean(event_returns), "median": median(event_returns),
                          "up_rate": sum(value > 0 for value in event_returns) / len(event_returns) * 100 if event_returns else math.nan,
                          "other_mean": mean(other_returns), "difference": mean(event_returns) - mean(other_returns),
                          "p": permutation_p(event_returns, other_returns)})

# Pre-market articles strictly before 9:30 ET, one observation per category/day.
premarket_days = defaultdict(set)
after_close_days = defaultdict(set)
intraday_first = {}
for event in events:
    for key in event["groups"]:
        if 420 <= event["minute"] < 570:
            premarket_days[key].add(event["day"])
        elif 960 <= event["minute"] < 1200:
            after_close_days[key].add(event["day"])
        elif 570 <= event["minute"] <= 930:
            intraday_first[(event["day"], key)] = min(event["minute"], intraday_first.get((event["day"], key), 2000))

premarket_results = []
for key, label in labels.items():
    event_returns = [daily[day]["return"] for day in sorted(premarket_days[key]) if day in daily]
    gap_returns = [daily[day]["overnight"] for day in sorted(premarket_days[key]) if "overnight" in daily.get(day, {})]
    close_returns = [daily[day]["close_to_close"] for day in sorted(premarket_days[key]) if "close_to_close" in daily.get(day, {})]
    control = [daily[day]["return"] for day in market_days if day not in premarket_days[key]]
    gap_control = [daily[day]["overnight"] for day in market_days if day not in premarket_days[key] and "overnight" in daily[day]]
    premarket_results.append({"key": key, "label": label, "n": len(event_returns),
                              "mean": mean(event_returns), "median": median(event_returns),
                              "up_rate": sum(value > 0 for value in event_returns) / len(event_returns) * 100 if event_returns else math.nan,
                              "gap_mean": mean(gap_returns), "gap_up_rate": sum(value > 0 for value in gap_returns) / len(gap_returns) * 100 if gap_returns else math.nan,
                              "close_to_close_mean": mean(close_returns), "gap_difference": mean(gap_returns) - mean(gap_control),
                              "difference": mean(event_returns) - mean(control),
                              "ci": bootstrap_ci(event_returns), "p": permutation_p(event_returns, control)})


def close_at(day, minute):
    values = minute_close.get(day, {})
    available = [key for key in values if key >= minute]
    return values[min(available)] if available else None


intraday_results = []
for key, label in labels.items():
    excess_60 = []
    raw_60 = []
    for (day, category), start in intraday_first.items():
        if category != key or start + 60 >= 960:
            continue
        start_price, end_price = close_at(day, start), close_at(day, start + 60)
        if not start_price or not end_price:
            continue
        event_return = (end_price / start_price - 1) * 100
        matched = []
        for control_day in market_days:
            c0, c1 = close_at(control_day, start), close_at(control_day, start + 60)
            if c0 and c1:
                matched.append((c1 / c0 - 1) * 100)
        raw_60.append(event_return)
        excess_60.append(event_return - mean(matched))
    intraday_results.append({"key": key, "label": label, "n": len(raw_60),
                             "mean_60": mean(raw_60), "excess_60": mean(excess_60),
                             "up_rate": sum(value > 0 for value in raw_60) / len(raw_60) * 100 if raw_60 else math.nan,
                             "ci": bootstrap_ci(excess_60)})

after_close_results = []
for key, label in labels.items():
    returns = [daily[next_day[day]]["return"] for day in sorted(after_close_days[key]) if day in next_day]
    gaps = [daily[next_day[day]]["overnight"] for day in sorted(after_close_days[key]) if day in next_day and "overnight" in daily[next_day[day]]]
    event_next_days = {next_day[day] for day in after_close_days[key] if day in next_day}
    control = [daily[day]["return"] for day in market_days if day not in event_next_days]
    after_close_results.append({"key": key, "label": label, "n": len(returns),
                                "next_mean": mean(returns),
                                "gap_mean": mean(gaps), "difference": mean(returns) - mean(control),
                                "up_rate": sum(value > 0 for value in returns) / len(returns) * 100 if returns else math.nan,
                                "ci": bootstrap_ci(returns), "p": permutation_p(returns, control)})

# Market regime summaries.
month_returns = []
for month in sorted({day[:7] for day in market_days}):
    days = [day for day in market_days if day.startswith(month)]
    month_returns.append({"month": month, "return": (daily[days[-1]]["close"] / daily[days[0]]["open"] - 1) * 100,
                          "up_rate": sum(daily[day]["return"] > 0 for day in days) / len(days) * 100,
                          "avg_range": mean([daily[day]["range"] for day in days])})


def correlation(left, right):
    if len(left) < 3:
        return math.nan
    left_mean, right_mean = mean(left), mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    denominator = math.sqrt(sum((x - left_mean) ** 2 for x in left) * sum((y - right_mean) ** 2 for y in right))
    return numerator / denominator if denominator else math.nan


news_counts = dict(connection.execute("SELECT market_date,count(*) FROM news_articles GROUP BY market_date"))
weekday_results = []
for weekday in range(5):
    values = [daily[day]["return"] for day in market_days if date.fromisoformat(day).weekday() == weekday]
    ranges = [daily[day]["range"] for day in market_days if date.fromisoformat(day).weekday() == weekday]
    weekday_results.append({"weekday": ["Mon", "Tue", "Wed", "Thu", "Fri"][weekday], "n": len(values),
                            "mean": mean(values), "up_rate": sum(value > 0 for value in values) / len(values) * 100,
                            "avg_range": mean(ranges)})
range_pairs = [(daily[market_days[index - 1]]["range"], daily[market_days[index]]["range"])
               for index in range(1, len(market_days))]
news_days = [day for day in market_days if day in news_counts]
general = {
    "mean_overnight": mean([daily[day]["overnight"] for day in market_days if "overnight" in daily[day]]),
    "mean_close_to_close": mean([daily[day]["close_to_close"] for day in market_days if "close_to_close" in daily[day]]),
    "range_persistence": correlation([row[0] for row in range_pairs], [row[1] for row in range_pairs]),
    "news_count_abs_return_corr": correlation([news_counts[day] for day in news_days], [abs(daily[day]["return"]) for day in news_days]),
    "news_count_range_corr": correlation([news_counts[day] for day in news_days], [daily[day]["range"] for day in news_days]),
    "weekdays": weekday_results,
}

# A conservative 30D near-the-money IV proxy: median of rank-1 calls/puts from 9:45–10:30 ET.
iv_observations = defaultdict(list)
for day, timestamp, iv in connection.execute(
    """SELECT s.market_date,m.timestamp,m.implied_volatility
       FROM option_selection s JOIN option_metrics_5m m ON m.symbol=s.symbol
         AND date(m.timestamp)=s.market_date
       WHERE s.target_dte=30 AND s.rank_from_spot=1
         AND m.implied_volatility BETWEEN 0.01 AND 3.0"""
):
    local = eastern_time(timestamp)
    minute = local.hour * 60 + local.minute
    if 585 <= minute <= 630:
        iv_observations[day].append(float(iv))
daily_iv = {day: median(values) for day, values in iv_observations.items() if values}
iv_days = sorted(day for day in daily_iv if day in daily)
iv_next_days = [day for day in iv_days if day in next_day]
general["options"] = {
    "days": len(iv_days),
    "median_30d_iv": median(list(daily_iv.values())) * 100,
    "iv_same_day_range_corr": correlation([daily_iv[day] for day in iv_days], [daily[day]["range"] for day in iv_days]),
    "iv_next_day_abs_return_corr": correlation([daily_iv[day] for day in iv_next_days], [abs(daily[next_day[day]]["return"]) for day in iv_next_days]),
}

output = {"period": [market_days[0], market_days[-1]], "sessions": len(market_days),
          "market": {"mean_daily": mean(all_returns), "median_daily": median(all_returns),
                     "up_rate": sum(value > 0 for value in all_returns) / len(all_returns) * 100,
                     "total_return": (daily[market_days[-1]]["close"] / daily[market_days[0]]["open"] - 1) * 100,
                     "avg_range": mean([daily[day]["range"] for day in market_days])},
          "daily": daily_results, "premarket": premarket_results,
          "intraday": intraday_results, "after_close": after_close_results,
          "months": month_returns, "general": general}


def clean(value):
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


print(json.dumps(clean(output), indent=2, allow_nan=False))
