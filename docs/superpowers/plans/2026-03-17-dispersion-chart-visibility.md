# Dispersion Chart Visibility Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dispersion chart's Top-down view more readable by fading tracer lines to ghosts, always rendering large prominent landing dots, and replacing the "Dots only" checkbox with a "Show tracers" toggle.

**Architecture:** All changes are isolated to the Top-down branch of the dispersion chart section in `app.py` (around lines 1034–1097). No new files, no schema changes, no data-model changes — the `landing_pts` dict already collects every club's landing coordinates unconditionally.

**Tech Stack:** Python, Streamlit, Plotly (`plotly.graph_objects`)

---

## Chunk 1: Dispersion chart visibility changes

### Task 1: Replace "Dots only" checkbox with "Show tracers" toggle

**Files:**
- Modify: `app.py` ~line 1035

- [ ] **Step 1: Locate the checkbox**

  Open `app.py` and find this block (around line 1034):
  ```python
  if view_mode == "Top-down":
      dots_only    = st.checkbox("Dots only (no tracers)", value=False, key="disp_dots")
      show_circles = st.checkbox("Dispersion circles (±1σ)", value=False, key="disp_circles")
  else:
      dots_only    = False
      show_circles = False
  ```

- [ ] **Step 2: Replace `dots_only` with `show_tracers`**

  Replace with:
  ```python
  if view_mode == "Top-down":
      show_tracers = st.checkbox("Show tracers", value=True, key="disp_tracers")
      show_circles = st.checkbox("Dispersion circles (±1σ)", value=False, key="disp_circles")
  else:
      show_tracers = True
      show_circles = False
  ```

---

### Task 2: Restructure tracer rendering to be conditional on `show_tracers`

**Files:**
- Modify: `app.py` ~lines 1058–1083

- [ ] **Step 1: Locate the inner shot loop**

  Find this block (around line 1058):
  ```python
  for club in sel_clubs:
      club_shots = [t for t in traj_data if t["club"] == club][-max_shots:]
      xs, ys = [], []
      for shot in club_shots:
          traj = parse_trajectory(shot["raw_json"])
          if not traj:
              continue
          has_any_traj = True
          if view_mode == "Top-down":
              if not dots_only:
                  xs.extend([pt.get("Z", 0) for pt in traj] + [None])
                  ys.extend([pt.get("X", 0) for pt in traj] + [None])
              landing_pts[club].append(
                  (traj[-1].get("Z", 0), traj[-1].get("X", 0))
              )
          else:
              xs.extend([pt.get("X", 0) for pt in traj] + [None])
              ys.extend([pt.get("Y", 0) for pt in traj] + [None])

      if xs:
          fig_disp.add_trace(go.Scatter(
              x=xs, y=ys,
              mode="lines",
              name=club,
              line=dict(color=club_color[club], width=1.2),
              opacity=0.55,
          ))
  ```

- [ ] **Step 2: Replace with restructured version**

  Replace the entire block above with:
  ```python
  for club in sel_clubs:
      club_shots = [t for t in traj_data if t["club"] == club][-max_shots:]
      xs, ys = [], []
      for shot in club_shots:
          traj = parse_trajectory(shot["raw_json"])
          if not traj:
              continue
          has_any_traj = True
          if view_mode == "Top-down":
              # NOTE: has_any_traj is set above, before the show_tracers guard —
              # keep it there so the "No trajectory data" warning is suppressed
              # even when tracers are toggled off.
              if show_tracers:
                  xs.extend([pt.get("Z", 0) for pt in traj] + [None])
                  ys.extend([pt.get("X", 0) for pt in traj] + [None])
              landing_pts[club].append(
                  (traj[-1].get("Z", 0), traj[-1].get("X", 0))
              )
          else:
              xs.extend([pt.get("X", 0) for pt in traj] + [None])
              ys.extend([pt.get("Y", 0) for pt in traj] + [None])

      if show_tracers:
          if xs:
              fig_disp.add_trace(go.Scatter(
                  x=xs, y=ys,
                  mode="lines",
                  name=club,
                  showlegend=True,  # tracer owns the legend entry when visible
                  line=dict(color=club_color[club], width=1.2),
                  opacity=0.15,
              ))
  ```

  Key changes from the old code:
  - `if not dots_only:` → `if show_tracers:`
  - `if xs: add_trace(...)` moves inside `if show_tracers:`
  - Tracer `opacity` changes from `0.55` → `0.15`

---

### Task 3: Always render landing dots (replace old dots-only block)

**Files:**
- Modify: `app.py` ~lines 1084–1097

- [ ] **Step 1: Locate the dots-only rendering block**

  Find this block (around line 1084):
  ```python
  # Dots-only mode: plot landing points as markers
  if view_mode == "Top-down" and dots_only:
      for club in sel_clubs:
          pts = landing_pts[club]
          if not pts:
              continue
          fig_disp.add_trace(go.Scatter(
              x=[p[0] for p in pts],
              y=[p[1] for p in pts],
              mode="markers",
              name=club,
              marker=dict(color=club_color[club], size=7),
              opacity=0.75,
          ))
  ```

- [ ] **Step 2: Replace with always-on landing dots**

  Replace with:
  ```python
  # Landing dots — always rendered in Top-down view
  if view_mode == "Top-down":
      for club in sel_clubs:
          pts = landing_pts[club]
          if not pts:
              continue
          fig_disp.add_trace(go.Scatter(
              x=[p[0] for p in pts],
              y=[p[1] for p in pts],
              mode="markers",
              name=club,
              showlegend=not show_tracers,
              marker=dict(
                  color=club_color[club],
                  size=10,
                  line=dict(color="white", width=1.5),
              ),
              opacity=0.95,
          ))
  ```

  Key changes:
  - Guard changes from `dots_only` → always-on (`if view_mode == "Top-down":`)
  - `showlegend=not show_tracers` — dots own the legend entry when tracers are hidden; tracers own it when visible (avoiding duplicates)
  - `size=7` → `size=10`
  - Added `line=dict(color="white", width=1.5)` for white halo
  - `opacity=0.75` → `0.95`

---

### Task 4: Verify in browser

- [ ] **Step 1: Start the app**

  ```bash
  cd "/Users/stevenmoretti/Documents/Projects/Trackman analysis"
  streamlit run app.py
  ```

- [ ] **Step 2: Navigate to the Dispersion tab**

  Open `http://localhost:8501` → click **🗺️ Dispersion** tab.

- [ ] **Step 3: Verify default state (tracers on)**

  - Select 2+ clubs (e.g. 7 Iron + PW)
  - Confirm tracer lines are visible but faint (ghosted)
  - Confirm landing dots are large with white halos, clearly visible at each club's cluster
  - Confirm each club appears once in the legend

- [ ] **Step 4: Toggle "Show tracers" off**

  - Uncheck **Show tracers**
  - Confirm tracer lines disappear entirely
  - Confirm landing dots remain, and each club still appears once in the legend

- [ ] **Step 5: Verify `has_any_traj` / warning behaviour when tracers off**

  - Keep 2+ clubs selected, uncheck **Show tracers**
  - Confirm the "No trajectory data found" warning does NOT appear (it should stay hidden because `has_any_traj` is set before the tracer guard)

- [ ] **Step 6: Verify side view is unaffected**

  - Switch to **Side view**
  - Confirm ball flight profiles render normally

---

### Task 5: Commit

- [ ] **Step 1: Stage and commit**

  ```bash
  git add app.py
  git commit -m "feat: ghost tracers + prominent landing dots on dispersion chart

  - Tracer opacity 0.55 → 0.15 (ghost effect)
  - Landing dots always visible in top-down view (was dots-only mode)
  - Dot size 7 → 10 with white halo (opacity 0.95)
  - Replace 'Dots only' checkbox with 'Show tracers' toggle (default on)
  - Dots own legend entry when tracers off; tracers own it when on"
  ```
