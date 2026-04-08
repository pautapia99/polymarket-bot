"""
Cliente HTTP minimalista para los endpoints de leaderboard y datos
de Polymarket. Solo lectura, no requiere auth.

Endpoints descubiertos empíricamente:
  GET https://lb-api.polymarket.com/profit?window={1d|7d|30d}&limit=N
  GET https://lb-api.polymarket.com/volume?window=...&limit=N
  GET https://data-api.polymarket.com/trades?user=<wallet>&limit=N
  GET https://data-api.polymarket.com/positions?user=<wallet>
  GET https://data-api.polymarket.com/activity?user=<wallet>
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

LB_URL = "https://lb-api.polymarket.com"
DATA_URL = "https://data-api.polymarket.com"
UA = {"User-Agent": "polybot-tracker/0.1"}


def _get(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_top_profit(window: str = "7d", limit: int = 100) -> list[dict]:
    """Top traders por PnL en la ventana indicada (1d, 7d, 30d)."""
    qs = urllib.parse.urlencode({"window": window, "limit": limit})
    return _get(f"{LB_URL}/profit?{qs}")


def fetch_top_volume(window: str = "7d", limit: int = 100) -> list[dict]:
    qs = urllib.parse.urlencode({"window": window, "limit": limit})
    return _get(f"{LB_URL}/volume?{qs}")


def fetch_user_trades(wallet: str, limit: int = 50) -> list[dict]:
    qs = urllib.parse.urlencode({"user": wallet, "limit": limit})
    return _get(f"{DATA_URL}/trades?{qs}")


def fetch_user_positions(wallet: str) -> list[dict]:
    qs = urllib.parse.urlencode({"user": wallet})
    return _get(f"{DATA_URL}/positions?{qs}")
