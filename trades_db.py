import sqlite3
from threading import Lock

DB_PATH = "nezo_trades.db"
db_lock = Lock()

def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                placed_at TEXT NOT NULL,
                account TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stoploss_price REAL NOT NULL,
                tp1_filled_price REAL,
                tp2_filled_price REAL,
                tp1_hit INTEGER DEFAULT 0,
                tp2_hit INTEGER DEFAULT 0,
                result TEXT
            );
        """)
        conn.commit()
        conn.close()


def create_trade(placed_at, account, symbol, timeframe,
                 entry_price, stoploss_price):

    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("""
            INSERT INTO trades (
                placed_at, account, symbol, timeframe,
                entry_price, stoploss_price
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            placed_at, account, symbol, timeframe,
            entry_price, stoploss_price
        ))

        trade_id = c.lastrowid

        conn.commit()
        conn.close()

        return trade_id


def update_trade(trade_id, tp1_filled_price=None, tp2_filled_price=None,
                 tp1_hit=None, tp2_hit=None, result=None):

    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        fields = []
        values = []

        if tp1_filled_price is not None:
            fields.append("tp1_filled_price = ?")
            values.append(tp1_filled_price)

        if tp2_filled_price is not None:
            fields.append("tp2_filled_price = ?")
            values.append(tp2_filled_price)

        if tp1_hit is not None:
            fields.append("tp1_hit = ?")
            values.append(tp1_hit)

        if tp2_hit is not None:
            fields.append("tp2_hit = ?")
            values.append(tp2_hit)

        if result is not None:
            fields.append("result = ?")
            values.append(result)

        if not fields:
            return False

        sql = f"UPDATE trades SET {', '.join(fields)} WHERE id = ?"
        values.append(trade_id)

        c.execute(sql, values)
        conn.commit()
        conn.close()

        return True


def get_trades(from_time, to_time, account, symbol, tfs):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        sql = "SELECT * FROM trades WHERE placed_at BETWEEN ? AND ?"
        params = [from_time, to_time]

        if account:
            sql += " AND account = ?"
            params.append(account)

        if symbol:
            sql += " AND LOWER(symbol) LIKE ?"
            params.append(symbol + "%")

        if tfs and "all" not in tfs:
            sql += " AND timeframe IN ({})".format(",".join("?" * len(tfs)))
            params.extend(tfs)

        c.execute(sql, params)
        rows = [dict(r) for r in c.fetchall()]

        conn.close()
        return rows


def calculate_analytics(filters):
    from_time = filters.get("from")
    to_time = filters.get("to")
    account = filters.get("account", "").strip()
    symbol = filters.get("symbol", "").lower().strip()
    timeframes = filters.get("timeframes", [])

    trades = get_trades(from_time, to_time, account, symbol, timeframes)

    wins = sum(1 for t in trades if t["result"] == "win")
    losses = sum(1 for t in trades if t["result"] == "lose")
    total = len(trades)

    win_rate = (wins / total * 100) if total > 0 else 0

    # calculate R:R average
    rr_list = []
    for t in trades:
        entry = t["entry_price"]
        sl = t["stoploss_price"]
        result = t["result"]

        if entry is None or sl is None or result is None:
            continue

        risk = abs(entry - sl)
        if risk <= 0:
            continue

        if result == "win":
            tp = t["tp2_filled_price"] or t["tp1_filled_price"]
            if tp is None:
                continue
            reward = abs(tp - entry)
            rr_list.append(reward / risk)

        elif result == "lose":
            rr_list.append(-1)

    avg_rr = sum(rr_list) / len(rr_list) if rr_list else 0

    return {
        "win_rate": round(win_rate, 2),
        "avg_rr": round(avg_rr, 2),
        "total_trades": total,
        "wins": wins,
        "losses": losses
    }
