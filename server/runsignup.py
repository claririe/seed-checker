import requests
import os

BASE_URL = "https://api.runsignup.com/rest"


def get_participants(race_id, event_id):
    response = requests.get(
        f"{BASE_URL}/race/{race_id}/participants",
        params={
            "rsu_api_key": os.getenv("RUNSIGNUP_API_KEY"),
            "event_id": event_id,
            "format": "json",
            "per_page": 500,
            "page": 1,
            "include_questions": "T",
        },
        headers={"X-RSU-API-SECRET": os.getenv("RUNSIGNUP_API_SECRET")},
    )
    return response.json()


def parse_participant(p):
    seed_time = None
    first_boilermaker = None

    for q in p.get("question_responses", []):
        if q["question_id"] == 7885:
            seed_time = q["response"]
        if q["question_id"] == 7884:
            first_boilermaker = q["response"]

    return {
        "registration_id": p["registration_id"],
        "first_name": p["user"]["first_name"],
        "last_name": p["user"]["last_name"],
        "age": p["age"],
        "gender": p["user"]["gender"],
        "city": p["user"]["address"]["city"],
        "state": p["user"]["address"]["state"],
        "seed_time": seed_time,
        "first_boilermaker": first_boilermaker,
    }
