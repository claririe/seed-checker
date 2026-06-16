import time
import threading
import requests
from database import get_db, normalize_seed_time

BASE_URL = "https://api.runsignup.com/rest"

_import_state = {
    "running": False,
    "current_year": None,
    "completed": [],
    "errors": [],
    "last_error_detail": None,
    "total_events": 0,
}


def _params(api_key, extra=None):
    p = {"rsu_api_key": api_key, "format": "json"}
    if extra:
        p.update(extra)
    return p


def _headers(api_secret):
    return {"X-RSU-API-SECRET": api_secret}


def _response_json(response):
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        error = data["error"]
        if isinstance(error, dict):
            raise RuntimeError(error.get("error_msg") or "RunSignup results request failed")
        raise RuntimeError(str(error))
    return data


def get_result_set_id(race_id, event_id, api_key, api_secret):
    url = f"{BASE_URL}/race/{race_id}/results/get-result-sets"
    resp = requests.get(
        url,
        params=_params(api_key, {"event_id": event_id}),
        headers=_headers(api_secret),
        timeout=15,
    )
    sets = _response_json(resp).get("individual_results_sets", [])
    if not sets:
        return None
    for result_set in sets:
        name = (result_set.get("individual_result_set_name") or "").lower()
        if "wheel" not in name and "virtual" not in name:
            return result_set["individual_result_set_id"]
    return sets[0]["individual_result_set_id"]


def fetch_page(
    race_id, event_id, result_set_id, page, api_key, api_secret, per_page=500
):
    url = f"{BASE_URL}/race/{race_id}/results/get-results"
    resp = requests.get(
        url,
        params=_params(
            api_key,
            {
                "event_id": event_id,
                "individual_result_set_id": result_set_id,
                "results_per_page": per_page,
                "page": page,
            }
        ),
        headers=_headers(api_secret),
        timeout=30,
    )
    data = _response_json(resp)

    results = data.get("individual_results", {}).get("results_individual")
    if results is not None:
        return results

    result_sets = data.get("individual_results_sets", [])
    if result_sets:
        return result_sets[0].get("results", [])

    return []


def parse_result(raw):
    user = raw.get("user", {})
    addr = user.get("address", {})
    net_time = raw.get("chip_time") or raw.get("clock_time") or raw.get("time") or ""
    net_time = normalize_seed_time(net_time) or ""
    return {
        "first_name": (user.get("first_name") or raw.get("first_name") or "").strip(),
        "last_name": (user.get("last_name") or raw.get("last_name") or "").strip(),
        "age": raw.get("age"),
        "gender": raw.get("gender") or user.get("gender") or "",
        "city": (addr.get("city") or raw.get("city") or "").strip(),
        "net_time": net_time,
        "bib_number": str(
            raw.get("bib_num") or raw.get("bib") or raw.get("bib_number") or ""
        ).strip(),
    }


def import_year(
    race_id, race_name, year, event_id, event_name, distance,
    api_key, api_secret, result_set_id=None
):
    result_set_id = result_set_id or get_result_set_id(
        race_id, event_id, api_key, api_secret
    )
    if result_set_id is None:
        return {
            "year": year,
            "event_id": event_id,
            "skipped": True,
            "inserted": 0,
        }

    all_results = []
    page = 1
    while True:
        page_data = fetch_page(
            race_id, event_id, result_set_id, page, api_key, api_secret
        )
        if not page_data:
            break
        all_results.extend(page_data)
        if len(page_data) < 500:
            break
        page += 1
        time.sleep(0.2)

    conn = get_db()
    inserted = 0
    for raw in all_results:
        r = parse_result(raw)
        if not r["first_name"] or not r["last_name"]:
            continue
        conn.execute(
            """
            INSERT INTO past_results
            (year, event_id, first_name, last_name, age, gender, city, net_time,
             bib_number, race_id, race_name, event_name, distance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(race_id, event_id, first_name, last_name, age, gender)
            DO UPDATE SET
                city = excluded.city,
                net_time = excluded.net_time,
                bib_number = excluded.bib_number,
                race_name = excluded.race_name,
                event_name = excluded.event_name,
                distance = excluded.distance
        """,
            (
                year,
                event_id,
                r["first_name"],
                r["last_name"],
                r["age"],
                r["gender"],
                r["city"],
                r["net_time"],
                r["bib_number"],
                race_id,
                race_name,
                event_name,
                distance,
            ),
        )
        inserted += 1

    conn.commit()
    conn.close()
    return {
        "year": year,
        "event_id": event_id,
        "result_set_id": result_set_id,
        "inserted": inserted,
    }


def _run_import(race_id, race_name, events, api_key, api_secret):
    _import_state["running"] = True
    _import_state["completed"] = []
    _import_state["errors"] = []
    _import_state["last_error_detail"] = None
    _import_state["total_events"] = len(events)
    for event in events:
        year = event["year"]
        event_id = event["event_id"]
        _import_state["current_year"] = year
        try:
            summary = import_year(
                race_id, race_name, year, event_id, event.get("name", ""),
                event.get("distance", ""), api_key, api_secret,
                event.get("result_set_id")
            )
            _import_state["completed"].append(summary)
            if "error" in summary:
                _import_state["errors"].append(summary)
        except Exception as e:
            detail = f"{year}: {type(e).__name__}: {e}"
            _import_state["last_error_detail"] = detail
            err = {"year": year, "event_id": event_id, "error": str(e), "inserted": 0}
            _import_state["completed"].append(err)
            _import_state["errors"].append(err)
    _import_state["running"] = False
    _import_state["current_year"] = None


def start_import_background(race_id, race_name, events, api_key, api_secret):
    if _import_state["running"]:
        return {"error": "import already running"}
    t = threading.Thread(
        target=_run_import,
        args=(race_id, race_name, events, api_key, api_secret),
        daemon=True,
    )
    t.start()
    return {"started": True}


def get_import_status():
    return {
        "running": _import_state["running"],
        "current_year": _import_state["current_year"],
        "completed_years": [s["year"] for s in _import_state["completed"]],
        "total_years": _import_state["total_events"],
        "errors": _import_state["errors"],
        "last_error_detail": _import_state["last_error_detail"],
    }


def count_imported_years(race_id=None):
    conn = get_db()
    if race_id is None:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'race_id'"
        ).fetchone()
        race_id = int(row["value"]) if row else 13089
    rows = conn.execute("""
        SELECT year, COUNT(*) as count FROM past_results
        WHERE race_id = ? GROUP BY year ORDER BY year DESC
    """, (race_id,)).fetchall()
    conn.close()
    return {r["year"]: r["count"] for r in rows}
