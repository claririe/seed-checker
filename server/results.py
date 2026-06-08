import os
import time
import threading
import requests
from database import get_db

BOILERMAKER_15K_EVENTS = [
    {"year": 2025, "event_id": 877558, "result_set_id": 566346},
    {"year": 2024, "event_id": 744809, "result_set_id": 472794},
    {"year": 2023, "event_id": 632176, "result_set_id": 392463},
    {"year": 2022, "event_id": 576499, "result_set_id": 327766},
    {"year": 2021, "event_id": 462222, "result_set_id": 281380},
    {"year": 2020, "event_id": 360351, "result_set_id": 200121},
    {"year": 2019, "event_id": 263840, "result_set_id": 163651},
    {"year": 2018, "event_id": 190269, "result_set_id": 124051},
]

RACE_ID = 13089
BASE_URL = "https://api.runsignup.com/rest"

_import_state = {
    "running": False,
    "current_year": None,
    "completed": [],
    "errors": [],
    "last_error_detail": None,
}


def _params(extra=None):
    p = {"rsu_api_key": os.getenv("RUNSIGNUP_API_KEY"), "format": "json"}
    if extra:
        p.update(extra)
    return p


def _headers():
    return {"X-RSU-API-SECRET": os.getenv("RUNSIGNUP_API_SECRET")}


def get_result_set_id(event_id):
    url = f"{BASE_URL}/race/{RACE_ID}/results/get-result-sets"
    resp = requests.get(
        url, params=_params({"event_id": event_id}), headers=_headers(), timeout=15
    )
    resp.raise_for_status()
    sets = resp.json().get("individual_results_sets", [])
    if not sets:
        return None
    for result_set in sets:
        name = (result_set.get("individual_result_set_name") or "").lower()
        if "15k" in name and "wheel" not in name:
            return result_set["individual_result_set_id"]
    return sets[0]["individual_result_set_id"]


def fetch_page(event_id, result_set_id, page, per_page=500):
    url = f"{BASE_URL}/race/{RACE_ID}/results/get-results"
    resp = requests.get(
        url,
        params=_params(
            {
                "event_id": event_id,
                "individual_result_set_id": result_set_id,
                "results_per_page": per_page,
                "page": page,
            }
        ),
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("error_msg", "RunSignup results error"))

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
    if net_time and net_time.startswith("0") and ":" in net_time:
        net_time = net_time.lstrip("0") or "0"
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


def import_year(year, event_id, result_set_id=None):
    result_set_id = result_set_id or get_result_set_id(event_id)
    if result_set_id is None:
        return {
            "year": year,
            "event_id": event_id,
            "error": "no result sets found",
            "inserted": 0,
        }

    all_results = []
    page = 1
    while True:
        page_data = fetch_page(event_id, result_set_id, page)
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
            INSERT OR REPLACE INTO past_results
            (year, event_id, first_name, last_name, age, gender, city, net_time, bib_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def _run_import():
    _import_state["running"] = True
    _import_state["completed"] = []
    _import_state["errors"] = []
    _import_state["last_error_detail"] = None
    for event in BOILERMAKER_15K_EVENTS:
        year = event["year"]
        event_id = event["event_id"]
        _import_state["current_year"] = year
        try:
            summary = import_year(year, event_id, event.get("result_set_id"))
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


def start_import_background():
    if _import_state["running"]:
        return {"error": "import already running"}
    t = threading.Thread(target=_run_import, daemon=True)
    t.start()
    return {"started": True}


def get_import_status():
    return {
        "running": _import_state["running"],
        "current_year": _import_state["current_year"],
        "completed_years": [s["year"] for s in _import_state["completed"]],
        "total_years": len(BOILERMAKER_15K_EVENTS),
        "errors": _import_state["errors"],
        "last_error_detail": _import_state["last_error_detail"],
    }


def count_imported_years():
    conn = get_db()
    rows = conn.execute(
        "SELECT year, COUNT(*) as count FROM past_results GROUP BY year ORDER BY year DESC"
    ).fetchall()
    conn.close()
    return {r["year"]: r["count"] for r in rows}
