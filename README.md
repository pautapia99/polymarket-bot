# Bot de trading para Polymarket

Bot simple en Python que opera un mercado de Polymarket vía el CLOB usando
[`py-clob-client`](https://github.com/Polymarket/py-clob-client).

**Estrategia:** comprar cuando el ask cae por debajo de un umbral, vender
cuando el bid sube por encima de otro. Pensado como punto de partida — modifícalo.

## Requisitos previos

1. Wallet en Polygon con:
   - **MATIC** para gas
   - **USDC.e** depositado y aprobado en Polymarket (haz al menos un trade manual desde la UI primero para que se inicialicen los allowances)
2. Python 3.10+

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
cp .env.example .env
```

Edita `.env` con tu `PRIVATE_KEY` y el `TOKEN_ID` del outcome a operar.

### Cómo obtener el TOKEN_ID

Cada mercado de Polymarket tiene 2 outcomes (Yes/No), cada uno con su `token_id`
ERC1155. Puedes obtenerlos de la Gamma API:

```
https://gamma-api.polymarket.com/markets?slug=<slug-del-mercado>
```

El campo `clobTokenIds` contiene los dos IDs.

### SIGNATURE_TYPE

- `0` → wallet EOA propia (lo normal si importas tu seed). `FUNDER_ADDRESS` vacío.
- `1` → cuenta Polymarket creada con email/magic. Necesitas el `FUNDER_ADDRESS` del proxy.
- `2` → wallet de navegador conectada vía Polymarket. También requiere `FUNDER_ADDRESS`.

## Uso

**Siempre** prueba primero con `DRY_RUN=true`:

```bash
python bot.py
```

Cuando estés seguro, pon `DRY_RUN=false` en `.env` y vuelve a ejecutarlo.

## Estructura

- `config.py` — carga `.env`
- `client.py` — inicializa el `ClobClient` y deriva las API creds L2
- `bot.py` — loop principal con la estrategia

## Avisos

- **No es asesoramiento financiero.** Puedes perder dinero.
- Empieza con `ORDER_SIZE_USDC` muy pequeño.
- Nunca subas tu `.env` ni tu `PRIVATE_KEY` a git.
- Polymarket no está disponible para residentes de EE.UU.; respeta los TOS.
