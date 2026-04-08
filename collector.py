"""
Recolector multi-mercado de Polymarket.

Cada N segundos consulta los TOP-K mercados activos por volumen 24h en la
Gamma API y guarda un snapshot por outcome (precio, volumen, liquidez).

No requiere wallet ni autenticación. Pensado para correr en segundo plano
durante semanas y construir un dataset histórico que luego usaremos para
backtesting y optimización de parámetros.

Variables de entorno:
  COLLECTOR_LIMIT     número de mercados a vigilar (default 50)
  COLLECTOR_INTERVAL  segundos entre snapshots (default 60)
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request

import storage

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
DEFAULT_LIMIT = 50
DEFAULT_INTERVAL = 60

log = logging.getLogger("collector")


def fetch_top_markets(limit: int) -> list[dict]:
    """Devuelve los `limit` mercados más activos por volumen 24h."""
    params = urllib.parse.urlencode({
        "active": "true",
        "closed": "false",
        "limit": limit,
        "order": "volume24hr",
        "ascending": "false",
    })
    req = urllib.request.Request(
        f"{GAMMA_URL}?{params}",
        headers={"User-Agent": "polybot-collector/0.1"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _row_for(market: dict, token_id: str, outcome: str, price_str: str, ts: float) -> dict | None:
    try:
        price = float(price_str)
    except (TypeError, ValueError):
        return None
    return {
        "ts": ts,
        "market_slug": market.get("slug"),
        "question": market.get("question"),
        "token_id": token_id,
        "outcome": outcome,
        "price": price,
        "volume_24h": float(market.get("volume24hr") or 0),
        "liquidity": float(market.get("liquidity") or 0),
        "end_date": market.get("endDate"),
    }


def collect_once(limit: int) -> int:
    markets = fetch_top_markets(limit)
    now = time.time()
    rows: list[dict] = []
    for m in markets:
        try:
            ids = json.loads(m.get("clobTokenIds") or "[]")
            outs = json.loads(m.get("outcomes") or "[]")
            prices = json.loads(m.get("outcomePrices") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for tok, out, pr in zip(ids, outs, prices):
            row = _row_for(m, tok, out, pr, now)
            if row is not None:
                rows.append(row)
    storage.insert_snapshots(rows)
    log.info(
        "snapshot %d filas (%d mercados, %d tokens)",
        len(rows), len(markets), len({r["token_id"] for r in rows}),
    )
    return len(rows)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    storage.init_db()
    limit = int(os.getenv("COLLECTOR_LIMIT", DEFAULT_LIMIT))
    interval = int(os.getenv("COLLECTOR_INTERVAL", DEFAULT_INTERVAL))
    log.info("Iniciando colector: top %d mercados cada %ds", limit, interval)

    backoff = interval
    while True:
        try:
            collect_once(limit)
            backoff = interval  # reset al éxito
        except KeyboardInterrupt:
            log.info("Interrumpido por usuario")
            break
        except Exception as e:
            log.exception("Error: %s — backoff %ds", e, backoff)
            time.sleep(min(backoff, 300))
            backoff = min(backoff * 2, 300)
            continue
        time.sleep(interval)


if __name__ == "__main__":
    main()
