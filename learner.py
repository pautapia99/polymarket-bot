"""
Motor de aprendizaje del bot Polymarket.

Analiza los trades históricos de los top traders y calcula métricas
de rendimiento para asignar pesos dinámicos a cada uno.

Cómo aprende:
  1. PAIR MATCHING: empareja BUY->SELL del mismo trader en el mismo asset
     (FIFO). Si sell_price > buy_price -> WIN.
  2. PRICE ORACLE: para BUYs sin SELL aún, busca el precio PRICE_FUTURE_HOURS
     horas después en market_snapshots. Si subió -> WIN probable.

Fases de autonomía (ver storage.get_autonomy_phase()):
  Fase 1 – COPIA     (< 100 pares): peso uniforme, copia directa
  Fase 2 – HÍBRIDO   (100-500 pares): pesos por win_rate
  Fase 3 – AUTÓNOMO  (> 500 pares, avg_wr > 55%): criterio propio consolidado

Variables de entorno:
  LEARN_INTERVAL_SECS   frecuencia de recálculo (default 1800 = 30 min)
  MIN_TRADES_TO_SCORE   pares mínimos para puntuar un trader (default 5)
  PRICE_FUTURE_HOURS    horas de evaluación de precio futuro (default 4)
"""
from __future__ import annotations

import logging
import math
import os
import sqlite3
import time
from collections import defaultdict

import storage

log = logging.getLogger("learner")

LEARN_INTERVAL_SECS = int(os.getenv("LEARN_INTERVAL_SECS", "1800"))
MIN_TRADES_TO_SCORE = int(os.getenv("MIN_TRADES_TO_SCORE", "5"))
PRICE_FUTURE_HOURS = float(os.getenv("PRICE_FUTURE_HOURS", "4"))
_FUTURE_SECS = PRICE_FUTURE_HOURS * 3600


# ── Pair matching ────────────────────────────────────────────────────────────

def _pair_match_stats() -> dict:
    """
    Empareja BUYs con SELLs por (wallet, asset) en orden cronológico (FIFO).
    Devuelve {wallet: {pseudonym, wins, losses, profit_sum, pairs}}.
    """
    con = sqlite3.connect(storage.DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT wallet, pseudonym, asset, side, price, ts
           FROM tracked_trades
           ORDER BY wallet, asset, ts ASC"""
    ).fetchall()
    con.close()

    groups: dict = defaultdict(list)
    for r in rows:
        groups[(r["wallet"], r["asset"])].append(dict(r))

    stats: dict = defaultdict(lambda: {
        "pseudonym": None,
        "wins": 0,
        "losses": 0,
        "profit_sum": 0.0,
        "pairs": 0,
    })

    for (wallet, _asset), trades in groups.items():
        buy_stack: list = []
        for t in trades:
            side = (t["side"] or "").upper()
            if side == "BUY":
                buy_stack.append(t)
            elif side == "SELL" and buy_stack:
                buy = buy_stack.pop(0)          # FIFO
                bp, sp = buy["price"], t["price"]
                if bp > 0:
                    profit_pct = (sp - bp) / bp
                    stats[wallet]["pairs"] += 1
                    stats[wallet]["profit_sum"] += profit_pct
                    stats[wallet]["pseudonym"] = t.get("pseudonym")
                    if sp > bp * 1.005:         # +0.5 % = win
                        stats[wallet]["wins"] += 1
                    else:
                        stats[wallet]["losses"] += 1

    return dict(stats)


# ── Price oracle (market_snapshots) ─────────────────────────────────────────

def _snapshot_stats() -> dict:
    """
    Para BUYs sin SELL posterior, consulta el precio N horas después.
    Devuelve {wallet: {snapshot_wins, snapshot_losses, snapshot_pairs}}.
    """
    con = sqlite3.connect(storage.DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT b.wallet, b.asset, b.price AS entry_price, b.ts AS entry_ts,
               (
                   SELECT AVG(ms.price)
                   FROM market_snapshots ms
                   WHERE ms.token_id = b.asset
                     AND ms.ts BETWEEN b.ts + ? * 0.7
                                   AND b.ts + ? * 1.4
               ) AS future_price
        FROM tracked_trades b
        WHERE b.side = 'BUY'
          AND NOT EXISTS (
              SELECT 1 FROM tracked_trades s
              WHERE s.wallet = b.wallet
                AND s.asset  = b.asset
                AND s.side   = 'SELL'
                AND s.ts > b.ts
          )
        """,
        (_FUTURE_SECS, _FUTURE_SECS),
    ).fetchall()
    con.close()

    stats: dict = defaultdict(lambda: {
        "snapshot_wins": 0, "snapshot_losses": 0, "snapshot_pairs": 0
    })
    for r in rows:
        if r["future_price"] is None or r["entry_price"] <= 0:
            continue
        wallet = r["wallet"]
        stats[wallet]["snapshot_pairs"] += 1
        if r["future_price"] > r["entry_price"] * 1.01:
            stats[wallet]["snapshot_wins"] += 1
        else:
            stats[wallet]["snapshot_losses"] += 1

    return dict(stats)


# ── Combinar + pesar ─────────────────────────────────────────────────────────

def compute_trader_stats() -> list[dict]:
    """
    Combina pair-matching y price oracle.
    Normaliza pesos a [0.05, 1.0].
    Devuelve lista de dicts listos para upsert en trader_stats.
    """
    pair = _pair_match_stats()
    snap = _snapshot_stats()
    all_wallets = set(pair) | set(snap)

    results: list[dict] = []
    for wallet in all_wallets:
        ps = pair.get(wallet, {})
        ss = snap.get(wallet, {})

        wins   = ps.get("wins", 0)   + ss.get("snapshot_wins", 0)
        losses = ps.get("losses", 0) + ss.get("snapshot_losses", 0)
        pairs  = ps.get("pairs", 0)  + ss.get("snapshot_pairs", 0)
        profit = ps.get("profit_sum", 0.0)

        if pairs < MIN_TRADES_TO_SCORE:
            continue

        win_rate      = wins / pairs
        avg_profit    = profit / max(ps.get("pairs", 1), 1)
        # Penaliza traders con win_rate < 40%; premia consistencia (log)
        raw_weight    = max(0.0, (win_rate - 0.40)) * math.log(pairs + 1)

        results.append({
            "wallet":         wallet,
            "pseudonym":      ps.get("pseudonym"),
            "win_rate":       round(win_rate, 4),
            "avg_profit_pct": round(avg_profit, 4),
            "trades_analyzed": pairs,
            "pairs_found":    ps.get("pairs", 0),
            "raw_weight":     raw_weight,
            "weight":         0.0,
        })

    if results:
        max_w = max(r["raw_weight"] for r in results) or 1.0
        for r in results:
            r["weight"] = round(max(0.05, r["raw_weight"] / max_w), 4)

    return results


# ── Ciclo principal ──────────────────────────────────────────────────────────

def run_learning_cycle() -> None:
    log.info("Iniciando ciclo de aprendizaje...")
    stats = compute_trader_stats()

    if not stats:
        log.info(
            "Sin pares suficientes todavía (necesito %d por trader). "
            "Sigue acumulando datos con el tracker.",
            MIN_TRADES_TO_SCORE,
        )
        return

    storage.upsert_trader_stats_batch(stats)

    top5 = sorted(stats, key=lambda x: x["weight"], reverse=True)[:5]
    log.info("Top 5 traders por peso aprendido:")
    for s in top5:
        name = s.get("pseudonym") or s["wallet"][:14]
        log.info(
            "  %-22s  win=%.1f%%  profit=%.2f%%  pares=%3d  peso=%.3f",
            name,
            s["win_rate"] * 100,
            s["avg_profit_pct"] * 100,
            s["trades_analyzed"],
            s["weight"],
        )

    phase, phase_name = storage.get_autonomy_phase()
    log.info("━━ Fase de autonomía actual: %d – %s ━━", phase, phase_name)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    storage.init_db()
    log.info(
        "Learner iniciado.  ciclo=%ds  min_trades=%d  ventana_futura=%.0fh",
        LEARN_INTERVAL_SECS, MIN_TRADES_TO_SCORE, PRICE_FUTURE_HOURS,
    )

    while True:
        try:
            run_learning_cycle()
        except KeyboardInterrupt:
            log.info("Interrumpido por usuario.")
            break
        except Exception as e:
            log.exception("Error en ciclo de aprendizaje: %s", e)
        time.sleep(LEARN_INTERVAL_SECS)


if __name__ == "__main__":
    main()
