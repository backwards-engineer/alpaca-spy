from __future__ import annotations

import math


def _cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def _price(kind: str, spot: float, strike: float, years: float,
           rate: float, dividend: float, sigma: float) -> float:
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - dividend + 0.5 * sigma * sigma) * years) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    if kind == "call":
        return spot * math.exp(-dividend * years) * _cdf(d1) - strike * math.exp(-rate * years) * _cdf(d2)
    return strike * math.exp(-rate * years) * _cdf(-d2) - spot * math.exp(-dividend * years) * _cdf(-d1)


def implied_vol_and_greeks(kind: str, spot: float, strike: float, years: float,
                           market_price: float, rate: float = 0.0425,
                           dividend: float = 0.012) -> dict[str, float] | None:
    """Return Black-Scholes IV and Greeks, with theta/day and vega/vol-point."""
    if kind not in {"call", "put"} or min(spot, strike, years, market_price) <= 0:
        return None
    discounted_spot = spot * math.exp(-dividend * years)
    discounted_strike = strike * math.exp(-rate * years)
    intrinsic = max(0.0, discounted_spot - discounted_strike) if kind == "call" else max(0.0, discounted_strike - discounted_spot)
    upper = discounted_spot if kind == "call" else discounted_strike
    if market_price < intrinsic - 0.02 or market_price > upper + 0.02:
        return None
    low, high = 0.0001, 5.0
    if _price(kind, spot, strike, years, rate, dividend, high) < market_price:
        return None
    for _ in range(64):
        mid = (low + high) / 2.0
        if _price(kind, spot, strike, years, rate, dividend, mid) < market_price:
            low = mid
        else:
            high = mid
    sigma = (low + high) / 2.0
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - dividend + 0.5 * sigma * sigma) * years) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    discount_q = math.exp(-dividend * years)
    discount_r = math.exp(-rate * years)
    delta = discount_q * _cdf(d1) if kind == "call" else discount_q * (_cdf(d1) - 1.0)
    gamma = discount_q * _pdf(d1) / (spot * sigma * root_t)
    common = -(spot * discount_q * _pdf(d1) * sigma) / (2.0 * root_t)
    if kind == "call":
        theta_year = common - rate * strike * discount_r * _cdf(d2) + dividend * spot * discount_q * _cdf(d1)
    else:
        theta_year = common + rate * strike * discount_r * _cdf(-d2) - dividend * spot * discount_q * _cdf(-d1)
    vega = spot * discount_q * _pdf(d1) * root_t / 100.0
    return {"implied_volatility": sigma, "delta": delta, "gamma": gamma,
            "theta": theta_year / 365.0, "vega": vega}
