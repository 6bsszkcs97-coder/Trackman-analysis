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

- `display_club(name: str) -> str` — looks up `CLUB_DISPLAY`, falls back to regex that inserts spaces before uppercase letters and appends `°` before `Wedge` for numeric prefixes (handles any future club Trackman adds).

**Where it's applied (rendering layer only — internal data stays as-is):**

1. **Sidebar** — club filter multiselect: `format_func=display_club`
2. **Sessions Overview** — personal records "Best carry by club" table: map the `club` column
3. **Trends** — chart legends, axis labels: map via `display_club`
4. **Session Detail** — scatter legends, shot sequence legends, shot log `Club` column
5. **Club Stats** — bar chart x-axis, averages table index
6. **Dispersion** — club multiselect `format_func`, chart legends, impact chart labels
7. **Quality Analysis** — club filter multiselect `format_func`, correlation matrix column headers

**What does NOT change:**
- DB values (always raw Trackman identifiers)
- `CLUB_ORDER`, `_CLUB_RANK`, `club_color` keys — all stay internal
- `TOUR_CARRY`, `TOUR_DISP` keys — already have some aliases; no changes needed

---

## Feature 2: Session Comparison Mode (inside Session Detail tab)

### Problem

Golfers want to compare a specific session against one or more other sessions to see improvement or regression. Currently the multi-select merges everything into one view with no side-by-side breakdown.

### Design

**New UI elements in Session Detail (below existing session picker):**

1. **"Compare to…" multi-select** — appears when a single primary session is selected (hidden when "All sessions" is checked or when 2+ sessions are already selected in the main picker). Lists all sessions *except* the currently selected one.

2. **When comparison sessions are selected, the Averages section transforms:**
   - Layout: columns = `[Primary Session] | [Comp 1] | [Comp 2] | … | [Comp Avg] | [Δ]`
   - Each column shows the session's average for key metrics (SQS, ball speed, carry, club speed, smash factor, etc.)
   - The `Δ` column = primary minus the pooled average of all comparison sessions
   - Color: green text when primary is better, red when worse (direction-aware: higher carry/speed/smash = better; lower face-to-path/offline = better)

3. **Per-club comparison table (below the metric summary):**
   - Metric dropdown selector (carry, ball speed, SQS, total, smash factor, etc.)
   - Table rows = clubs hit in *any* of the selected sessions (sorted by `CLUB_ORDER`)
   - Columns = `Club | Primary Avg | Comparison Avg | Δ | Primary Shots | Comp Shots`
   - `Comparison Avg` pools all comparison sessions together
   - Δ color-coded same as above

**Direction-awareness for color coding:**
- "Higher is better": `carry`, `total`, `ball_speed`, `club_speed`, `smash_factor`, `_sqs`
- "Lower absolute value is better": `face_to_path`, `club_path`, `face_angle`, `offline`, `impact_offset`, `impact_height`, `spin_axis`
- "Neutral" (no color): everything else

**When "Compare to…" is empty (default):**
- Session Detail works exactly as today — no visual changes
- The existing "Δ vs previous session" on metric tiles remains as the quick-glance default

**What stays the same:**
- Scatter plot, shot sequence chart, and shot log continue working as-is
- Multi-session selection in the main picker (2+ sessions without compare mode) continues as-is — merged view, no comparison layout
