import sqlite3
import json

DB_PATH = "presets.db"

# Authentication material should never be written to a preset database.
SENSITIVE_KEYS = {"apiKey", "token", "token_expiry"}


def init_db():
    """Create the presets table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            data TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def _sanitized_settings(settings: dict) -> dict:
    """Return preset-safe settings with authentication material removed."""
    return {key: value for key, value in settings.items() if key not in SENSITIVE_KEYS}


def save_preset(name: str, settings: dict):
    """Insert or replace a preset without persisting authentication secrets."""
    init_db()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    settings_json = json.dumps(_sanitized_settings(settings))

    cur.execute("""
        INSERT INTO presets (name, data)
        VALUES (?, ?)
        ON CONFLICT(name) DO UPDATE SET data = excluded.data
    """, (name, settings_json))

    conn.commit()
    conn.close()


def load_preset(name: str):
    """Load a preset by name and return the settings dict."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT data FROM presets WHERE name = ?", (name,))
    row = cur.fetchone()
    conn.close()

    if row is None:
        return None

    # Also sanitize older rows in case they were created before this safeguard.
    return _sanitized_settings(json.loads(row[0]))


def delete_preset(name: str):
    """Delete a preset by its name."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("DELETE FROM presets WHERE name = ?", (name,))
    conn.commit()
    conn.close()


def list_presets():
    """Return a list of all preset names."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT name FROM presets ORDER BY name ASC")
    rows = cur.fetchall()
    conn.close()

    return [r[0] for r in rows]
