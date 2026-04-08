"""Inicialización del cliente CLOB de Polymarket."""
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

from config import Config


def build_client(cfg: Config) -> ClobClient:
    """Crea un ClobClient.

    En paper trading se construye sin clave: solo se usan endpoints
    públicos (get_order_book, get_market). En modo real se autentica
    para poder enviar órdenes.
    """
    if cfg.paper_trading:
        return ClobClient(host=cfg.clob_host, chain_id=cfg.chain_id)

    kwargs = {
        "host": cfg.clob_host,
        "key": cfg.private_key,
        "chain_id": cfg.chain_id,
        "signature_type": cfg.signature_type,
    }
    if cfg.funder_address:
        kwargs["funder"] = cfg.funder_address

    client = ClobClient(**kwargs)

    # Deriva o crea las API credentials L2 (necesarias para enviar órdenes)
    creds: ApiCreds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    return client
