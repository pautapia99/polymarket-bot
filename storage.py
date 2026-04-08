"""Persistencia en SQLite para ticks y órdenes."""
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "polybot.db"


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                token_id TEXT NOT NULL,
                bid REAL,
                ask REAL,
                spread REAL,
                mid REAL
            );
            CREATE INDEX IF NOT EXISTS idx_ticks_ts ON ticks(ts);

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                token_id TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size_shares REAL NOT NULL,
                size_usdc REAL NOT NULL,
                dry_run INTEGER NOT NULL,
                status TEXT,
                response TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(ts);

            CREATE TABLE IF NOT EXISTS paper_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS paper_positions (
                token_id TEXT PRIMARY KEY,
                shares REAL NOT NULL,
                cost_basis REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                market_slug TEXT,
                question TEXT,
                token_id TEXT NOT NULL,
                outcome TEXT,
                price REAL,
                volume_24h REAL,
                liquidity REAL,
                end_date TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_snap_token_ts
                ON market_snapshots(token_id, ts);
            CREATE INDEX IF NOT EXISTS idx_snap_ts
                ON market_snapshots(ts);

            CREATE TABLE IF NOT EXISTS top_traders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                window TEXT NOT NULL,
                rank INTEGER NOT NULL,
                wallet TEXT NOT NULL,
                pseudonym TEXT,
                name TEXT,
                amount REAL
            );
            CREATE INDEX IF NOT EXISTS idx_topt_ts ON top_traders(ts);
            CREATE INDEX IF NOT EXISTS idx_topt_wallet ON top_traders(wallet);

            CREATE TABLE IF NOT EXISTS tracked_traders (
                wallet TEXT PRIMARY KEY,
                pseudonym TEXT,
                added_ts REAL NOT NULL,
                last_seen_tx TEXT,
                enabled INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS tracked_trades (
                tx_hash TEXT PRIMARY KEY,
                ts REAL NOT NULL,
                wallet TEXT NOT NULL,
                pseudonym TEXT,
                side TEXT NOT NULL,
                asset TEXT NOT NULL,
                condition_id TEXT,
                size REAL NOT NULL,
                price REAL NOT NULL,
                title TEXT,
                slug TEXT,
                outcome TEXT,
                outcome_index INTEGER,
                detected_ts REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tt_wallet_ts ON tracked_trades(wallet, ts);
            CREATE INDEX IF NOT EXISTS idx_tt_ts ON tracked_trades(ts);
            """
        )


# ---------- paper trading helpers ----------

def get_paper_cash() -> float | None:
    with _conn() as con:
        row = con.execute(
            "SELECT value FROM paper_state WHERE key='cash'"
        ).fetchone()
    return float(row["value"]) if row else None


def set_paper_cash(amount: float):
    with _conn() as con:
        con.execute(
            "INSERT INTO paper_state(key,value) VALUES('cash',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(amount),),
        )


def get_paper_realized() -> float:
    with _conn() as con:
        row = con.execute(
            "SELECT value FROM paper_state WHERE key='realized'"
        ).fetchone()
    return float(row["value"]) if row else 0.0


def add_paper_realized(delta: float):
    cur = get_paper_realized()
    with _conn() as con:
        con.execute(
            "INSERT INTO paper_state(key,value) VALUES('realized',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(cur + delta),),
        )


def get_paper_position(token_id: str) -> tuple[float, float]:
    with _conn() as con:
        row = con.execute(
            "SELECT shares, cost_basis FROM paper_positions WHERE token_id=?",
            (token_id,),
        ).fetchone()
    return (row["shares"], row["cost_basis"]) if row else (0.0, 0.0)


def upsert_paper_position(token_id: str, shares: float, cost_basis: float):
    with _conn() as con:
        if shares <= 1e-9:
            con.execute("DELETE FROM paper_positions WHERE token_id=?", (token_id,))
        else:
            con.execute(
                "INSERT INTO paper_positions(token_id, shares, cost_basis) VALUES(?,?,?) "
                "ON CONFLICT(token_id) DO UPDATE SET shares=excluded.shares, "
                "cost_basis=excluded.cost_basis",
                (token_id, shares, cost_basis),
            )


def fetch_paper_positions():
    with _conn() as con:
        rows = con.execute("SELECT * FROM paper_positions").fetchall()
    return [dict(r) for r in rows]


# ---------- snapshots multi-mercado ----------

def insert_snapshots(rows: list[dict]):
    if not rows:
        return
    with _conn() as con:
        con.executemany(
            """INSERT INTO market_snapshots
               (ts, market_slug, question, token_id, outcome, price,
                volume_24h, liquidity, end_date)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [
                (
                    r["ts"], r.get("market_slug"), r.get("question"),
                    r["token_id"], r.get("outcome"), r.get("price"),
                    r.get("volume_24h"), r.get("liquidity"), r.get("end_date"),
                )
                for r in rows
            ],
        )


def fetch_snapshot_stats() -> dict:
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) AS rows, COUNT(DISTINCT token_id) AS tokens, "
            "COUNT(DISTINCT market_slug) AS markets, "
            "MIN(ts) AS first_ts, MAX(ts) AS last_ts "
            "FROM market_snapshots"
        ).fetchone()
    return dict(row) if row else {}


# ---------- top traders / tracker ----------

def insert_top_traders_snapshot(window: str, rows: list[dict]):
    if not rows:
        return
    now = time.time()
    with _conn() as con:
        con.executemany(
            """INSERT INTO top_traders
               (ts, window, rank, wallet, pseudonym, name, amount)
               VALUES (?,?,?,?,?,?,?)""",
            [
                (now, window, i + 1, r["proxyWallet"],
                 r.get("pseudonym"), r.get("name"), float(r.get("amount") or 0))
                for i, r in enumerate(rows)
            ],
        )


def upsert_tracked_trader(wallet: str, pseudonym: str | None):
    with _conn() as con:
        con.execute(
            """INSERT INTO tracked_traders(wallet, pseudonym, added_ts, enabled)
               VALUES (?,?,?,1)
               ON CONFLICT(wallet) DO UPDATE SET pseudonym=excluded.pseudonym""",
            (wallet, pseudonym, time.time()),
        )


def get_tracked_traders() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT wallet, pseudonym, last_seen_tx FROM tracked_traders WHERE enabled=1"
        ).fetchall()
    return [dict(r) for r in rows]


def update_tracked_trader_last_tx(wallet: str, tx_hash: str | None):
    if not tx_hash:
        return
    with _conn() as con:
        con.execute(
            "UPDATE tracked_traders SET last_seen_tx=? WHERE wallet=?",
            (tx_hash, wallet),
        )


def insert_tracked_trade(trade: dict) -> bool:
    """Inserta un trade nuevo. Devuelve True si era nuevo (no duplicado)."""
    tx = trade.get("transactionHash")
    if not tx:
        return False
    with _conn() as con:
        cur = con.execute(
            """INSERT OR IGNORE INTO tracked_trades
               (tx_hash, ts, wallet, pseudonym, side, asset, condition_id,
                size, price, title, slug, outcome, outcome_index, detected_ts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                tx,
                float(trade.get("timestamp") or 0),
                trade.get("proxyWallet"),
                trade.get("pseudonym"),
                trade.get("side"),
                trade.get("asset"),
                trade.get("conditionId"),
                float(trade.get("size") or 0),
                float(trade.get("price") or 0),
                trade.get("title"),
                trade.get("slug"),
                trade.get("outcome"),
                trade.get("outcomeIndex"),
                time.time(),
            ),
        )
        return cur.rowcount > 0


def fetch_recent_tracked_trades(limit: int = 50) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM tracked_trades ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_tracker_stats() -> dict:
    with _conn() as con:
        traders_n = con.execute(
            "SELECT COUNT(*) FROM tracked_traders WHERE enabled=1"
        ).fetchone()[0]
        trades_n = con.execute("SELECT COUNT(*) FROM tracked_trades").fetchone()[0]
        last = con.execute(
            "SELECT MAX(detected_ts) FROM tracked_trades"
        ).fetchone()[0]
        first_lb = con.execute("SELECT MIN(ts) FROM top_traders").fetchone()[0]
        last_lb = con.execute("SELECT MAX(ts) FROM top_traders").fetchone()[0]
    return {
        "tracked_traders": traders_n,
        "tracked_trades": trades_n,
        "last_trade_ts": last,
        "first_lb_ts": first_lb,
        "last_lb_ts": last_lb,
    }


def reset_paper(initial_cash: float):
    with _conn() as con:
        con.execute("DELETE FROM paper_state")
        con.execute("DELETE FROM paper_positions")
    set_paper_cash(initial_cash)


def record_tick(token_id: str, bid: float | None, ask: float | None):
    spread = (ask - bid) if (bid is not None and ask is not None) else None
    mid = ((ask + bid) / 2) if (bid is not None and ask is not None) else None
    with _conn() as con:
        con.execute(
            "INSERT INTO ticks (ts, token_id, bid, ask, spread, mid) VALUES (?,?,?,?,?,?)",
            (time.time(), token_id, bid, ask, spread, mid),
        )


def record_order(
    token_id: str,
    side: str,
    price: float,
    size_shares: float,
    size_usdc: float,
    dry_run: bool,
    status: str,
    response: str = "",
):
    with _conn() as con:
        con.execute(
            """INSERT INTO orders
               (ts, token_id, side, price, size_shares, size_usdc, dry_run, status, response)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (time.time(), token_id, side, price, size_shares, size_usdc,
             int(dry_run), status, response),
        )


def fetch_ticks(limit: int = 500):
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM ticks ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def fetch_orders(limit: int = 200):
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM orders ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_stats():
    with _conn() as con:
        stats = {}
        stats["tick_count"] = con.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        stats["order_count"] = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

        last_tick = con.execute(
            "SELECT * FROM ticks ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        stats["last_tick"] = dict(last_tick) if last_tick else None

        buys = con.execute(
            "SELECT COALESCE(SUM(size_usdc),0) AS s, COALESCE(SUM(size_shares),0) AS sh "
            "FROM orders WHERE side='BUY'"
        ).fetchone()
        sells = con.execute(
            "SELECT COALESCE(SUM(size_usdc),0) AS s, COALESCE(SUM(size_shares),0) AS sh "
            "FROM orders WHERE side='SELL'"
        ).fetchone()

        stats["buy_usdc"] = buys["s"]
        stats["buy_shares"] = buys["sh"]
        stats["sell_usdc"] = sells["s"]
        stats["sell_shares"] = sells["sh"]
        stats["net_shares"] = (buys["sh"] or 0) - (sells["sh"] or 0)
        stats["realized_usdc"] = (sells["s"] or 0) - (buys["s"] or 0)
    return stats
