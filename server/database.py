import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_checker.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            registration_id TEXT PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            age INTEGER,
            gender TEXT,
            city TEXT,
            state TEXT,
            seed_time TEXT,
            first_boilermaker TEXT,
            override_status TEXT
        )
    """)

    try:
        conn.execute("ALTER TABLE participants ADD COLUMN override_status TEXT")
    except Exception:
        pass
    conn.execute(
        "UPDATE participants SET override_status = 'REVIEW' WHERE override_status = 'NEED TO GOOGLE'"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS past_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            event_id INTEGER NOT NULL,
            first_name TEXT,
            last_name TEXT,
            age INTEGER,
            gender TEXT,
            city TEXT,
            net_time TEXT,
            bib_number TEXT,
            UNIQUE(year, first_name, last_name, age, gender)
        )
    """)

    try:
        conn.execute("ALTER TABLE past_results ADD COLUMN bib_number TEXT")
    except Exception:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('leeway_seconds', '300')"
    )

    conn.commit()
    conn.close()
