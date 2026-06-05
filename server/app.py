from flask import Flask, request
from flask_cors import CORS
from dotenv import load_dotenv
import os
from runsignup import get_participants, parse_participant, update_seed_time
from database import init_db, get_db
import pandas as pd
import io

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
    rows = conn.execute("""
        SELECT * FROM participants
        ORDER BY seed_time ASC
    """).fetchall()
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


if __name__ == "__main__":
    app.run(debug=True, port=5001)
