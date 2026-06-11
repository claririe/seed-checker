import sqlite3
import os

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "seed_checker.db"
)
DB_PATH = os.getenv("DATABASE_PATH", DEFAULT_DB_PATH)


def normalize_seed_time(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return text
    if len(numbers) == 3:
        hours, minutes, seconds = numbers
    elif len(numbers) == 2:
        left, right = numbers
        if left <= 3 and len(parts[0]) == 1:
            hours, minutes, seconds = left, right, 0
        else:
            hours, minutes, seconds = 0, left, right
    else:
        return text
    if minutes > 59 or seconds > 59:
        return text
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db():
    conn = get_db()
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    participant_columns = {
        "registration_id",
        "first_name",
        "last_name",
        "age",
        "gender",
        "city",
        "state",
        "uploaded_seed",
        "runsignup_seed",
        "runsignup_checked",
        "override_status",
    }
    existing = {
        row["name"] for row in conn.execute("PRAGMA table_info(participants)").fetchall()
    }
    migrated_participants = not participant_columns.issubset(existing)
    if migrated_participants:
        conn.execute("""
            CREATE TABLE participants_new (
                registration_id TEXT PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                age INTEGER,
                gender TEXT,
                city TEXT,
                state TEXT,
                uploaded_seed TEXT,
                runsignup_seed TEXT,
                runsignup_checked INTEGER NOT NULL DEFAULT 0,
                override_status TEXT
            )
        """)
        if existing:
            def source(column, fallback="NULL"):
                return column if column in existing else fallback

            uploaded = source("uploaded_seed", source("seed_time"))
            runsignup = source("runsignup_seed", source("rsu_seed_time"))
            checked = source(
                "runsignup_checked",
                f"CASE WHEN {runsignup} IS NULL THEN 0 ELSE 1 END",
            )
            conn.execute(f"""
                INSERT INTO participants_new
                (registration_id, first_name, last_name, age, gender, city, state,
                 uploaded_seed, runsignup_seed, runsignup_checked, override_status)
                SELECT registration_id, first_name, last_name, age, gender, city, state,
                       {uploaded}, {runsignup}, {checked}, {source("override_status")}
                FROM participants
            """)
            conn.execute("DROP TABLE participants")
        conn.execute("ALTER TABLE participants_new RENAME TO participants")

    conn.execute(
        "UPDATE participants SET override_status = 'REVIEW' WHERE override_status = 'NEED TO GOOGLE'"
    )
    if migrated_participants:
        rows = conn.execute(
            "SELECT registration_id, uploaded_seed, runsignup_seed FROM participants"
        ).fetchall()
        for row in rows:
            conn.execute(
                """
                UPDATE participants SET uploaded_seed = ?, runsignup_seed = ?
                WHERE registration_id = ?
                """,
                (
                    normalize_seed_time(row["uploaded_seed"]),
                    normalize_seed_time(row["runsignup_seed"]),
                    row["registration_id"],
                ),
            )

    past_sql_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='past_results'"
    ).fetchone()
    past_sql = past_sql_row["sql"] if past_sql_row else ""
    if "UNIQUE(race_id, event_id" not in past_sql:
        conn.execute("""
            CREATE TABLE past_results_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                event_id INTEGER NOT NULL,
                first_name TEXT,
                last_name TEXT,
                age INTEGER,
                gender TEXT,
                city TEXT,
                net_time TEXT,
                bib_number TEXT,
                UNIQUE(race_id, event_id, first_name, last_name, age, gender)
            )
        """)
        if past_sql:
            existing_past = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(past_results)").fetchall()
            }
            race_source = "race_id" if "race_id" in existing_past else "13089"
            bib_source = "bib_number" if "bib_number" in existing_past else "NULL"
            conn.execute(f"""
                INSERT OR IGNORE INTO past_results_new
                (race_id, year, event_id, first_name, last_name, age, gender,
                 city, net_time, bib_number)
                SELECT COALESCE({race_source}, 13089), year, event_id,
                       first_name, last_name, age, gender, city, net_time, {bib_source}
                FROM past_results
            """)
            conn.execute("DROP TABLE past_results")
        conn.execute("ALTER TABLE past_results_new RENAME TO past_results")
    for column in ("race_name TEXT", "event_name TEXT", "distance TEXT"):
        try:
            conn.execute(f"ALTER TABLE past_results ADD COLUMN {column}")
        except Exception:
            pass
    conn.execute("""
        UPDATE past_results
        SET race_name = COALESCE(race_name, 'Boilermaker Road Race'),
            distance = COALESCE(distance, '15K')
        WHERE race_id = 13089
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('leeway_seconds', '300')"
    )
    defaults = {
        "race_id": "13089",
        "event_id": "1028766",
        "question_id": "7885",
        "race_name": "Boilermaker Road Race",
        "event_name": "15K Race - Presented By Excellus BlueCross BlueShield",
        "event_distance": "15K",
    }
    for key, value in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )

    conn.commit()
    conn.close()
