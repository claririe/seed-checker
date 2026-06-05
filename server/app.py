from flask import Flask, request
from flask_cors import CORS
from dotenv import load_dotenv
import os
from runsignup import get_participants, parse_participant, update_seed_time

load_dotenv()
print("KEY:", os.getenv("RUNSIGNUP_API_KEY"))
print("SECRET:", os.getenv("RUNSIGNUP_API_SECRET"))

app = Flask(__name__)
CORS(app)


@app.route("/ping")
def ping():
    return {"message": "server is running"}


@app.route("/test-participants")
def test_participants():
    data = get_participants(13089, 1028766)
    participants = [parse_participant(p) for p in data[0]["participants"]]
    return participants


@app.route("/update-seed", methods=["POST"])
def update_seed():
    body = request.get_json()
    result = update_seed_time(body["registration_id"], body["seed_time"])
    return result


if __name__ == "__main__":
    app.run(debug=True, port=5001)
