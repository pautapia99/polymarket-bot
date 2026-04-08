"""
Bot de trading simple para Polymarket.

Estrategia:
  - Sondea el orderbook de un token (outcome) cada N segundos.
  - Si el mejor ASK <= BUY_BELOW => coloca una orden de COMPRA limit.
  - Si el mejor BID >= SELL_ABOVE => coloca una orden de VENTA limit.
  - DRY_RUN=true imprime las acciones en lugar de enviarlas.

NO es asesoramiento financiero. Pruébalo primero con DRY_RUN=true y montos pequeños.
"""
import logging
import time
from decimal import Decimal

from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from client import build_client
from config import Config
from paper import PaperBroker
import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("polybot")


def get_top_of_book(client, token_id: str) -> tuple[float | None, float | None]:
    """Devuelve (mejor_bid, mejor_ask) o (None, None) si no hay liquidez."""
    book = client.get_order_book(token_id)
    best_bid = float(book.bids[-1].price) if book.bids else None
    best_ask = float(book.asks[-1].price) if book.asks else None
    return best_bid, best_ask


def place_order(client, cfg: Config, broker, side: str, price: float, size_usdc: float):
    """Enruta la orden según el modo: paper / dry / real."""
    size_shares = round(size_usdc / price, 2)
    mode = "PAPER" if cfg.paper_trading else ("DRY" if cfg.dry_run else "REAL")
    log.info(
        "[%s] %s %.4f shares @ %.3f (%.2f USDC) token=%s",
        mode, side, size_shares, price, size_usdc, cfg.token_id[:10] + "...",
    )

    # --- PAPER ---
    if cfg.paper_trading:
        fill = broker.execute(cfg.token_id, side, price, size_usdc)
        if fill is None:
            storage.record_order(
                cfg.token_id, side, price, 0, 0,
                dry_run=True, status="PAPER_NOFILL", response="",
            )
            return None
        storage.record_order(
            cfg.token_id, fill.side, fill.avg_price, fill.shares, fill.notional,
            dry_run=True, status="PAPER",
            response=f"realized={fill.realized:.4f}" if fill.side == "SELL" else "",
        )
        return fill

    # --- DRY ---
    if cfg.dry_run:
        storage.record_order(
            cfg.token_id, side, price, size_shares, size_usdc,
            dry_run=True, status="DRY", response="",
        )
        return None

    # --- REAL ---
    try:
        args = OrderArgs(
            price=price,
            size=size_shares,
            side=side,
            token_id=cfg.token_id,
        )
        signed = client.create_order(args)
        resp = client.post_order(signed, OrderType.GTC)
        log.info("Respuesta: %s", resp)
        storage.record_order(
            cfg.token_id, side, price, size_shares, size_usdc,
            dry_run=False, status="OK", response=str(resp),
        )
        return resp
    except Exception as e:
        storage.record_order(
            cfg.token_id, side, price, size_shares, size_usdc,
            dry_run=False, status="ERROR", response=str(e),
        )
        raise


def tick(client, cfg: Config, broker):
    bid, ask = get_top_of_book(client, cfg.token_id)
    storage.record_tick(cfg.token_id, bid, ask)
    if bid is None or ask is None:
        log.warning("Orderbook vacío, esperando...")
        return

    spread = ask - bid
    log.info("bid=%.3f  ask=%.3f  spread=%.3f", bid, ask, spread)

    if ask <= cfg.buy_below:
        place_order(client, cfg, broker, BUY, ask, cfg.order_size_usdc)
    elif bid >= cfg.sell_above:
        place_order(client, cfg, broker, SELL, bid, cfg.order_size_usdc)
    else:
        log.info("Sin señal (umbrales: <=%.2f compra, >=%.2f venta)",
                 cfg.buy_below, cfg.sell_above)


def main():
    cfg = Config.load()
    storage.init_db()
    mode = "PAPER" if cfg.paper_trading else ("DRY" if cfg.dry_run else "REAL")
    log.info("Iniciando bot. MODE=%s  token=%s", mode, cfg.token_id)
    client = build_client(cfg)
    broker = PaperBroker(client, cfg.initial_cash) if cfg.paper_trading else None
    if broker:
        eq = broker.equity(cfg.token_id, None)
        log.info("Paper portfolio: cash=%.2f shares=%.2f", eq["cash"], eq["shares"])
    log.info("Cliente CLOB listo. Polling cada %ss.", cfg.poll_interval)

    while True:
        try:
            tick(client, cfg, broker)
        except KeyboardInterrupt:
            log.info("Interrumpido por usuario, saliendo.")
            break
        except Exception as e:
            log.exception("Error en tick: %s", e)
        time.sleep(cfg.poll_interval)


if __name__ == "__main__":
    main()
