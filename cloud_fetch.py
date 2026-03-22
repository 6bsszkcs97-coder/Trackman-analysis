"""Fetch Trackman shot data directly from the public report API (no auth needed)."""

import json
import re
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
import requests

REPORT_API = "https://golf-player-activities.trackmangolf.com/api/reports/getactivityreport"
REPORT_HEADERS = {
    "referer": "https://web-dynamic-reports.trackmangolf.com/",
    "content-type": "application/json",
}

MS_TO_MPH = 2.23694
M_TO_YD = 1.09361

# DB column → (API Measurement key, conversion function)
# Must match sync.py FIELD_MAP exactly
FIELD_MAP = {
    "ball_speed":       ("BallSpeed",       lambda v: round(v * MS_TO_MPH, 1)),
    "club_speed":       ("ClubSpeed",       lambda v: round(v * MS_TO_MPH, 1)),
    "smash_factor":     ("SmashFactor",     lambda v: round(v, 3)),
    "launch_angle":     ("LaunchAngle",     lambda v: round(v, 1)),
    "launch_direction": ("LaunchDirection", lambda v: round(v, 1)),
    "total_spin":       ("SpinRate",        lambda v: round(v, 0)),
    "spin_axis":        ("SpinAxis",        lambda v: round(v, 1)),
    "attack_angle":     ("AttackAngle",     lambda v: round(v, 1)),
    "club_path":        ("ClubPath",        lambda v: round(v, 1)),
    "face_angle":       ("FaceAngle",       lambda v: round(v, 1)),
    "face_to_path":     ("FaceToPath",      lambda v: round(v, 1)),
    "dynamic_loft":     ("DynamicLoft",     lambda v: round(v, 1)),
    "carry":            ("Carry",           lambda v: round(v * M_TO_YD, 1)),
    "total":            ("Total",           lambda v: round(v * M_TO_YD, 1)),
    "offline":          ("TotalSide",       lambda v: round(v * M_TO_YD, 1)),
    "peak_height":      ("MaxHeight",       lambda v: round(v * M_TO_YD, 1)),
    "descent_angle":    ("LandingAngle",    lambda v: round(v, 1)),
    "impact_offset":    ("ImpactOffset",    lambda v: round(v * 100, 2)),
    "impact_height":    ("ImpactHeight",    lambda v: round(v * 100, 2)),
}


def extract_uuid(url: str) -> str | None:
    """Extract the activity UUID from a Trackman activity/report URL."""
    try:
        parsed = urlparse(url.strip())
        qs = parse_qs(parsed.query)
        candidates = qs.get("a", [])
        if candidates:
            return candidates[0]
    except Exception:
        pass
    # Fallback: try to find a UUID pattern in the string
    match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", url, re.I)
    return match.group(0) if match else None


def fetch_report(uuid: str) -> dict:
    """Fetch a single activity report from Trackman's public API."""
    resp = requests.post(
        REPORT_API,
        json={"ActivityId": uuid, "Altitude": 0, "Temperature": 25, "BallType": "Premium"},
        headers=REPORT_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def parse_report(report: dict, session_id: str) -> list[dict]:
    """Parse a report API response into a list of shot dicts matching db.get_shots() schema."""
    # Extract session metadata
    session_time = report.get("Time", "")
    date_str = session_time[:19] if session_time else ""
    # Try to get location from Groups
    location = ""
    for g in report.get("Groups", []):
        if g.get("Kind") == "Location":
            location = g.get("Name", "")
            break
    title = f"Session {date_str[:10]}" if date_str else "Unknown Session"

    # Flatten all strokes from grouped structure
    all_strokes = []
    for group in report.get("StrokeGroups", []):
        for stroke in group.get("Strokes", []):
            all_strokes.append(stroke)

    # Sort chronologically (Trackman groups by club, not by time)
    all_strokes.sort(key=lambda s: s.get("Time") or "")

    shots = []
    for i, stroke in enumerate(all_strokes):
        m = stroke.get("Measurement", {})
        shot = {
            "id": stroke.get("Id") or f"{session_id}_{i+1}",
            "session_id": session_id,
            "date": date_str,
            "title": title,
            "location": location,
            "shot_number": i + 1,
            "club": stroke.get("Club") or "",
            "excluded": None,
            "shot_time": stroke.get("Time", ""),
            "raw_json": json.dumps(stroke),
        }
        # Apply field map conversions
        for col, (key, fn) in FIELD_MAP.items():
            val = m.get(key)
            shot[col] = fn(val) if val is not None else None
        shots.append(shot)

    return shots


def fetch_sessions_from_urls(urls_text: str) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """
    Parse URLs, fetch data, return (shots_df, sessions_df, errors).

    shots_df: matches db.get_shots() schema
    sessions_df: matches load_sessions() schema (id, title, date, location, shot_count)
    errors: list of error messages for failed URLs
    """
    lines = [line.strip() for line in urls_text.strip().splitlines() if line.strip()]
    if not lines:
        return pd.DataFrame(), pd.DataFrame(), ["No URLs provided."]

    # Extract and deduplicate UUIDs
    uuid_map: dict[str, str] = {}  # uuid → original URL (for error reporting)
    for line in lines:
        uuid = extract_uuid(line)
        if uuid and uuid not in uuid_map:
            uuid_map[uuid] = line
        elif not uuid:
            pass  # Will be reported as error below

    errors: list[str] = []
    all_shots: list[dict] = []
    session_rows: list[dict] = []

    for uuid, url in uuid_map.items():
        try:
            report = fetch_report(uuid)
            shots = parse_report(report, uuid)
            all_shots.extend(shots)
            # Build session row
            if shots:
                s = shots[0]
                session_rows.append({
                    "id": uuid,
                    "title": s["title"],
                    "date": s["date"],
                    "location": s.get("location", ""),
                    "shot_count": len(shots),
                })
        except Exception as e:
            short_url = url[:60] + "..." if len(url) > 60 else url
            errors.append(f"{short_url}: {e}")

    # Report URLs that didn't parse
    for line in lines:
        uuid = extract_uuid(line)
        if not uuid:
            short = line[:60] + "..." if len(line) > 60 else line
            errors.append(f"Could not extract UUID: {short}")

    shots_df = pd.DataFrame(all_shots) if all_shots else pd.DataFrame()
    sessions_df = pd.DataFrame(session_rows) if session_rows else pd.DataFrame()

    return shots_df, sessions_df, errors
