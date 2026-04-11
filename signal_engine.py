"""
Motor de señales de trading.

Combina la actividad reciente de los top traders (ponderada por los pesos
calculados por learner.py) para generar señales BUY/SELL con score de
confianza 0–1.

Comportamiento por fase:
  Fase 1 – COPIA:   pesos uniformes, umbral reducido al 50%. Muy seguidor.
  Fase 2 – HÍBRIDO: pesos aprendidos, umbral normal.
  Fase 3 – AUTÓNOMO: pesos aprendidos + exige mayor consenso.

Variables de entorno:
  SIGNAL_LOOKBACK_HOURS   ventana de actividad reciente (default 2)
  MIN_CONFIDENCE          umbral mínimo de confianza (default 0.25)
  MIN_TRADERS_SIGNAL      mínimo traders distintos por señal (default 2)
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict

import storage

log = logging.getLogger("signal_engine")

SIGNAL_LOOKBACK_HOURS = float(os.getenv("SIGNAL_LOOKBACK_HOURS", "2"))
SIGNAL_LOOKBACK_SECS  = SIGNAL_LOOKBACK_HOURS * 3600
MIN_CONFIDENCE        = float(os.getenv("MIN_CONFIDENCE", "0.25"))
MIN_TRADERS_SIGNAL    = int(os.getenv("MIN_TRADERS_SIGNAL", "2"))

_BASE_WEIGHT = 0.3   # peso para traders sin estadísticas aprendidas aún


def generate_signals(save: bool = True) -> list[dict]:
    """
    Genera señales de trading a partir de la actividad reciente.

    Cada señal incluye:
      asset, slug, outcome, title, side, confidence (0-1),
      avg_price, traders_count, reason, phase, phase_name

    Args:
        save: si True, persiste las señales en la tabla `signals`.

    Returns:
        Lista de señales ordenadas por confianza DESC.
    """
    phase, phase_name = storage.get_autonomy_phase()
    trader_weights    = storage.get_trader_weights()

    cutoff       = time.time() - SIGNAL_LOOKBACK_SECS
    recent_trades = storage.get_recent_tracked_trades_since(cutoff)

    if not recent_trades:
        return []

    now = time.time()

    # Agrupa por (asset, side) acumulando pesos ponderados por recencia
    groups: dict = defaultdict(lambda: {
        "wallets":       set(),
        "weighted_sum":  0.0,
        "price_wsum":    0.0,
        "weight_total":  0.0,
        "meta":          {},
    })

    for trade in recent_trades:
        side  = (trade.get("side") or "").upper()
        asset = trade.get("asset")
        if not asset or side not in ("BUY", "SELL"):
            continue

        wallet = trade["wallet"]
        w      = trader_weights.get(wallet, _BASE_WEIGHT)

        # Recencia: 1.0 si es muy reciente, ~0.1 al límite de la ventana
        age     = now - trade["ts"]
        recency = max(0.1, 1.0 - age / SIGNAL_LOOKBACK_SECS)
        eff_w   = w * recency

        g = groups[(asset, side)]
        g["wallets"].add(wallet)
        g["weighted_sum"]  += eff_w
        g["price_wsum"]    += trade["price"] * eff_w
        g["weight_total"]  += eff_w
        # Guardamos metadatos del primer trade encontrado
        if not g["meta"].get("slug"):
            g["meta"] = {
                "slug":    trade.get("slug"),
                "outcome": trade.get("outcome"),
                "title":   trade.get("title"),
            }

    if not groups:
        return []

    max_ws   = max(g["weighted_sum"] for g in groups.values()) or 1.0
    # Fase 1: umbral más permisivo (estamos aprendiendo, mejor no perdernos señales)
    min_conf = MIN_CONFIDENCE * (0.5 if phase == 1 else 1.0)

    signals: list[dict] = []
    for (asset, side), g in groups.items():
        n = len(g["wallets"])
        if n < MIN_TRADERS_SIGNAL:
            continue

        confidence = min(g["weighted_sum"] / max_ws, 1.0)
        if confidence < min_conf:
            continue

        avg_price = (
            g["price_wsum"] / g["weight_total"]
            if g["weight_total"] > 0 else 0.0
        )

        reason = (
            f"[Fase {phase}/{phase_name}] "
            f"{n} traders (peso acum.={g['weighted_sum']:.2f}) "
            f"señalan {side} @ {avg_price:.3f}"
        )

        sig = {
            "asset":         asset,
            "slug":          g["meta"].get("slug"),
            "outcome":       g["meta"].get("outcome"),
            "title":         g["meta"].get("title"),
            "side":          side,
            "confidence":    round(confidence, 3),
            "avg_price":     round(avg_price, 4),
            "traders_count": n,
            "traders":       list(g["wallets"]),
            "reason":        reason,
            "phase":         phase,
            "phase_name":    phase_name,
        }
        signals.append(sig)

        if save:
            storage.insert_signal(
                asset         = asset,
                slug          = sig["slug"],
                outcome       = sig["outcome"],
                title         = sig["title"],
                side          = side,
                confidence    = sig["confidence"],
                avg_price     = sig["avg_price"],
                traders_count = n,
                traders_json  = json.dumps(list(g["wallets"])),
                reason        = reason,
                phase         = phase,
            )
            log.info(
                "Señal %s  conf=%.2f  token=%s  mercado=%s",
                side, confidence, asset[:12],
                sig["title"] or sig["slug"] or "—",
            )

    signals.sort(key=lambda x: x["confidence"], reverse=True)
    return signals
