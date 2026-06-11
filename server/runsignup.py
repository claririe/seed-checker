import requests
import json

BASE_URL = "https://api.runsignup.com/rest"


def _credentials(api_key, api_secret):
    return (
        {"rsu_api_key": api_key, "format": "json"},
        {"X-RSU-API-SECRET": api_secret},
    )


def _response_json(response):
    response.raise_for_status()
    data = response.json()
    error = _find_error(data)
    if error is not None:
        if isinstance(error, dict):
            raise RuntimeError(error.get("error_msg") or "RunSignup request failed")
        raise RuntimeError(str(error))
    return data


def _find_error(value):
    if isinstance(value, dict):
        if "error" in value:
            return value["error"]
        for child in value.values():
            error = _find_error(child)
            if error is not None:
                return error
    elif isinstance(value, list):
        for child in value:
            error = _find_error(child)
            if error is not None:
                return error
    return None


def get_race(race_id, api_key, api_secret):
    params, headers = _credentials(api_key, api_secret)
    params.update({"include_questions": "T"})
    response = requests.get(
        f"{BASE_URL}/race/{race_id}",
        params=params,
        headers=headers,
        timeout=30,
    )
    data = _response_json(response)
    if "race" not in data:
        raise RuntimeError("RunSignup did not return this race")
    return data["race"]


def race_options(race):
    events = []
    for event in race.get("events", []):
        events.append(
            {
                "event_id": event.get("event_id"),
                "name": event.get("name") or "",
                "distance": event.get("distance") or "",
                "start_time": event.get("start_time") or "",
                "previous_year_event_id": event.get("previous_year_event_id"),
            }
        )
    questions = [
        {
            "question_id": question.get("question_id"),
            "question_text": question.get("question_text") or "",
            "question_type_code": question.get("question_type_code") or "",
            "skip_for_event_ids": question.get("skip_for_event_ids") or [],
        }
        for question in race.get("questions", [])
    ]
    return {
        "race_id": race.get("race_id"),
        "name": race.get("name"),
        "events": events,
        "questions": questions,
    }


def historical_event_chain(events, current_event_id):
    by_id = {event["event_id"]: event for event in events}
    current = by_id.get(int(current_event_id))
    history = []
    seen = set()
    previous_id = current.get("previous_year_event_id") if current else None
    while previous_id and previous_id not in seen:
        seen.add(previous_id)
        previous = by_id.get(previous_id)
        if not previous:
            break
        history.append(previous)
        previous_id = previous.get("previous_year_event_id")
    return history


def get_participants(race_id, event_id, api_key, api_secret):
    participants = []
    page = 1
    per_page = 2500

    while True:
        response = requests.get(
            f"{BASE_URL}/race/{race_id}/participants",
            params={
                "rsu_api_key": api_key,
                "event_id": event_id,
                "format": "json",
                "results_per_page": per_page,
                "page": page,
                "include_questions": "T",
            },
            headers={"X-RSU-API-SECRET": api_secret},
            timeout=30,
        )
        data = _response_json(response)
        if not isinstance(data, list) or not data:
            raise RuntimeError("RunSignup returned an unexpected participant response")
        page_participants = data[0].get("participants", [])
        participants.extend(page_participants)
        if len(page_participants) < per_page:
            break
        page += 1

    return participants


def parse_participant(p, seed_question_id=7885):
    seed_time = None

    for q in p.get("question_responses", []):
        if q["question_id"] == seed_question_id:
            seed_time = q["response"]

    user = p.get("user") or {}
    address = user.get("address") or {}
    return {
        "registration_id": p["registration_id"],
        "first_name": user.get("first_name") or "",
        "last_name": user.get("last_name") or "",
        "age": p.get("age"),
        "gender": user.get("gender") or p.get("gender") or "",
        "city": address.get("city") or "",
        "state": address.get("state") or "",
        "seed_time": seed_time,
    }


def update_seed_time(
    race_id, event_id, question_id, registration_id, new_seed_time,
    api_key, api_secret
):
    response = requests.post(
        f"{BASE_URL}/race/{race_id}/participants",
        params={"rsu_api_key": api_key, "format": "json"},
        headers={"X-RSU-API-SECRET": api_secret},
        data={
            "race_id": race_id,
            "event_id": event_id,
            "restrict_potential_dup": "F",
            "request_format": "json",
            "request": json.dumps(
                {
                    "participants": [
                        {
                            "registration_id": registration_id,
                            "question_responses": [
                                {"question_id": question_id, "response": new_seed_time}
                            ],
                        }
                    ]
                }
            ),
        },
        timeout=30,
    )
    return _response_json(response)
