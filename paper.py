"""
Motor de paper trading.

Lee el orderbook real de Polymarket y simula fills contra él, manteniendo
un portafolio virtual (cash + posiciones) en SQLite. No requiere wallet.

Modelo:
  - El bot envía órdenes "limit" como en producción.
  - El simulador camina el libro: una BUY @ limit P consume asks <= P;
    una SELL @ limit P consume bids >= P.
  - El cash y las posiciones se actualizan al instante (asume fill inmediato
    de la liquidez visible). No hay slippage adicional ni latencia.
  - P&L realizado se calcula con coste promedio (avg cost basis).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import storage

log = logging.getLogger("polybot.paper")


@dataclass
class FillResult:
    side: str
    shares: float
    notional: float          # USDC movidos en el fill
    avg_price: float
    realized: float = 0.0    # solo en SELL


def _book_levels(book, side: str) -> list[tuple[float, float]]:
    """Normaliza los niveles del libro a una lista (precio, tamaño) ordenada.

    side='asks' -> ordenado ascendente (mejor primero)
    side='bids' -> ordenado descendente (mejor primero)
    """
    raw = book.asks if side == "asks" else book.bids
    levels = [(float(l.price), float(l.size)) for l in raw]
    levels.sort(key=lambda x: x[0], reverse=(side == "bids"))
    return levels


class PaperBroker:
    def __init__(self, client, initial_cash: float):
        self.client = client
        if storage.get_paper_cash() is None:
            log.info("Inicializando portafolio paper con %.2f USDC", initial_cash)
            storage.set_paper_cash(initial_cash)

    # ---------- consultas ----------

    def cash(self) -> float:
        return storage.get_paper_cash() or 0.0

    def position(self, token_id: str) -> tuple[float, float]:
        return storage.get_paper_position(token_id)

    def equity(self, token_id: str, mark_price: float | None) -> dict:
        cash = self.cash()
        shares, cost = self.position(token_id)
        mv = (shares * mark_price) if mark_price is not None else 0.0
        unrealized = mv - cost if shares > 0 else 0.0
        return {
            "cash": cash,
            "shares": shares,
            "cost_basis": cost,
            "avg_cost": (cost / shares) if shares > 0 else 0.0,
            "market_value": mv,
            "unrealized": unrealized,
            "realized": storage.get_paper_realized(),
            "equity": cash + mv,
        }

    # ---------- ejecución ----------

    def execute(
        self, token_id: str, side: str, limit_price: float, size_usdc: float
    ) -> FillResult | None:
        book = self.client.get_order_book(token_id)
        if side.upper() == "BUY":
            return self._buy(token_id, book, limit_price, size_usdc)
        else:
            return self._sell(token_id, book, limit_price, size_usdc)

    # ---------- internos ----------

    def _buy(self, token_id, book, limit_price, size_usdc) -> FillResult | None:
        cash = self.cash()
        budget = min(size_usdc, cash)
        if budget <= 0:
            log.warning("Sin cash para comprar (cash=%.4f)", cash)
            return None

        levels = _book_levels(book, "asks")
        filled = 0.0
        spent = 0.0
        for price, size in levels:
            if price > limit_price + 1e-9:
                break
            if budget <= 1e-9:
                break
            cost_level = price * size
            if cost_level <= budget:
                filled += size
                spent += cost_level
                budget -= cost_level
            else:
                shares = budget / price
                filled += shares
                spent += budget
                budget = 0
                break

        if filled <= 0:
            log.info("BUY no llenada (sin asks <= %.3f)", limit_price)
            return None

        # actualiza cash y posición (avg cost)
        storage.set_paper_cash(cash - spent)
        cur_shares, cur_cost = storage.get_paper_position(token_id)
        storage.upsert_paper_position(
            token_id, cur_shares + filled, cur_cost + spent
        )
        avg = spent / filled
        log.info("PAPER BUY filled %.4f shares @ avg %.4f (gasto %.4f)",
                 filled, avg, spent)
        return FillResult(side="BUY", shares=filled, notional=spent, avg_price=avg)

    def _sell(self, token_id, book, limit_price, size_usdc) -> FillResult | None:
        cur_shares, cur_cost = storage.get_paper_position(token_id)
        if cur_shares <= 0:
            log.info("SELL ignorada: no hay posición")
            return None

        # objetivo en shares = size_usdc / limit_price (consistente con bot.py)
        target_shares = min(size_usdc / limit_price, cur_shares)
        levels = _book_levels(book, "bids")

        sold = 0.0
        proceeds = 0.0
        remaining = target_shares
        for price, size in levels:
            if price < limit_price - 1e-9:
                break
            if remaining <= 1e-9:
                break
            take = min(size, remaining)
            sold += take
            proceeds += take * price
            remaining -= take

        if sold <= 0:
            log.info("SELL no llenada (sin bids >= %.3f)", limit_price)
            return None

        avg_cost = cur_cost / cur_shares
        cost_removed = avg_cost * sold
        realized = proceeds - cost_removed

        storage.set_paper_cash(self.cash() + proceeds)
        storage.upsert_paper_position(
            token_id, cur_shares - sold, cur_cost - cost_removed
        )
        storage.add_paper_realized(realized)

        avg = proceeds / sold
        log.info(
            "PAPER SELL filled %.4f shares @ avg %.4f (ingreso %.4f, realized %.4f)",
            sold, avg, proceeds, realized,
        )
        return FillResult(
            side="SELL", shares=sold, notional=proceeds,
            avg_price=avg, realized=realized,
        )
