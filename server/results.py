import os
import time
import json
import requests
from database import get_db

BOILERMAKER_15K_EVENTS = [
    (2024, 744809),
    (2023, 632176),
    (2022, 576499),
    (2021, 462222),
    (2019, 263840),
    (2018, 190269),
    (2017, 137291),
    (2016, 79224),
]

RACE_ID = 13089
BASE_URL = "https://api.runsignup.com/rest"


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
    return resp.json().get("individual_results", {}).get("results_individual", [])


def parse_result(raw):
    user = raw.get("user", {})
    addr = user.get("address", {})
    net_time = raw.get("chip_time") or raw.get("clock_time") or raw.get("time") or ""
    if net_time and net_time.startswith("0") and ":" in net_time:
        net_time = net_time.lstrip("0") or "0"
    return {
        "first_name": user.get("first_name", "").strip(),
        "last_name": user.get("last_name", "").strip(),
        "age": raw.get("age"),
        "gender": raw.get("gender", ""),
        "city": addr.get("city", "").strip(),
        "net_time": net_time,
        "bib_number": str(
            raw.get("bib_num") or raw.get("bib") or raw.get("bib_number") or ""
        ).strip(),
    }


def import_year(year, event_id):
    result_set_id = get_result_set_id(event_id)
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


def import_all_years_streaming():
    total = len(BOILERMAKER_15K_EVENTS)
    for i, (year, event_id) in enumerate(BOILERMAKER_15K_EVENTS):
        try:
            summary = import_year(year, event_id)
        except Exception as e:
            summary = {
                "year": year,
                "event_id": event_id,
                "error": str(e),
                "inserted": 0,
            }
        summary["done"] = i == total - 1
        summary["progress"] = {"current": i + 1, "total": total}
        yield json.dumps(summary) + "\n"


def count_imported_years():
    conn = get_db()
    rows = conn.execute(
        "SELECT year, COUNT(*) as count FROM past_results GROUP BY year ORDER BY year DESC"
    ).fetchall()
    conn.close()
    return {r["year"]: r["count"] for r in rows}
