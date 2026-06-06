from flask import Flask, request, Response, stream_with_context
from flask_cors import CORS
from dotenv import load_dotenv
import os
from runsignup import get_participants, parse_participant, update_seed_time
from database import init_db, get_db
import pandas as pd
import io
import requests
from results import import_all_years_streaming, count_imported_years
from matcher import enrich_participants, find_past_results, time_to_seconds

load_dotenv()
init_db()

app = Flask(__name__)
CORS(app)


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
    result = update_seed_time(body["registration_id"], body["seed_time"])
    return result


@app.route("/upload-csv", methods=["POST"])
def upload_csv():
    file = request.files["file"]
    df = pd.read_csv(io.StringIO(file.stream.read().decode("utf-8")))
    conn = get_db()
    inserted = 0
    for _, row in df.iterrows():
        conn.execute(
            """
            INSERT OR REPLACE INTO participants
            (registration_id, first_name, last_name, age, gender, city, state, seed_time, first_boilermaker)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("Registration ID"),
                row.get("First Name"),
                row.get("Last Name"),
                row.get("Age"),
                row.get("Gender"),
                row.get("City"),
                row.get("State"),
                row.get("Seeding time"),
                row.get("Is this your first Boilermaker?"),
            ),
        )
        inserted += 1
    conn.commit()
    conn.close()
    return {"inserted": inserted}


@app.route("/test-results")
def test_results():
    response = requests.get(
        "https://api.runsignup.com/rest/race/13089/results/get-results",
        params={
            "rsu_api_key": os.getenv("RUNSIGNUP_API_KEY"),
            "format": "json",
            "event_id": 877558,
            "individual_result_set_id": 472794,
            "first_name": "Robert",
            "last_name": "Brandt",
            "results_per_page": 5,
        },
        headers={"X-RSU-API-SECRET": os.getenv("RUNSIGNUP_API_SECRET")},
    )
    return response.json()


@app.route("/test-events")
def test_events():
    response = requests.get(
        "https://api.runsignup.com/rest/race/13089",
        params={
            "rsu_api_key": os.getenv("RUNSIGNUP_API_KEY"),
            "format": "json",
            "events": "T",
            "future_events_only": "F",
        },
        headers={"X-RSU-API-SECRET": os.getenv("RUNSIGNUP_API_SECRET")},
    )
    data = response.json()
    events = data.get("race", {}).get("events", [])
    return [
        {
            "event_id": e["event_id"],
            "name": e["name"],
            "previous_year_event_id": e.get("previous_year_event_id"),
        }
        for e in events
    ]


@app.route("/import-results", methods=["POST"])
def import_results():
    return Response(
        stream_with_context(import_all_years_streaming()),
        content_type="application/x-ndjson",
    )


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
    valid = {"GOOD", "LIAR", "NEED TO GOOGLE", None}
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
