"""
Rastreador de top traders de Polymarket (Fase 1 + Fase 2 del plan).

Fase 1 — Descubrir
  Cada LB_REFRESH_SECS consulta el leaderboard de Polymarket por la ventana
  configurada (7d por defecto), aplica filtros de calidad y guarda los TOP_K
  como "tracked traders".

Fase 2 — Rastrear
  Cada TRADES_POLL_SECS consulta los trades recientes de cada tracked trader
  y guarda los nuevos en `tracked_trades` (deduplicando por transactionHash).

Variables de entorno (todas opcionales):
  LB_WINDOW           1d | 7d | 30d   (default 7d)
  TOP_K               cuántos traders rastrear        (default 30)
  MIN_PROFIT_USD      filtro mínimo de PnL en USD     (default 5000)
  LB_REFRESH_SECS     refresco del leaderboard        (default 3600 = 1h)
  TRADES_POLL_SECS    polling de trades por trader    (default 300 = 5m)
"""
from __future__ import annotations

import logging
import os
import time

import storage
import traders

log = logging.getLogger("tracker")

LB_WINDOW = os.getenv("LB_WINDOW", "7d")
TOP_K = int(os.getenv("TOP_K", "30"))
MIN_PROFIT_USD = float(os.getenv("MIN_PROFIT_USD", "5000"))
LB_REFRESH_SECS = int(os.getenv("LB_REFRESH_SECS", "3600"))
TRADES_POLL_SECS = int(os.getenv("TRADES_POLL_SECS", "300"))


def refresh_leaderboard() -> int:
    log.info("Refrescando leaderboard window=%s", LB_WINDOW)
    rows = traders.fetch_top_profit(LB_WINDOW, limit=200)
    # Filtros de calidad
    filtered = [
        r for r in rows
        if float(r.get("amount") or 0) >= MIN_PROFIT_USD
        and r.get("proxyWallet")
    ][:TOP_K]

    storage.insert_top_traders_snapshot(LB_WINDOW, filtered)
    for r in filtered:
        storage.upsert_tracked_trader(
            r["proxyWallet"],
            r.get("pseudonym") or r.get("name"),
        )
    log.info(
        "Leaderboard: %d devueltos, %d superan filtro $%.0f, %d trackeados",
        len(rows), len(filtered), MIN_PROFIT_USD, len(filtered),
    )
    return len(filtered)


def poll_trades_for_all() -> int:
    tracked = storage.get_tracked_traders()
    new_total = 0
    for t in tracked:
        wallet = t["wallet"]
        try:
            trades = traders.fetch_user_trades(wallet, limit=100)
        except Exception as e:
            log.warning("Trades fail %s: %s", wallet[:10], e)
            continue
        if not trades:
            continue

        last_seen = t.get("last_seen_tx")
        new_for_this = 0
        found_anchor = False
        for tr in trades:  # vienen en orden cronológico desc
            tx = tr.get("transactionHash")
            if not tx:
                continue
            if tx == last_seen:
                found_anchor = True
                break
            if storage.insert_tracked_trade(tr):
                new_for_this += 1

        # Si llenamos la página sin encontrar el anchor y había anchor previo,
        # significa que el trader hizo más trades de los que cabe en una página
        # y posiblemente perdimos algunos. Útil para detectar gaps.
        if last_seen and not found_anchor and len(trades) >= 100:
            log.warning(
                "Posible gap en %s (%s): %d trades en la página y no se encontró "
                "el anchor previo. Considera bajar TRADES_POLL_SECS.",
                t.get("pseudonym") or wallet[:10], wallet[:10], len(trades),
            )

        # actualizamos puntero al hash más reciente
        storage.update_tracked_trader_last_tx(
            wallet, trades[0].get("transactionHash"),
        )
        new_total += new_for_this

    if new_total:
        log.info("Nuevos trades observados: %d (de %d traders)",
                 new_total, len(tracked))
    return new_total


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    storage.init_db()
    log.info(
        "Iniciando tracker. window=%s top=%d min_profit=$%.0f "
        "lb_refresh=%ds trades_poll=%ds",
        LB_WINDOW, TOP_K, MIN_PROFIT_USD, LB_REFRESH_SECS, TRADES_POLL_SECS,
    )

    refresh_leaderboard()
    last_lb = time.time()

    while True:
        try:
            poll_trades_for_all()
            if time.time() - last_lb > LB_REFRESH_SECS:
                refresh_leaderboard()
                last_lb = time.time()
        except KeyboardInterrupt:
            log.info("Interrumpido por usuario")
            break
        except Exception as e:
            log.exception("Error en loop: %s", e)
        time.sleep(TRADES_POLL_SECS)


if __name__ == "__main__":
    main()
