from flask import Flask
from dotenv import load_dotenv
import os
from runsignup import get_participants, parse_participant

load_dotenv()
print("KEY:", os.getenv("RUNSIGNUP_API_KEY"))
print("SECRET:", os.getenv("RUNSIGNUP_API_SECRET"))

app = Flask(__name__)

API_KEY = os.getenv("RUNSIGNUP_API_KEY")
API_SECRET = os.getenv("RUNSIGNUP_API_SECRET")

@app.route("/ping")
def ping():
    return {"message": "server is running"}

@app.route("/test-participants")
def test_participants():
    data = get_participants(13089, 1028766)
    participants = [parse_participant(p) for p in data[0]["participants"]]
    return participants

if __name__ == "__main__":
    app.run(debug=True)