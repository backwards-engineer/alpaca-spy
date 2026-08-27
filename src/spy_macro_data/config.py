from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    key: str
    secret: str
    trading_endpoint: str
    data_endpoint: str = "https://data.alpaca.markets"
    option_feed: str = "indicative"


def load_settings(path: Path) -> Settings:
    """Load the user's simple key/value secrets file without external packages."""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        delimiter = "=" if "=" in line else ":" if ":" in line else None
        if delimiter is None:
            continue
        name, value = line.split(delimiter, 1)
        values[name.strip().lower()] = value.strip().strip('"').strip("'")
    missing = [name for name in ("key", "secret") if not values.get(name)]
    if missing:
        raise ValueError(f"Missing {', '.join(missing)} in {path}")
    trading_endpoint = values.get("endpoint", "https://paper-api.alpaca.markets").rstrip("/")
    # Many Alpaca examples store the trading endpoint with `/v2` included.  The
    # client appends versioned resource paths itself, so normalize that form.
    if trading_endpoint.endswith("/v2"):
        trading_endpoint = trading_endpoint[:-3]
    return Settings(
        key=values["key"],
        secret=values["secret"],
        trading_endpoint=trading_endpoint,
        option_feed=values.get("option_feed", "indicative").lower(),
    )
