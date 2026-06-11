from flask import Flask, request
from flask_cors import CORS
from dotenv import load_dotenv
import os
from runsignup import (
    get_participants,
    get_race,
    historical_event_chain,
    parse_participant,
    race_options,
    update_seed_time,
)
from database import init_db, get_db, normalize_seed_time
import pandas as pd
import io
import re
from results import start_import_background, get_import_status, count_imported_years
from matcher import enrich_participants, find_past_results, time_to_seconds

load_dotenv()
init_db()

app = Flask(__name__)
frontend_origin = os.getenv(
    "FRONTEND_ORIGIN", "https://seed-checker-rho.vercel.app"
)
allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
if frontend_origin:
    allowed_origins.append(frontend_origin.rstrip("/"))
CORS(app, origins=allowed_origins)


def runsignup_credentials():
    api_key = request.headers.get("X-RSU-API-Key", "").strip()
    api_secret = request.headers.get("X-RSU-API-Secret", "").strip()
    if not api_key or not api_secret:
        return None
    return api_key, api_secret


def workspace():
    conn = get_db()
    rows = conn.execute(
        "SELECT key, value FROM settings WHERE key IN "
        "('race_id','event_id','question_id','race_name','event_name','event_distance',"
        "'participant_source')"
    ).fetchall()
    conn.close()
    values = {row["key"]: row["value"] for row in rows}
    for key in ("race_id", "event_id", "question_id"):
        values[key] = int(values[key]) if values.get(key) else None
    return values


def save_workspace(values):
    current = workspace()
    conn = get_db()
    if (
        current.get("race_id") != int(values["race_id"])
        or current.get("event_id") != int(values["event_id"])
    ):
        conn.execute("DELETE FROM participants")
        conn.execute("DELETE FROM settings WHERE key = 'participant_source'")
    for key in (
        "race_id", "event_id", "question_id", "race_name", "event_name",
        "event_distance",
    ):
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(values.get(key, ""))),
        )
    conn.commit()
    conn.close()


def year_from_start_time(value):
    match = re.search(r"\b(?:19|20)\d{2}\b", value or "")
    return int(match.group()) if match else None


@app.route("/ping")
def ping():
    return {"message": "server is running"}


@app.route("/participants")
def get_participants_route():
    conn = get_db()
    rows = conn.execute("""
        SELECT registration_id, first_name, last_name, age, gender, city, state,
               uploaded_seed, runsignup_seed, runsignup_checked, override_status
        FROM participants
        ORDER BY CASE WHEN runsignup_checked = 1
                      THEN runsignup_seed ELSE uploaded_seed END ASC
    """).fetchall()
    conn.close()
    participants = [dict(row) for row in rows]
    participants.sort(
        key=lambda participant: (
            time_to_seconds(
                participant["runsignup_seed"]
                if participant["runsignup_checked"]
                else participant["uploaded_seed"]
            ) is None,
            time_to_seconds(
                participant["runsignup_seed"]
                if participant["runsignup_checked"]
                else participant["uploaded_seed"]
            ) or 0,
        )
    )
    return participants


@app.route("/update-seed", methods=["POST"])
def update_seed():
    credentials = runsignup_credentials()
    if not credentials:
        return {"error": "RunSignup API key and secret are required"}, 401
    body = request.get_json()
    seed_time = normalize_seed_time(body["seed_time"])
    config = workspace()
    try:
        result = update_seed_time(
            config["race_id"], config["event_id"], config["question_id"],
            body["registration_id"], seed_time, *credentials
        )
    except Exception as e:
        return {"error": str(e)}, 502

    conn = get_db()
    conn.execute(
        """
        UPDATE participants
        SET runsignup_seed = ?, runsignup_checked = 1
        WHERE registration_id = ?
        """,
        (seed_time, body["registration_id"]),
    )
    conn.commit()
    conn.close()
    return result


@app.route("/upload-csv", methods=["POST"])
def upload_csv():
    if "file" not in request.files or not request.files["file"].filename:
        return {"error": "select a CSV or Excel file"}, 400
    file = request.files["file"]
    filename = file.filename.lower()
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        df = pd.read_excel(io.BytesIO(file.stream.read()))
    else:
        df = pd.read_csv(io.StringIO(file.stream.read().decode("utf-8")))

    seed_col = "Seeding time:" if "Seeding time:" in df.columns else "Seeding time"

    conn = get_db()
    inserted = 0
    registration_ids = []
    for _, row in df.iterrows():
        registration_id = row.get("Registration ID")
        if pd.isna(registration_id):
            continue
        if isinstance(registration_id, float) and registration_id.is_integer():
            registration_id = int(registration_id)
        registration_id = str(registration_id).strip()
        registration_ids.append(registration_id)

        raw_seed = row.get(seed_col)
        seed_time = normalize_seed_time(
            raw_seed if raw_seed is not None and str(raw_seed) != "nan" else None
        )

        conn.execute(
            """
            INSERT INTO participants
            (registration_id, first_name, last_name, age, gender, city, state,
             uploaded_seed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(registration_id) DO UPDATE SET
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                age = excluded.age,
                gender = excluded.gender,
                city = excluded.city,
                state = excluded.state,
                uploaded_seed = excluded.uploaded_seed
            """,
            (
                registration_id,
                row.get("First Name"),
                row.get("Last Name"),
                row.get("Age"),
                row.get("Gender"),
                row.get("City"),
                row.get("State"),
                seed_time,
            ),
        )
        inserted += 1
    if registration_ids:
        placeholders = ",".join("?" for _ in registration_ids)
        conn.execute(
            f"DELETE FROM participants WHERE registration_id NOT IN ({placeholders})",
            registration_ids,
        )
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('participant_source', 'upload')"
    )
    conn.commit()
    conn.close()
    return {"inserted": inserted}


@app.route("/import-results", methods=["POST"])
def import_results():
    credentials = runsignup_credentials()
    if not credentials:
        return {"error": "RunSignup API key and secret are required"}, 401
    body = request.get_json(silent=True) or {}
    events = body.get("events", [])
    if not events:
        return {"error": "select at least one historical event"}, 400
    config = workspace()
    return start_import_background(
        config["race_id"], config.get("race_name", ""), events, *credentials
    )


@app.route("/import-status")
def import_status():
    return get_import_status()


@app.route("/results-status")
def results_status():
    return count_imported_years()


@app.route("/check", methods=["POST"])
def check_participants():
    credentials = runsignup_credentials()
    if not credentials:
        return {"error": "RunSignup API key and secret are required"}, 401

    body = request.get_json(silent=True) or {}
    leeway = int(body.get("leeway", 300))
    raw_limit = body.get("limit", 300)
    limit = int(raw_limit) if raw_limit is not None else None
    range_start = body.get("range_start")
    range_end = body.get("range_end")
    config = workspace()
    conn = get_db()
    unchecked = conn.execute(
        "SELECT COUNT(*) FROM participants WHERE runsignup_checked = 0"
    ).fetchone()[0]
    conn.close()
    if unchecked:
        try:
            current = get_participants(
                config["race_id"], config["event_id"], *credentials
            )
        except Exception as e:
            return {"error": str(e)}, 502
        current_by_registration = {
            str(participant["registration_id"]): parse_participant(
                participant, config["question_id"]
            )
            for participant in current
        }
        conn = get_db()
        local_ids = [
            row["registration_id"]
            for row in conn.execute(
                "SELECT registration_id FROM participants WHERE runsignup_checked = 0"
            ).fetchall()
        ]
        for registration_id in local_ids:
            current_participant = current_by_registration.get(str(registration_id))
            if current_participant is None:
                continue
            conn.execute(
                """
                UPDATE participants SET runsignup_seed = ?, runsignup_checked = 1
                WHERE registration_id = ?
                """,
                (
                    normalize_seed_time(current_participant["seed_time"]),
                    registration_id,
                ),
            )
        conn.commit()
        conn.close()
    return enrich_participants(
        leeway, limit=limit, range_start=range_start, range_end=range_end
    )


@app.route("/discover-race", methods=["POST"])
def discover_race():
    credentials = runsignup_credentials()
    if not credentials:
        return {"error": "RunSignup API key and secret are required"}, 401
    body = request.get_json(silent=True) or {}
    try:
        race = get_race(int(body["race_id"]), *credentials)
    except Exception as e:
        return {"error": str(e)}, 502
    return race_options(race)


@app.route("/workspace", methods=["GET", "POST"])
def workspace_route():
    if request.method == "GET":
        return workspace()
    if not runsignup_credentials():
        return {"error": "RunSignup API key and secret are required"}, 401
    body = request.get_json(silent=True) or {}
    required = ("race_id", "event_id", "question_id")
    if any(not body.get(key) for key in required):
        return {"error": "race, event, and seed question are required"}, 400
    save_workspace(body)
    return workspace()


@app.route("/historical-events", methods=["POST"])
def historical_events():
    credentials = runsignup_credentials()
    if not credentials:
        return {"error": "RunSignup API key and secret are required"}, 401
    config = workspace()
    try:
        race = get_race(config["race_id"], *credentials)
    except Exception as e:
        return {"error": str(e)}, 502
    options = race_options(race)
    history = historical_event_chain(options["events"], config["event_id"])
    for event in history:
        event["year"] = year_from_start_time(event.get("start_time"))
    return history


@app.route("/sync-participants", methods=["POST"])
def sync_participants():
    credentials = runsignup_credentials()
    if not credentials:
        return {"error": "RunSignup API key and secret are required"}, 401
    config = workspace()
    try:
        current = get_participants(
            config["race_id"], config["event_id"], *credentials
        )
    except Exception as e:
        return {"error": str(e)}, 502

    parsed = [
        parse_participant(participant, config["question_id"])
        for participant in current
    ]
    conn = get_db()
    registration_ids = []
    for participant in parsed:
        registration_id = str(participant["registration_id"])
        registration_ids.append(registration_id)
        runsignup_seed = normalize_seed_time(participant["seed_time"])
        conn.execute("""
            INSERT INTO participants
            (registration_id, first_name, last_name, age, gender, city, state,
             runsignup_seed, runsignup_checked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(registration_id) DO UPDATE SET
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                age = excluded.age,
                gender = excluded.gender,
                city = excluded.city,
                state = excluded.state,
                runsignup_seed = excluded.runsignup_seed,
                runsignup_checked = 1
        """, (
            registration_id,
            participant["first_name"], participant["last_name"],
            participant["age"], participant["gender"], participant["city"],
            participant["state"], runsignup_seed,
        ))
    if registration_ids:
        placeholders = ",".join("?" for _ in registration_ids)
        conn.execute(
            f"DELETE FROM participants WHERE registration_id NOT IN ({placeholders})",
            registration_ids,
        )
    else:
        conn.execute("DELETE FROM participants")
    conn.execute("UPDATE participants SET uploaded_seed = NULL")
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('participant_source', 'sync')"
    )
    conn.commit()
    conn.close()
    return {"synced": len(parsed)}


@app.route("/enrich-one", methods=["POST"])
def enrich_one():
    body = request.get_json()
    reg_id = body.get("registration_id")
    conn = get_db()
    row = conn.execute(
        """
        SELECT registration_id, first_name, last_name, age, gender, city, state,
               uploaded_seed, runsignup_seed, runsignup_checked, override_status
        FROM participants WHERE registration_id = ?
        """,
        (reg_id,),
    ).fetchone()
    leeway_row = conn.execute(
        "SELECT value FROM settings WHERE key='leeway_seconds'"
    ).fetchone()
    conn.close()
    if not row:
        return {"error": "participant not found"}, 404
    p = dict(row)
    if "seed_time" in body:
        p["runsignup_seed"] = normalize_seed_time(body["seed_time"])
        p["runsignup_checked"] = 1
    leeway = int(leeway_row["value"]) if leeway_row else 300
    enriched = find_past_results(p, leeway)
    return {
        **p,
        "past_results": enriched["matches"],
        "past_best": enriched["past_best"],
        "past_best_year": enriched["past_best_year"],
        "status": enriched["status"],
        "reason": enriched["reason"],
    }


@app.route("/override-status", methods=["POST"])
def override_status():
    body = request.get_json()
    reg_id = body.get("registration_id")
    new_status = body.get("override_status")
    if new_status == "NEED TO GOOGLE":
        new_status = "REVIEW"
    valid = {"GOOD", "LIAR", "REVIEW", None}
    if new_status not in valid:
        return {"error": f"invalid status '{new_status}'"}, 400
    conn = get_db()
    conn.execute(
        "UPDATE participants SET override_status = ? WHERE registration_id = ?",
        (new_status, reg_id),
    )
    if conn.execute("SELECT changes()").fetchone()[0] == 0:
        conn.close()
        return {"error": "participant not found"}, 404
    conn.commit()
    conn.close()
    return {"registration_id": reg_id, "override_status": new_status}


@app.route("/settings")
def get_settings():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


@app.route("/settings", methods=["POST"])
def update_settings():
    body = request.get_json()
    if not body:
        return {"error": "no body"}, 400
    conn = get_db()
    for key, value in body.items():
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value)),
        )
    conn.commit()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False, threaded=True)
