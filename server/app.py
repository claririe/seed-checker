from flask import Flask, request
from flask_cors import CORS
from dotenv import load_dotenv
import os
from runsignup import get_participants, parse_participant, update_seed_time
from database import init_db, get_db
import pandas as pd
import io
from results import start_import_background, get_import_status, count_imported_years
from matcher import enrich_participants, find_past_results, time_to_seconds

load_dotenv()
init_db()

app = Flask(__name__)
CORS(app)


def response_has_error(value):
    if isinstance(value, dict):
        if "error" in value:
            return True
        return any(response_has_error(v) for v in value.values())
    if isinstance(value, list):
        return any(response_has_error(v) for v in value)
    return False


@app.route("/ping")
def ping():
    return {"message": "server is running"}


@app.route("/test-participants")
def test_participants():
    participants = get_participants(13089, 1028766)
    parsed = [parse_participant(p) for p in participants]
    parsed.sort(key=lambda p: p["seed_time"] or "9:99:99")
    return parsed


@app.route("/participants")
def get_participants_route():
    conn = get_db()
    rows = conn.execute("SELECT * FROM participants ORDER BY seed_time ASC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.route("/update-seed", methods=["POST"])
def update_seed():
    body = request.get_json()
    try:
        result = update_seed_time(body["registration_id"], body["seed_time"])
    except Exception as e:
        return {"error": str(e)}, 502

    if response_has_error(result):
        return {"error": "RunSignup rejected the seed update", "runsignup": result}, 502

    conn = get_db()
    conn.execute(
        "UPDATE participants SET seed_time = ? WHERE registration_id = ?",
        (body["seed_time"], body["registration_id"]),
    )
    conn.commit()
    conn.close()
    return result


@app.route("/upload-csv", methods=["POST"])
def upload_csv():
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
        registration_id = str(registration_id)
        registration_ids.append(registration_id)

        raw_seed = row.get(seed_col)
        seed_time = (
            str(raw_seed) if raw_seed is not None and str(raw_seed) != "nan" else None
        )

        conn.execute(
            """
            INSERT INTO participants
            (registration_id, first_name, last_name, age, gender, city, state, seed_time, first_boilermaker)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(registration_id) DO UPDATE SET
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                age = excluded.age,
                gender = excluded.gender,
                city = excluded.city,
                state = excluded.state,
                seed_time = excluded.seed_time,
                first_boilermaker = excluded.first_boilermaker
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
                row.get("Is this your first Boilermaker?"),
            ),
        )
        inserted += 1
    if registration_ids:
        placeholders = ",".join("?" for _ in registration_ids)
        conn.execute(
            f"DELETE FROM participants WHERE registration_id NOT IN ({placeholders})",
            registration_ids,
        )
    conn.commit()
    conn.close()
    return {"inserted": inserted}


@app.route("/import-results", methods=["POST"])
def import_results():
    return start_import_background()


@app.route("/import-status")
def import_status():
    return get_import_status()


@app.route("/results-status")
def results_status():
    return count_imported_years()


@app.route("/enriched-participants")
def enriched_participants():
    leeway_param = request.args.get("leeway")
    if leeway_param:
        leeway = int(leeway_param)
    else:
        conn = get_db()
        row = conn.execute(
            "SELECT value FROM settings WHERE key='leeway_seconds'"
        ).fetchone()
        conn.close()
        leeway = int(row["value"]) if row else 300
    return enrich_participants(leeway)


@app.route("/enrich-one", methods=["POST"])
def enrich_one():
    body = request.get_json()
    reg_id = body.get("registration_id")
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM participants WHERE registration_id = ?", (reg_id,)
    ).fetchone()
    leeway_row = conn.execute(
        "SELECT value FROM settings WHERE key='leeway_seconds'"
    ).fetchone()
    conn.close()
    if not row:
        return {"error": "participant not found"}, 404
    p = dict(row)
    if "seed_time" in body:
        p["seed_time"] = body["seed_time"]
    leeway = int(leeway_row["value"]) if leeway_row else 300
    enriched = find_past_results(p, leeway)
    return {**p, **enriched}


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


@app.route("/corral-counts", methods=["POST"])
def corral_counts():
    body = request.get_json()
    corrals = body.get("corrals", [])
    conn = get_db()
    rows = conn.execute(
        "SELECT seed_time FROM participants WHERE seed_time IS NOT NULL"
    ).fetchall()
    conn.close()
    seeds_sec = [
        s for s in (time_to_seconds(r["seed_time"]) for r in rows) if s is not None
    ]
    result = []
    for c in corrals:
        start_sec = time_to_seconds(c.get("start", "0:00:00"))
        end_sec = time_to_seconds(c.get("end", "9:59:59"))
        count = sum(
            1
            for s in seeds_sec
            if start_sec is not None
            and end_sec is not None
            and start_sec <= s <= end_sec
        )
        result.append(
            {
                "label": c.get("label", ""),
                "start": c.get("start"),
                "end": c.get("end"),
                "count": count,
            }
        )
    return result


if __name__ == "__main__":
    app.run(debug=True, port=5001)
