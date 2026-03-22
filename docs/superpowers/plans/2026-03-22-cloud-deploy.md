# Cloud Deployment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ephemeral cloud mode so anyone can paste Trackman activity URLs and get a full analytics dashboard without installing anything.

**Architecture:** Detect local vs cloud mode at startup. In cloud mode, show a landing page where users paste URLs. Fetch shot data directly from Trackman's public REST API, build the same DataFrame schema as `db.get_shots()`, store in `st.session_state`, and render the existing dashboard identically.

**Tech Stack:** Streamlit, requests, pandas, plotly (all already in requirements.txt)

**Spec:** `docs/superpowers/specs/2026-03-22-cloud-deploy-design.md`

---

## File Structure

| File | Role |
|---|---|
| `app.py` | Main dashboard — add mode detection, landing page, cloud data loading, mode-aware branches for DB calls |
| `cloud_fetch.py` | **New** — encapsulates API fetching, parsing, unit conversion. Reuses `FIELD_MAP` logic from `sync.py` |
| `db.py` | No changes (conditionally imported in local mode only) |
| `sync.py` | No changes |
| `.streamlit/config.toml` | Theme config for cloud deployment |

---

## Chunk 1: Cloud fetch module + mode detection

### Task 1: Create `cloud_fetch.py` — API fetch and parse module

**Files:**
- Create: `cloud_fetch.py`

This module encapsulates all cloud-mode data fetching. It mirrors the logic in `sync.py` lines 26-98 but returns DataFrames instead of writing to SQLite.

- [ ] **Step 1: Create `cloud_fetch.py` with constants and FIELD_MAP**

```python
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
```

- [ ] **Step 2: Add `extract_uuid(url)` function**

```python
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
```

- [ ] **Step 3: Add `fetch_report(uuid)` function**

```python
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
```

- [ ] **Step 4: Add `parse_report(report, session_id)` function**

Returns a list of shot dicts matching `db.get_shots()` schema.

```python
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
```

- [ ] **Step 5: Add `fetch_sessions_from_urls(urls_text)` — main entry point**

```python
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
```

- [ ] **Step 6: Syntax check**

Run: `.venv/bin/python3 -c "import ast; ast.parse(open('cloud_fetch.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 7: Smoke test with a real URL**

Run:
```bash
.venv/bin/python3 -c "
from cloud_fetch import fetch_sessions_from_urls
url = 'https://web-dynamic-reports.trackmangolf.com/?a=e16f3697-3126-f111-96ac-28c5c8d39b4d'
shots, sessions, errors = fetch_sessions_from_urls(url)
print(f'Shots: {len(shots)}, Sessions: {len(sessions)}, Errors: {errors}')
print(f'Columns: {list(shots.columns)}')
print(shots[['club', 'carry', 'ball_speed']].head())
"
```
Expected: ~80 shots, 1 session, no errors. Verify carry values are in yards (100-300 range), ball_speed in mph (80-180 range).

- [ ] **Step 8: Commit**

```bash
git add cloud_fetch.py
git commit -m "feat: add cloud_fetch module for ephemeral URL-based data loading"
```

---

### Task 2: Add mode detection and conditional DB import to `app.py`

**Files:**
- Modify: `app.py:1-20` (imports section)

- [ ] **Step 1: Replace unconditional `import db` with mode-aware import**

Find line 15 in `app.py`:
```python
import db
```

Replace the import section (around lines 1-20) so that:
1. Check for `CLOUD_MODE` env var or missing `data/trackman.db`
2. Only import `db` in local mode
3. Import `cloud_fetch` in cloud mode

```python
import os

CLOUD_MODE = os.environ.get("CLOUD_MODE") == "1" or not os.path.exists("data/trackman.db")

if not CLOUD_MODE:
    import db
```

Add `from cloud_fetch import fetch_sessions_from_urls` near the other imports.

- [ ] **Step 2: Wrap `load_sessions()`, `load_shots()`, `load_clubs()` with mode branches**

These are at lines 49-63. Replace them with mode-aware versions:

```python
@st.cache_data(ttl=30)
def load_sessions():
    if CLOUD_MODE:
        return st.session_state.get("cloud_sessions", pd.DataFrame())
    return pd.DataFrame(db.get_sessions())

@st.cache_data(ttl=30)
def load_shots(session_id=None, club=None):
    if CLOUD_MODE:
        df = st.session_state.get("cloud_shots", pd.DataFrame())
        if session_id is not None and not df.empty:
            if isinstance(session_id, list):
                df = df[df["session_id"].isin(session_id)]
            else:
                df = df[df["session_id"] == session_id]
        if club is not None and not df.empty:
            df = df[df["club"] == club]
        return df
    return pd.DataFrame(db.get_shots(session_id=session_id, club=club))

@st.cache_data(ttl=30)
def load_clubs():
    if CLOUD_MODE:
        df = st.session_state.get("cloud_shots", pd.DataFrame())
        if df.empty:
            return []
        return sort_clubs(df["club"].dropna().unique().tolist())
    return sort_clubs(db.get_clubs())
```

- [ ] **Step 3: Wrap `build_export_csv()` to use cloud data**

At line 353, `build_export_csv()` calls `load_shots()` which already branches on mode. No changes needed — verify this is the case by reading the function.

- [ ] **Step 4: Wrap shot exclusion save handler**

Find the exclusion save handler (around line 1192):
```python
db.update_shot_excluded(shot_ids[i], 1 if new_val else None)
```

Replace with:
```python
if CLOUD_MODE:
    # Update in session_state only (ephemeral)
    cloud_df = st.session_state.get("cloud_shots", pd.DataFrame())
    if not cloud_df.empty:
        cloud_df.loc[cloud_df["id"] == shot_ids[i], "excluded"] = 1 if new_val else None
        st.session_state["cloud_shots"] = cloud_df
else:
    db.update_shot_excluded(shot_ids[i], 1 if new_val else None)
```

- [ ] **Step 5: Syntax check**

Run: `.venv/bin/python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: add cloud mode detection and mode-aware data loading"
```

---

## Chunk 2: Landing page, sidebar disclaimer, deployment config

### Task 3: Add cloud mode landing page

**Files:**
- Modify: `app.py` (after mode detection, before the main dashboard code)

- [ ] **Step 1: Add landing page that shows when cloud_shots is empty**

Insert after the `st.set_page_config()` call and before the sidebar/main dashboard code. The landing page should only show in cloud mode when no data is loaded yet.

```python
if CLOUD_MODE and "cloud_shots" not in st.session_state:
    st.title("Trackman Shot Analysis Dashboard")
    st.markdown(
        "Paste your Trackman activity URLs below to analyze your sessions. "
        "Open each session in [portal.trackmangolf.com](https://portal.trackmangolf.com), "
        "then copy the URL from your browser's address bar."
    )
    urls_input = st.text_area(
        "Trackman activity URLs (one per line)",
        height=200,
        placeholder="https://web-dynamic-reports.trackmangolf.com/?a=...\nhttps://web-dynamic-reports.trackmangolf.com/?a=...",
    )
    if st.button("Load Sessions", type="primary"):
        if urls_input.strip():
            with st.spinner("Fetching shot data from Trackman..."):
                shots_df, sessions_df, errors = fetch_sessions_from_urls(urls_input)
            if not shots_df.empty:
                st.session_state["cloud_shots"] = shots_df
                st.session_state["cloud_sessions"] = sessions_df
                if errors:
                    st.warning(f"Loaded {len(sessions_df)} sessions. Errors: " + "; ".join(errors))
                st.rerun()
            else:
                st.error("No data could be loaded. " + "; ".join(errors))
        else:
            st.warning("Please paste at least one URL.")
    st.markdown("---")
    st.caption("Not affiliated with or endorsed by Trackman A/S. For personal use only.")
    st.stop()  # Don't render the dashboard
```

Key points:
- `st.stop()` prevents the rest of `app.py` from executing
- `st.rerun()` after loading triggers a fresh run with data now in session_state
- Error messages show which URLs failed

- [ ] **Step 2: Add "Load new sessions" button to sidebar (cloud mode only)**

Find the sidebar section (search for `with st.sidebar:`). Add at the bottom of the sidebar block:

```python
if CLOUD_MODE:
    st.markdown("---")
    if st.button("Load new sessions"):
        for key in ["cloud_shots", "cloud_sessions"]:
            st.session_state.pop(key, None)
        st.cache_data.clear()
        st.rerun()
```

- [ ] **Step 3: Add disclaimer to sidebar footer (both modes)**

At the very bottom of the sidebar block, add:

```python
st.markdown("---")
st.caption("Not affiliated with or endorsed by Trackman A/S. For personal use only.")
```

- [ ] **Step 4: Syntax check**

Run: `.venv/bin/python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: add cloud mode landing page and sidebar disclaimer"
```

---

### Task 4: Add `.streamlit/config.toml` for deployment

**Files:**
- Create: `.streamlit/config.toml`

- [ ] **Step 1: Create config file**

```toml
[theme]
primaryColor = "#1d6fb8"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f0f2f6"
textColor = "#262730"

[server]
maxUploadSize = 5
```

- [ ] **Step 2: Commit**

```bash
git add .streamlit/config.toml
git commit -m "chore: add Streamlit config for cloud deployment"
```

---

### Task 5: Test cloud mode end-to-end locally

**Files:**
- No file changes — verification only

- [ ] **Step 1: Stop any running Streamlit instance**

```bash
pkill -f "streamlit run" 2>/dev/null
```

- [ ] **Step 2: Start app in cloud mode**

```bash
CLOUD_MODE=1 .venv/bin/streamlit run app.py
```

- [ ] **Step 3: Verify landing page appears**

Open http://localhost:8501. Should see:
- Title: "Trackman Shot Analysis Dashboard"
- Text area for URLs
- "Load Sessions" button
- Disclaimer at bottom

- [ ] **Step 4: Test with real URL**

Paste this URL into the text area:
```
https://web-dynamic-reports.trackmangolf.com/?a=e16f3697-3126-f111-96ac-28c5c8d39b4d
```

Click "Load Sessions". Verify:
- Dashboard loads with shot data
- All 6 tabs work (Overview, Trends, Session Detail, Club Stats, Dispersion, Quality Analysis)
- SQS scores are computed
- Charts render
- Club names display correctly
- Sidebar shows "Load new sessions" button
- Disclaimer in sidebar

- [ ] **Step 5: Test "Load new sessions" button**

Click "Load new sessions" in sidebar. Should return to landing page.

- [ ] **Step 6: Test error handling**

Paste an invalid URL and click Load. Should show error message.

- [ ] **Step 7: Verify local mode still works**

```bash
pkill -f "streamlit run" 2>/dev/null
.venv/bin/streamlit run app.py
```

Open http://localhost:8501. Dashboard should load from SQLite as before (no landing page).

- [ ] **Step 8: Commit any fixes needed**

```bash
git add -A
git commit -m "fix: address issues found in cloud mode testing"
```
