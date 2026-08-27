from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

from .config import Settings


class AlpacaError(RuntimeError):
    pass


class AlpacaClient:
    def __init__(self, settings: Settings, timeout: float = 60.0) -> None:
        self.settings = settings
        self.timeout = timeout

    def get(self, base: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        clean = {k: str(v) for k, v in params.items() if v is not None}
        url = f"{base.rstrip('/')}/{path.lstrip('/')}?{urllib.parse.urlencode(clean)}"
        request = urllib.request.Request(
            url,
            headers={
                "APCA-API-KEY-ID": self.settings.key,
                "APCA-API-SECRET-KEY": self.settings.secret,
                "Accept": "application/json",
                "User-Agent": "spy-macro-lab/0.1",
            },
        )
        for attempt in range(7):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                if exc.code == 429 or 500 <= exc.code < 600:
                    time.sleep(min(30.0, (2**attempt) + random.random()))
                    continue
                raise AlpacaError(f"Alpaca returned HTTP {exc.code}: {detail}") from exc
            except (TimeoutError, urllib.error.URLError) as exc:
                if attempt == 6:
                    raise AlpacaError(f"Alpaca request failed after retries: {exc}") from exc
                time.sleep(min(30.0, (2**attempt) + random.random()))
        raise AssertionError("unreachable")

    def pages(
        self,
        base: str,
        path: str,
        params: dict[str, Any],
        token_field: str = "next_page_token",
    ) -> Iterator[dict[str, Any]]:
        token: str | None = None
        while True:
            page_params = dict(params)
            if token:
                page_params["page_token"] = token
            page = self.get(base, path, page_params)
            yield page
            token = page.get(token_field) or page.get("page_token")
            if not token:
                break

