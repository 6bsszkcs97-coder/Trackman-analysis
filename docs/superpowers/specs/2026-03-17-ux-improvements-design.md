# UX Improvements: Club Display Names & Session Comparison

Two independent features that improve the dashboard's readability and analytical depth.

---

## Feature 1: Human-Readable Club Display Names

### Problem

Every chart, legend, filter, and table shows Trackman's internal identifiers (`7Iron`, `PitchingWedge`, `SandWedge`). Users should see `7 Iron`, `Pitching Wedge`, `Sand Wedge`.

### Design

**New constants and helper (top of `app.py`, near other helpers):**

- `CLUB_DISPLAY: dict[str, str]` — explicit mapping for all known Trackman club identifiers:
  - `Driver` → `Driver`
  - `2Wood`–`7Wood` → `2 Wood`–`7 Wood`
  - `DrivingIron` → `Driving Iron`
  - `1Iron`–`9Iron` → `1 Iron`–`9 Iron`
  - `1Hybrid`–`7Hybrid` → `1 Hybrid`–`7 Hybrid`
  - `PitchingWedge` → `Pitching Wedge`
  - `GapWedge` → `Gap Wedge`
  - `SandWedge` → `Sand Wedge`
  - `LobWedge` → `Lob Wedge`
  - `46Wedge`–`64Wedge` (even degrees) → `46° Wedge`–`64° Wedge`
  - `Putter` → `Putter`

- `display_club(name: str) -> str` — looks up `CLUB_DISPLAY`. Fallback for unknown clubs: use `re.sub(r'(\d+)([A-Z])', r'\1 \2', re.sub(r'([a-z])([A-Z])', r'\1 \2', name))`. Then, if the result matches `^\d+ Wedge$`, insert `°` before `Wedge` (e.g. `"50Wedge"` → `"50 Wedge"` → `"50° Wedge"`). This handles any future Trackman identifier gracefully.

**Where it's applied (rendering layer only — internal data stays as-is):**

1. **Sidebar** — club filter multiselect: `format_func=display_club`
2. **Sessions Overview** — personal records "Best carry by club" table: map the `club` column via `.map(display_club)`
3. **Trends** — before passing to `px.line`/`px.histogram`, add a `_club_display` column via `.map(display_club)` and use it as the `color=` column. This makes Plotly use display names in legends automatically.
4. **Session Detail** — same approach: add `_club_display` column, use as `color=` in scatter/sequence charts. Shot log `Club` column: rename values via `.map(display_club)` on the editor display copy.
5. **Club Stats** — bar chart: map club column before passing to `px.bar`. Averages table: map the index.
6. **Dispersion** — club multiselect: `format_func=display_club`. Chart trace `name=` parameters: wrap with `display_club()`. Ellipse traces: `name=f"{display_club(club)} ±1σ"`. Impact chart `text=` and `name=`: wrap with `display_club()`. `club_color` dict stays keyed by raw names internally; only the trace `name=` is transformed.
7. **Quality Analysis** — club filter multiselect: `format_func=display_club`. Correlation matrix column headers: map via `display_club` when building `_corr_cols`.

**What does NOT change:**
- DB values (always raw Trackman identifiers)
- `CLUB_ORDER`, `_CLUB_RANK`, `club_color` keys — all stay keyed by raw internal names
- `TOUR_CARRY`, `TOUR_DISP` keys — lookups always use raw club names (in `score_shot_quality`), no changes needed
- CSV export — keeps raw club names (machine-readable export; display names are a UI concern)

---

## Feature 2: Session Comparison Mode (inside Session Detail tab)

### Problem

Golfers want to compare a specific session against one or more other sessions to see improvement or regression. Currently the multi-select merges everything into one view with no side-by-side breakdown.

### Design

**New UI elements in Session Detail (below existing session picker):**

1. **"Compare to…" multi-select** — visible only when: (a) "All sessions" is unchecked, AND (b) exactly 1 session is selected in the main picker. Otherwise hidden. If the user changes the main picker from 1 to 2+ sessions, any compare selection is ignored (not rendered). Session labels use the same `date – title` format as the main picker.

2. **When comparison sessions are selected, the Averages section transforms:**
   - Render as a Streamlit dataframe/table (not metric tiles) for clean columnar layout
   - Columns: `Metric | Primary (date) | Comp Avg | Δ`
   - Rows: SQS, Ball Speed, Club Speed, Smash Factor, Carry, Total, Launch Angle, Total Spin, Attack Angle, Club Path, Face Angle, Face to Path
   - Individual comparison session columns are NOT shown (would be too wide with 4+ comps). Only the pooled `Comp Avg` column appears.
   - `Δ` = primary minus comp avg. Formatted with `+`/`-` prefix.
   - Color: use Streamlit's dataframe styling — green background for "better" deltas, red for "worse" (direction-aware per metric).
   - The existing metric tiles with "Δ vs previous session" are replaced by this table when compare mode is active.

3. **Per-club comparison table (below the metric summary):**
   - Metric dropdown selector: list includes `_sqs` (displayed as "SQS"), plus all available metrics from `KEY_METRICS`
   - Table rows = clubs hit in *any* of the selected sessions (sorted by `CLUB_ORDER`). Club names displayed via `display_club()`.
   - Columns: `Club | Primary Avg | Comp Avg | Δ | Primary n | Comp n`
   - `Comp Avg` pools all comparison sessions together
   - Δ color-coded same as metric summary
   - Cells where a club has no data in one side show "–" (em dash). Rows where *both* sides are null are omitted entirely.
   - Clubs not in `TOUR_CARRY` will show "–" for SQS (since `_sqs` is `NaN` for those clubs)

**Direction-awareness for color coding:**
- "Higher is better": `carry`, `total`, `ball_speed`, `club_speed`, `smash_factor`, `_sqs`
- "Lower absolute value is better": `face_to_path`, `club_path`, `face_angle`, `offline`, `impact_offset`, `impact_height`, `spin_axis`
- "Neutral" (no color): everything else (`launch_angle`, `total_spin`, `dynamic_loft`, etc.)

**Edge cases:**
- Primary session has 0 non-excluded shots → show "No shot data" info, skip comparison layout
- No overlapping clubs → table shows all clubs, with "–" in the side that has no data
- "Compare to…" is empty (default) → Session Detail works exactly as today, no changes

**What stays the same:**
- Scatter plot, shot sequence chart, and shot log continue working as-is (unaffected by compare mode)
- Multi-session selection in the main picker (2+ sessions without compare mode) continues as-is — merged view, no comparison layout
