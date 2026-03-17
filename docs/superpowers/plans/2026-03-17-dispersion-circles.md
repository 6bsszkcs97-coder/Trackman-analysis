# Dispersion Circles Style & Mutual Exclusivity Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When dispersion circles are enabled, hide landing dots (for clubs that qualify for an ellipse) and render filled solid-border ellipses instead of dashed outlines.

**Architecture:** All changes are in the dispersion chart section of `app.py` (~lines 1089–1145). The ellipse block is moved to run before the dots block so `clubs_with_ellipse` is populated before dots consume it. A `_hex_to_rgba` helper is added at module level just above the TAB 5 comment.

**Tech Stack:** Python, Streamlit, Plotly (`plotly.graph_objects`), NumPy

---

## Chunk 1: All dispersion circles changes

### Task 1: Add `_hex_to_rgba` helper

**Files:**
- Modify: `app.py` — immediately above the `# TAB 5 – Dispersion` comment (~line 1013)

- [ ] **Step 1: Find the insertion point**

  Open `app.py` and locate:
  ```python
  # TAB 5 – Dispersion
  ```
  (around line 1013)

- [ ] **Step 2: Insert the helper immediately above that line**

  ```python
  def _hex_to_rgba(hex_color: str, alpha: float) -> str:
      """Convert a hex colour string (e.g. '#636EFA') to an rgba() CSS string."""
      h = hex_color.lstrip("#")
      r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
      return f"rgba({r},{g},{b},{alpha})"


  ```

- [ ] **Step 3: Verify syntax**

  ```bash
  cd "/Users/stevenmoretti/Documents/Projects/Trackman analysis"
  python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"
  ```
  Expected: `OK`

---

### Task 2: Swap block order — ellipses before dots

**Context:** In the current file, the dots block (~line 1089) runs before the ellipse block (~line 1109). `clubs_with_ellipse` must be populated by the ellipse loop before the dots block can use it, so these two blocks must be swapped.

**Files:**
- Modify: `app.py` ~lines 1089–1145

- [ ] **Step 1: Locate both blocks**

  **Dots block** (currently first, ~line 1089):
  ```python
  # Landing dots — always rendered in Top-down view, unless the club has an ellipse
  if view_mode == "Top-down":
      for club in sel_clubs:
          ...
  ```

  **Ellipse block** (currently second, ~line 1109):
  ```python
  # Dispersion circles: ±1σ ellipse around each club's landing centroid
  if view_mode == "Top-down" and show_circles:
      ...
  ```

- [ ] **Step 2: Replace both blocks together with this new ordering**

  Delete everything from `# Landing dots` through the end of the ellipse block (including the crosshair `add_trace`), and replace with the following — ellipse block first, dots block second:

  ```python
                  # Dispersion circles: ±1σ ellipse around each club's landing centroid
                  # Must run BEFORE the dots block so clubs_with_ellipse is populated first.
                  clubs_with_ellipse: set[str] = set()
                  if view_mode == "Top-down" and show_circles:
                      theta = np.linspace(0, 2 * np.pi, 120)
                      for club in sel_clubs:
                          pts = landing_pts[club]
                          if len(pts) < 3:
                              continue
                          lats    = np.array([p[0] for p in pts])
                          carries = np.array([p[1] for p in pts])
                          c_lat, c_carry = lats.mean(), carries.mean()
                          r_lat   = lats.std()
                          r_carry = carries.std()
                          if r_lat == 0 or r_carry == 0:
                              continue
                          clubs_with_ellipse.add(club)
                          fig_disp.add_trace(go.Scatter(
                              x=c_lat   + r_lat   * np.cos(theta),
                              y=c_carry + r_carry * np.sin(theta),
                              mode="lines",
                              name=f"{club} ±1σ",
                              fill="toself",
                              fillcolor=_hex_to_rgba(club_color[club], 0.12),
                              line=dict(color=club_color[club], width=2.5),
                              opacity=1.0,
                              showlegend=True,
                          ))
                          fig_disp.add_trace(go.Scatter(
                              x=[c_lat], y=[c_carry],
                              mode="markers",
                              name=f"{club} center",
                              marker=dict(color=club_color[club], size=9, symbol="cross-thin",
                                          line=dict(width=2, color=club_color[club])),
                              showlegend=False,
                          ))

                  # Landing dots — rendered for all clubs except those with a valid ellipse
                  if view_mode == "Top-down":
                      for club in sel_clubs:
                          if show_circles and club in clubs_with_ellipse:
                              continue  # ellipse is the spatial summary for this club
                          pts = landing_pts[club]
                          if not pts:
                              continue
                          fig_disp.add_trace(go.Scatter(
                              x=[p[0] for p in pts],
                              y=[p[1] for p in pts],
                              mode="markers",
                              name=club,
                              showlegend=True,
                              marker=dict(
                                  color=club_color[club],
                                  size=10,
                                  line=dict(color="white", width=1.5),
                              ),
                              opacity=0.95,
                          ))
  ```

  Changes from current code:
  - Block order swapped: ellipses now run first
  - `clubs_with_ellipse: set[str] = set()` declared before ellipse loop
  - `clubs_with_ellipse.add(club)` called for each qualifying club
  - Ellipse: `dash="dash"` removed, `width` 2→2.5, `fill="toself"`, `fillcolor` at 12% opacity, `opacity` 0.9→1.0, `showlegend=True` explicit
  - Dots: `if show_circles and club in clubs_with_ellipse: continue` added

- [ ] **Step 3: Verify syntax**

  ```bash
  python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"
  ```
  Expected: `OK`

---

### Task 3: Verify in browser

- [ ] **Step 1: Confirm the app is running at `http://localhost:8501`**

  If not:
  ```bash
  cd "/Users/stevenmoretti/Documents/Projects/Trackman analysis"
  streamlit run app.py
  ```

- [ ] **Step 2: Navigate to the Dispersion tab**

  Click **🗺️ Dispersion**.

- [ ] **Step 3: Circles off (default) — dots visible**

  - Select 2+ clubs (e.g. 7 Iron + PW)
  - Confirm **Dispersion circles (±1σ)** is unchecked
  - Confirm landing dots render with white halos

- [ ] **Step 4: Enable circles — dots replaced by ellipses**

  - Check **Dispersion circles (±1σ)**
  - Confirm landing dots disappear for clubs with valid ellipses
  - Confirm filled solid-border ellipses appear with a soft tinted interior
  - Confirm crosshair at each ellipse centre
  - Confirm one legend entry per club (e.g. "7 Iron ±1σ"), no duplicates

- [ ] **Step 5: Disable circles — dots return**

  - Uncheck **Dispersion circles (±1σ)**
  - Confirm dots reappear for all clubs

---

### Task 4: Commit

- [ ] **Step 1: Stage and commit**

  ```bash
  cd "/Users/stevenmoretti/Documents/Projects/Trackman analysis"
  git add app.py
  git commit -m "feat: filled dispersion circles replace dots when enabled

  - Ellipses now solid border (width 2.5) with 12% opacity fill
  - Landing dots hidden for clubs that have a valid ellipse
  - Clubs with <3 shots or zero std retain their dots as fallback
  - Swap block order: ellipses populate clubs_with_ellipse before dots read it
  - Add _hex_to_rgba() helper for fillcolor conversion"
  ```
