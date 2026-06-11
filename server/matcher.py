import datetime
from collections import defaultdict
from rapidfuzz import fuzz
from database import get_db

NAME_SCORE_THRESHOLD = 80
CURRENT_YEAR = datetime.date.today().year


def time_to_seconds(t):
    if not t:
        return None
    parts = str(t).strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            first = int(parts[0])
            second = int(parts[1])
            if first <= 3 and len(parts[0]) == 1:
                return first * 3600 + second * 60
            return first * 60 + second
    except ValueError:
        return None
    return None


def seconds_to_display(s):
    if s is None:
        return ""
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def last_name_score(a, b):
    if not a or not b:
        return 0
    return fuzz.token_sort_ratio(a.lower().strip(), b.lower().strip())


def first_name_matches(a, b):
    if not a or not b:
        return False
    a, b = a.lower().strip(), b.lower().strip()
    if fuzz.token_sort_ratio(a, b) >= NAME_SCORE_THRESHOLD:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 3 and long.startswith(short)


def age_matches(current_age, past_age, past_year):
    if current_age is None or past_age is None:
        return True
    try:
        expected_past_age = int(current_age) - (CURRENT_YEAR - int(past_year))
        return abs(expected_past_age - int(past_age)) <= 1
    except (TypeError, ValueError):
        return True


def load_history():
    conn = get_db()
    race_row = conn.execute(
        "SELECT value FROM settings WHERE key = 'race_id'"
    ).fetchone()
    distance_row = conn.execute(
        "SELECT value FROM settings WHERE key = 'event_distance'"
    ).fetchone()
    race_id = int(race_row["value"]) if race_row else 13089
    distance = distance_row["value"] if distance_row else ""
    if distance:
        all_rows = conn.execute("""
            SELECT year, first_name, last_name, age, gender, city, net_time,
                   bib_number, race_name, event_name, distance
            FROM past_results
            WHERE LOWER(distance) = LOWER(?)
            ORDER BY year DESC
        """, (distance,)).fetchall()
    else:
        all_rows = conn.execute("""
            SELECT year, first_name, last_name, age, gender, city, net_time,
                   bib_number, race_name, event_name, distance
            FROM past_results WHERE race_id = ? ORDER BY year DESC
        """, (race_id,)).fetchall()
    history = [dict(row) for row in all_rows]
    conn.close()
    by_last_name = defaultdict(list)
    for result in history:
        last_name = (result.get("last_name") or "").lower().strip()
        if last_name:
            by_last_name[last_name].append(result)
    return history, by_last_name


def find_past_results(
    participant, leeway_seconds=300, history=None, history_by_last_name=None
):
    if history is None or history_by_last_name is None:
        history, history_by_last_name = load_history()

    p_first = (participant.get("first_name") or "").strip()
    p_last = (participant.get("last_name") or "").strip()
    p_gender = (participant.get("gender") or "").upper().strip()
    p_age = participant.get("age")
    p_seed = participant.get("runsignup_seed")
    if not participant.get("runsignup_checked"):
        p_seed = participant.get("uploaded_seed")

    exact_last_name = p_last.lower()
    candidates = history_by_last_name.get(exact_last_name)
    if candidates is None:
        candidates = history

    matches = []
    for r in candidates:

        if last_name_score(p_last, r["last_name"]) < NAME_SCORE_THRESHOLD:
            continue
        if not first_name_matches(p_first, r["first_name"]):
            continue

        r_gender = (r.get("gender") or "").upper().strip()
        if p_gender and r_gender and p_gender != r_gender:
            continue

        if not age_matches(p_age, r["age"], r["year"]):
            continue

        score = (
            last_name_score(p_last, r["last_name"])
            + fuzz.token_sort_ratio(p_first.lower(), r["first_name"].lower())
        ) // 2

        matches.append(
            {
                "year": r["year"],
                "net_time": r["net_time"],
                "bib_number": r.get("bib_number") or "",
                "age": r["age"],
                "gender": r["gender"],
                "city": r["city"],
                "race_name": r.get("race_name") or "",
                "event_name": r.get("event_name") or "",
                "distance": r.get("distance") or "",
                "score": score,
            }
        )

    past_best_str = None
    past_best_year = None
    if matches:
        best_sec = None
        for m in matches:
            s = time_to_seconds(m["net_time"])
            if s is not None and (best_sec is None or s < best_sec):
                best_sec = s
                past_best_str = m["net_time"]
                past_best_year = m["year"]

    status, reason = classify(
        p_seed, past_best_str, past_best_year, matches, leeway_seconds
    )

    return {
        "matches": matches,
        "past_best": past_best_str,
        "past_best_year": past_best_year,
        "status": status,
        "reason": reason,
    }


def classify(seed_time, past_best_str, past_best_year, matches, leeway_seconds):
    seed_sec = time_to_seconds(seed_time)
    if seed_sec is None:
        return "REVIEW", "Seed time missing or unreadable"

    if not matches:
        return "REVIEW", "No matching past results found"

    best_sec = time_to_seconds(past_best_str)

    if best_sec is None:
        return "REVIEW", "Past results found but times unreadable"

    round_hour = seed_sec % 3600 == 0
    gap = best_sec - seed_sec
    flag = " (round-hour seed)" if round_hour else ""

    if gap <= leeway_seconds:
        return "GOOD", f"Best: {past_best_str} ({past_best_year}){flag}"
    else:
        gap_str = seconds_to_display(abs(gap))
        return (
            "LIAR",
            f"Best: {past_best_str} ({past_best_year}); {gap_str} slower than seed{flag}",
        )


def enrich_participants(leeway_seconds=300, limit=None, range_start=None, range_end=None):
    conn = get_db()
    rows = conn.execute("""
        SELECT registration_id, first_name, last_name, age, gender,
               city, state, uploaded_seed, runsignup_seed,
               runsignup_checked, override_status
        FROM participants
        ORDER BY CASE WHEN runsignup_checked = 1
                      THEN runsignup_seed ELSE uploaded_seed END ASC
    """).fetchall()
    conn.close()

    participants = [dict(row) for row in rows]
    participants.sort(
        key=lambda participant: (
            time_to_seconds(
                participant["runsignup_seed"]
                if participant["runsignup_checked"]
                else participant["uploaded_seed"]
            )
            is None,
            time_to_seconds(
                participant["runsignup_seed"]
                if participant["runsignup_checked"]
                else participant["uploaded_seed"]
            )
            or 0,
        )
    )
    start_seconds = time_to_seconds(range_start)
    end_seconds = time_to_seconds(range_end)
    if start_seconds is not None and end_seconds is not None:
        participants = [
            participant for participant in participants
            if (seed_seconds := time_to_seconds(
                participant["runsignup_seed"]
                if participant["runsignup_checked"]
                else participant["uploaded_seed"]
            )) is not None and start_seconds <= seed_seconds <= end_seconds
        ]
    elif limit is not None:
        participants = participants[:max(0, int(limit))]

    history, history_by_last_name = load_history()
    results = []
    for p in participants:
        enriched = find_past_results(
            p, leeway_seconds, history, history_by_last_name
        )
        results.append(
            {
                **p,
                "past_results": enriched["matches"],
                "past_best": enriched["past_best"],
                "past_best_year": enriched["past_best_year"],
                "status": enriched["status"],
                "reason": enriched["reason"],
            }
        )
    return results
