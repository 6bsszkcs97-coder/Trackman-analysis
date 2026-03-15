"""
Trackman Golf Data Syncer
=========================
1. Opens a browser to log into portal.trackmangolf.com and get your session list.
2. For each session, calls the public report API directly (no browser needed) to
   pull shot-by-shot data and saves everything to data/trackman.db.

Usage:
    python sync.py            # sync new sessions only
    python sync.py --all      # re-sync every session (overwrite existing)
"""
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

import db

RAW_DIR = Path("data/raw")
SESSION_FILE = Path("data/browser_session.json")
PORTAL = "https://portal.trackmangolf.com"
REPORT_API = "https://golf-player-activities.trackmangolf.com/api/reports/getactivityreport"

# m/s → mph conversion for speed fields
MS_TO_MPH = 2.23694

# Mapping: DB column → (source key in Measurement, unit conversion fn)
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
    "carry":            ("Carry",           lambda v: round(v, 1)),
    "total":            ("Total",           lambda v: round(v, 1)),
    "offline":          ("TotalSide",       lambda v: round(v, 1)),
    "peak_height":      ("MaxHeight",       lambda v: round(v, 1)),
    "descent_angle":    ("LandingAngle",    lambda v: round(v, 1)),
    "impact_offset":    ("ImpactOffset",    lambda v: round(v * 100, 2)),
    "impact_height":    ("ImpactHeight",    lambda v: round(v * 100, 2)),
}


# ---------------------------------------------------------------------------
# Report API (public — UUID in the report link IS the auth token)
# ---------------------------------------------------------------------------

def fetch_report(uuid: str) -> dict:
    resp = requests.post(
        REPORT_API,
        json={"ActivityId": uuid, "Altitude": 0, "Temperature": 25, "BallType": "Premium"},
        headers={
            "referer": "https://web-dynamic-reports.trackmangolf.com/",
            "content-type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def parse_and_save_report(report: dict, session_id: str) -> int:
    """Parse StrokeGroups → Strokes → Measurement and upsert shots. Returns count."""
    saved = 0
    all_strokes = []
    for group in report.get("StrokeGroups", []):
        for stroke in group.get("Strokes", []):
            all_strokes.append(stroke)

    for i, stroke in enumerate(all_strokes):
        shot_id = stroke.get("Id") or f"{session_id}_{i+1}"
        club = stroke.get("Club") or ""
        m = stroke.get("Measurement", {})

        metrics = {}
        for col, (key, fn) in FIELD_MAP.items():
            val = m.get(key)
            metrics[col] = fn(val) if val is not None else None

        metrics["raw_json"] = json.dumps(stroke)
        db.upsert_shot(shot_id, session_id, i + 1, club, **metrics)
        saved += 1

    return saved


def uuid_from_report_link(link: str) -> str | None:
    m = re.search(r'[?&]a=([0-9a-f\-]{36})', link or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Activities list (needs browser + login)
# ---------------------------------------------------------------------------

async def fetch_activities_with_browser() -> list[dict]:
    from playwright.async_api import async_playwright

    activities: list[dict] = []
    seen: set[str] = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=30)
        storage = str(SESSION_FILE) if SESSION_FILE.exists() else None
        ctx = await browser.new_context(storage_state=storage)
        page = await ctx.new_page()

        async def capture(resp):
            if resp.status != 200 or ("graphql" not in resp.url and "api.golf" not in resp.url):
                return
            try:
                body = await resp.json()
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                (RAW_DIR / f"{ts}.json").write_text(json.dumps(body, indent=2))
                items = (
                    body.get("data", {}).get("me", {})
                        .get("activities", {}).get("items", [])
                )
                for item in items:
                    sid = item.get("id")
                    if sid and sid not in seen and item.get("kind") == "SHOT_ANALYSIS":
                        seen.add(sid)
                        activities.append(item)
            except Exception:
                pass

        page.on("response", capture)

        print("Opening portal.trackmangolf.com/player/activities …")
        await page.goto(f"{PORTAL}/player/activities")

        if not page.url.startswith(f"{PORTAL}/player"):
            print("\n>>> A browser window has opened. Please log in.")
            print(">>> Waiting up to 5 minutes …\n")
            await page.wait_for_url(f"{PORTAL}/player/**", timeout=300_000)

        await ctx.storage_state(path=str(SESSION_FILE))
        print("Logged in. Scrolling to load full activity list …")
        await page.wait_for_load_state("networkidle")

        prev_h = 0
        for _ in range(20):
            h = await page.evaluate("document.body.scrollHeight")
            if h == prev_h:
                break
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.5)
            await page.wait_for_load_state("networkidle")
            prev_h = h

        await browser.close()

    return activities


def load_activities_from_raw() -> list[dict]:
    activities, seen = [], set()
    for f in sorted(RAW_DIR.glob("*.json")):
        try:
            body = json.loads(f.read_text())
            items = (
                body.get("data", {}).get("me", {})
                    .get("activities", {}).get("items", [])
            )
            for item in items:
                sid = item.get("id")
                if sid and sid not in seen and item.get("kind") == "SHOT_ANALYSIS":
                    seen.add(sid)
                    activities.append(item)
        except Exception:
            pass
    return activities


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(resync_all: bool = False):
    db.init()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # ── Step 1: get/refresh the session list ──────────────────────────────
    cached = load_activities_from_raw()
    fresh = await fetch_activities_with_browser()

    # Merge, deduplicated
    seen = set()
    activities = []
    for item in fresh + cached:
        sid = item.get("id")
        if sid and sid not in seen:
            seen.add(sid)
            activities.append(item)

    print(f"\nFound {len(activities)} sessions total.")

    # ── Step 2: save session metadata ─────────────────────────────────────
    for s in activities:
        date = s.get("time", "")[:19]
        db.upsert_session(
            id=s["id"],
            title=f"Session {date[:10]}",
            date=date,
            location="",
            shot_count=s.get("strokeCount", 0),
            raw_json=json.dumps(s),
        )

    # ── Step 3: fetch shot data via public report API ─────────────────────
    print(f"Fetching shot data …\n")
    total_shots = 0

    for i, session in enumerate(activities):
        sid = session["id"]
        date_str = session.get("time", "")[:10]
        expected = session.get("strokeCount", 0)

        if not resync_all and len(db.get_shots(session_id=sid)) > 0:
            n = len(db.get_shots(session_id=sid))
            print(f"  [{i+1}/{len(activities)}] {date_str} ({expected} shots) – already in DB, skipping")
            continue

        uuid = uuid_from_report_link(session.get("reportLink", ""))
        if not uuid:
            print(f"  [{i+1}/{len(activities)}] {date_str} – no UUID, skipping")
            continue

        print(f"  [{i+1}/{len(activities)}] {date_str} – fetching {expected} shots …", end=" ", flush=True)
        try:
            report = fetch_report(uuid)
            n = parse_and_save_report(report, sid)
            total_shots += n
            print(f"✓ {n} shots")
        except Exception as e:
            print(f"✗ {e}")

    # ── Summary ───────────────────────────────────────────────────────────
    all_sessions = db.get_sessions()
    shots_in_db = len(db.get_shots())
    print(f"\nDone. {len(all_sessions)} sessions, {shots_in_db} shots in database.")


if __name__ == "__main__":
    asyncio.run(run(resync_all="--all" in sys.argv))
