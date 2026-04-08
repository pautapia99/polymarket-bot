"""Carga de configuración desde .env"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(name, default)
    if required and not val:
        raise RuntimeError(f"Falta variable de entorno: {name}")
    return val or ""


@dataclass
class Config:
    private_key: str
    clob_host: str
    chain_id: int
    signature_type: int
    funder_address: str
    token_id: str
    buy_below: float
    sell_above: float
    order_size_usdc: float
    poll_interval: int
    dry_run: bool
    paper_trading: bool
    initial_cash: float

    @classmethod
    def load(cls) -> "Config":
        paper = _get("PAPER_TRADING", "true").lower() == "true"
        # En paper trading no necesitamos PRIVATE_KEY
        return cls(
            private_key=_get("PRIVATE_KEY", required=not paper),
            clob_host=_get("CLOB_HOST", "https://clob.polymarket.com"),
            chain_id=int(_get("CHAIN_ID", "137")),
            signature_type=int(_get("SIGNATURE_TYPE", "0")),
            funder_address=_get("FUNDER_ADDRESS", ""),
            token_id=_get("TOKEN_ID", required=True),
            buy_below=float(_get("BUY_BELOW", "0.40")),
            sell_above=float(_get("SELL_ABOVE", "0.60")),
            order_size_usdc=float(_get("ORDER_SIZE_USDC", "5")),
            poll_interval=int(_get("POLL_INTERVAL", "30")),
            dry_run=_get("DRY_RUN", "true").lower() == "true",
            paper_trading=paper,
            initial_cash=float(_get("INITIAL_CASH", "1000")),
        )
