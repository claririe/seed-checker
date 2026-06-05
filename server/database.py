import sqlite3

DB_PATH = "seed_checker.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            registration_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            age INTEGER,
            gender TEXT,
            city TEXT,
            state TEXT,
            seed_time TEXT,
            first_boilermaker TEXT
        )
    """)
    conn.commit()
    conn.close()
