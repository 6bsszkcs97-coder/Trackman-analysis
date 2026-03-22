# Cloud Deployment — Ephemeral Multi-User Mode

## Goal

Deploy the Trackman dashboard on Streamlit Community Cloud so anyone can paste their Trackman activity URLs and get a full analytics dashboard — no install, no account, no persistent storage.

## Architecture

Two modes, one codebase:

- **Local mode** (existing): `sync.py` populates `data/trackman.db`, `app.py` reads from SQLite. Unchanged.
- **Cloud mode** (new): No DB. Users paste Trackman activity URLs. App fetches shot data from Trackman's public REST API, processes in-memory, renders the dashboard. Data lives only in `st.session_state` — gone when the tab closes.

Mode detection: check for environment variable `CLOUD_MODE=1` first (set in Streamlit Community Cloud secrets). Fallback: if `data/trackman.db` does not exist → cloud mode. This avoids accidental mode activation on fresh local checkouts.

## Cloud Mode Flow

### Landing page

Displayed when no session data is loaded yet (`st.session_state["cloud_shots"]` is empty or absent):

- Text area: "Paste your Trackman activity URLs (one per line)"
- "Load Sessions" button
- Brief instructions explaining how to copy URLs from portal.trackmangolf.com
- Disclaimer: "Not affiliated with or endorsed by Trackman A/S. For personal use only."

### Data loading

On submit:

1. Parse each URL, extract UUID from `?a=` query parameter
2. **Deduplicate** UUIDs before fetching (same URL pasted twice → fetch once)
3. For each UUID, call `POST https://golf-player-activities.trackmangolf.com/api/reports/getactivityreport` with:
   - Body: `{"ActivityId": "<uuid>", "Altitude": 0, "Temperature": 25, "BallType": "Premium"}`
   - Headers: `{"Referer": "https://web-dynamic-reports.trackmangolf.com/"}` (same as `sync.py` — API may reject without it)
4. **Per-URL error handling**: if a URL fails (invalid UUID, timeout, non-200 response), skip it and report which URLs failed. Show: "Loaded 3 of 5 sessions. 2 failed: [truncated URLs]"
5. Parse `StrokeGroups[].Strokes[].Measurement` — same field mapping as `sync.py`
6. Convert units: speeds m/s → mph (× 2.23694), distances m → yards (× 1.09361). Note: `impact_offset` and `impact_height` convert m → cm (× 100), not m → yards.
7. Build a DataFrame matching the exact schema of `db.get_shots()` output. Required columns:
   - `id` (synthetic: UUID + shot index), `session_id` (the activity UUID), `date` (from API response `ActivityInfo.Date`), `title` (from `ActivityInfo.Title` or fallback to date string), `shot_number` (sequential per session), `club` (from `Stroke.ClubType`)
   - `excluded` (default `0` for all cloud shots — no persistent exclusion in cloud mode)
   - `raw_json` (full `Stroke` dict as JSON string — required by Dispersion tab's `parse_trajectory()`)
   - All 17 metric columns: `club_speed`, `ball_speed`, `smash_factor`, `launch_angle`, `launch_direction`, `total_spin`, `spin_axis`, `attack_angle`, `club_path`, `face_angle`, `face_to_path`, `dynamic_loft`, `carry`, `total`, `offline`, `peak_height`, `descent_angle`, `impact_offset`, `impact_height`
8. Store in `st.session_state["cloud_shots"]`
9. Build a synthetic `sessions_df` from the loaded data (one row per unique session_id with `date`, `title`, `shot_count`) and store in `st.session_state["cloud_sessions"]`

### Dashboard rendering

Once data is loaded:

- All existing tabs render identically — SQS scoring, charts, filters, everything
- The data source switches based on mode:
  - `load_shots()` → returns `st.session_state["cloud_shots"]` in cloud mode
  - `load_clubs()` → derives from `cloud_shots["club"].unique()` in cloud mode
  - `sessions_df` → uses `st.session_state["cloud_sessions"]` in cloud mode
  - `build_export_csv()` → builds from `cloud_shots` in cloud mode
- **Shot exclusion UI** (Session Detail tab): checkboxes still work but changes are session-state-only — they modify `cloud_shots["excluded"]` in memory, not a DB. The "Save exclusions" button either calls `db.update_shot_excluded()` (local) or updates session_state (cloud). Changes are lost when tab closes.
- Sidebar gains a "Load new sessions" button that clears `session_state` and returns to landing page

### Data lifecycle

- Per-browser-tab only (`st.session_state`)
- No server-side persistence
- Close tab = data gone
- No cookies, no accounts, no tracking

## File Changes

| File | Change |
|---|---|
| `app.py` | Add mode detection at top; add landing page for cloud mode; add `fetch_sessions_from_urls()` function; wrap `load_shots()`, `load_clubs()`, `build_export_csv()`, and exclusion logic with mode-aware branches |
| `db.py` | No changes (conditionally imported only in local mode) |
| `sync.py` | No changes |
| `.streamlit/config.toml` | Add if needed for cloud deployment config |
| `requirements.txt` | `requests` already present — no changes needed |

## What stays the same

- All 6 dashboard tabs
- All charts, filters, SQS scoring, quality tiers
- Club ordering, display names, personal records
- CSV export (data source changes, output format identical)
- The core DataFrame pipeline

## Deployment

- Streamlit Community Cloud (free tier)
- Connected to the GitHub repo
- Secrets/env: `CLOUD_MODE=1` (no API keys needed — Trackman report API is public)
- The `data/` directory is gitignored, so cloud mode activates automatically on deploy

## Disclaimer

Visible in both modes:
- Cloud mode: on the landing page
- Both modes: in the sidebar footer

Text: "Not affiliated with or endorsed by Trackman A/S. For personal use only."
