"""
Bot autónomo de Polymarket.

Sustituye al bot.py de umbrales fijos. Ahora:
  1. Consulta signal_engine para obtener señales BUY/SELL basadas en
     lo que hacen los top traders (ponderados por su historial aprendido).
  2. Escala el tamaño de posición según la confianza de la señal (0-1).
  3. Gestiona un portafolio multi-token: puede operar en varios mercados
     a la vez, no solo en el TOKEN_ID del .env.
  4. Take-profit y stop-loss automáticos.
  5. Registra resultados en la BD para retroalimentar el aprendizaje.

Evolución automática por fases (ver learner.py / storage.get_autonomy_phase):
  Fase 1 – COPIA    : sigue a cualquier trader con >= 2 confirmaciones
  Fase 2 – HÍBRIDO  : pesos aprendidos, umbral de confianza normal
  Fase 3 – AUTÓNOMO : exige confianza alta; ya no depende de copiar ciegamente

Variables de entorno (en .env):
  MIN_CONFIDENCE        umbral para operar (default 0.25)
  MAX_POSITION_USDC     máximo USDC por posición (default ORDER_SIZE_USDC * 3)
  TAKE_PROFIT_PCT       % ganancia para cerrar (default 0.20 = 20%)
  STOP_LOSS_PCT         % pérdida para cortar   (default 0.30 = 30%)
  AUTONOMOUS_INTERVAL   segundos entre ciclos   (default 60)
  PAPER_TRADING         true/false (hereda del .env base)
"""
from __future__ import annotations

import logging
import os
import time

from py_clob_client.order_builder.constants import BUY, SELL

import signal_engine
import storage
from client import build_client
from config import Config
from paper import PaperBroker

log = logging.getLogger("autonomous_bot")

AUTONOMOUS_INTERVAL = int(os.getenv("AUTONOMOUS_INTERVAL", "60"))
TAKE_PROFIT_PCT     = float(os.getenv("TAKE_PROFIT_PCT", "0.25"))
STOP_LOSS_PCT       = float(os.getenv("STOP_LOSS_PCT", "0.15"))


# ── Helpers de precio ────────────────────────────────────────────────────────

def _book_prices(client, token_id: str) -> tuple:
    """Devuelve (bid, ask, mid) del orderbook, o (None, None, None) si no hay liquidez."""
    try:
        book = client.get_order_book(token_id)
        bid  = float(book.bids[-1].price) if book.bids else None
        ask  = float(book.asks[-1].price) if book.asks else None
        mid  = ((bid + ask) / 2) if (bid and ask) else (bid or ask)
        return bid, ask, mid
    except Exception:
        return None, None, None


# ── Órdenes paper ────────────────────────────────────────────────────────────

def _paper_buy(broker: PaperBroker, token_id: str, price: float, usdc: float,
               signal_id: int | None = None) -> bool:
    fill = broker.execute(token_id, BUY, price, usdc)
    if fill:
        storage.record_order(
            token_id, "BUY", fill.avg_price, fill.shares, fill.notional,
            dry_run=True, status="PAPER",
        )
        if signal_id is not None:
            storage.mark_signal_acted(signal_id)
        log.info(
            "COMPRA PAPER: %.4f shares @ %.4f (%.2f USDC) token=%s",
            fill.shares, fill.avg_price, fill.notional, token_id[:12],
        )
        return True
    return False


def _paper_sell(broker: PaperBroker, token_id: str, price: float, usdc: float,
                reason: str = "", entry_price: float | None = None) -> bool:
    fill = broker.execute(token_id, SELL, price, usdc)
    if fill:
        storage.record_order(
            token_id, "SELL", fill.avg_price, fill.shares, fill.notional,
            dry_run=True, status="PAPER",
            response=f"realized={fill.realized:.4f}  {reason}",
        )
        # Cerrar la señal abierta para este token (feedback loop)
        open_sig = storage.get_open_signal_for_token(token_id)
        if open_sig:
            ref_price = entry_price or open_sig["avg_price"]
            pnl_pct = (fill.avg_price - ref_price) / ref_price if ref_price > 0 else 0.0
            storage.update_signal_outcome(open_sig["id"], fill.avg_price, round(pnl_pct, 4))
        log.info(
            "VENTA PAPER [%s]: %.4f shares @ %.4f  realizado=%.4f USDC  token=%s",
            reason, fill.shares, fill.avg_price, fill.realized, token_id[:12],
        )
        return True
    return False


# ── Gestión de posiciones abiertas ───────────────────────────────────────────

def manage_positions(client, broker: PaperBroker) -> None:
    """
    Revisa todas las posiciones abiertas y cierra si:
      - bid >= entry * (1 + TAKE_PROFIT_PCT)  → take profit
      - bid <= entry * (1 - STOP_LOSS_PCT)    → stop loss
    Usa el bid para vender (precio real al que se puede vender).
    """
    positions = storage.fetch_paper_positions()
    for pos in positions:
        token_id   = pos["token_id"]
        shares     = pos["shares"]
        cost_basis = pos["cost_basis"]
        if shares <= 0 or cost_basis <= 0:
            continue

        avg_entry = cost_basis / shares
        bid, _, _ = _book_prices(client, token_id)
        if bid is None:
            continue

        chg = (bid - avg_entry) / avg_entry

        if chg >= TAKE_PROFIT_PCT:
            log.info(
                "TAKE PROFIT  token=%s  entry=%.3f  bid=%.3f  (+%.1f%%)",
                token_id[:12], avg_entry, bid, chg * 100,
            )
            _paper_sell(broker, token_id, bid, shares * bid, "TAKE_PROFIT", avg_entry)

        elif chg <= -STOP_LOSS_PCT:
            log.info(
                "STOP LOSS    token=%s  entry=%.3f  bid=%.3f  (%.1f%%)",
                token_id[:12], avg_entry, bid, chg * 100,
            )
            _paper_sell(broker, token_id, bid, shares * bid, "STOP_LOSS", avg_entry)


# ── Actuar sobre señales ─────────────────────────────────────────────────────

def act_on_signals(client, broker: PaperBroker, cfg: Config) -> None:
    """Genera señales y opera las que superan el umbral de confianza."""
    signals = signal_engine.generate_signals(save=True)

    if not signals:
        log.info("Sin señales nuevas este ciclo.")
        return

    # Máximo por operación: el menor entre MAX_POSITION_USDC y el 5% del cash
    # disponible. Así nunca se queda sin dinero por una sola compra.
    cash_now  = broker.cash()
    hard_cap  = float(os.getenv("MAX_POSITION_USDC", "100.0"))
    max_pos   = min(hard_cap, cash_now * 0.05)
    min_conf  = float(os.getenv("MIN_CONFIDENCE", "0.25"))
    open_pos  = {p["token_id"] for p in storage.fetch_paper_positions()}

    for sig in signals:
        token_id   = sig["asset"]
        confidence = sig["confidence"]
        side       = sig["side"]
        signal_id  = sig.get("signal_id")

        if confidence < min_conf:
            continue

        # Tamaño proporcional a confianza: entre 25% y 100% del máximo
        size_usdc = max_pos * min(0.25 + confidence * 0.75, 1.0)

        if side == "BUY":
            if token_id in open_pos:
                log.info("Ya tenemos posición en %s – ignorando BUY.", token_id[:12])
                continue

            # Compramos al ASK (precio real al que el mercado vende)
            bid, ask, _ = _book_prices(client, token_id)
            if ask is None:
                log.warning("Sin ask para %s, saltando.", token_id[:12])
                continue

            log.info(
                "SEÑAL BUY  conf=%.2f  token=%s  ask=%.3f  size=%.1f$  │ %s",
                confidence, token_id[:12], ask, size_usdc, sig["reason"],
            )
            if _paper_buy(broker, token_id, ask, size_usdc, signal_id):
                open_pos.add(token_id)

        elif side == "SELL" and token_id in open_pos:
            # Vendemos al BID (precio real al que el mercado compra)
            bid, _, _ = _book_prices(client, token_id)
            if bid is None:
                continue

            log.info(
                "SEÑAL SELL conf=%.2f  token=%s  bid=%.3f  │ %s",
                confidence, token_id[:12], bid, sig["reason"],
            )
            shares, cost = storage.get_paper_position(token_id)
            entry = (cost / shares) if shares > 0 else None
            _paper_sell(broker, token_id, bid, shares * bid, "SIGNAL", entry)
            open_pos.discard(token_id)


# ── Ciclo principal ──────────────────────────────────────────────────────────

def tick(client, broker: PaperBroker, cfg: Config) -> None:
    phase, phase_name = storage.get_autonomy_phase()
    open_count        = len(storage.fetch_paper_positions())
    cash              = broker.cash()
    log.info(
        "── Ciclo │ Fase %d–%s │ Cash=%.2f$ │ Posiciones=%d ──",
        phase, phase_name, cash, open_count,
    )
    manage_positions(client, broker)
    act_on_signals(client, broker, cfg)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    storage.init_db()
    cfg    = Config.load()
    client = build_client(cfg)
    broker = PaperBroker(client, cfg.initial_cash)

    phase, phase_name = storage.get_autonomy_phase()
    eq = broker.equity(cfg.token_id, None)
    log.info(
        "Bot autónomo iniciado.  Fase=%d (%s) | Cash=%.2f$ | "
        "Take-profit=%.0f%% | Stop-loss=%.0f%% | Intervalo=%ds",
        phase, phase_name, eq["cash"],
        TAKE_PROFIT_PCT * 100, STOP_LOSS_PCT * 100, AUTONOMOUS_INTERVAL,
    )

    while True:
        try:
            tick(client, broker, cfg)
        except KeyboardInterrupt:
            log.info("Interrumpido por usuario.")
            break
        except Exception as e:
            log.exception("Error en tick autónomo: %s", e)
        time.sleep(AUTONOMOUS_INTERVAL)


if __name__ == "__main__":
    main()
