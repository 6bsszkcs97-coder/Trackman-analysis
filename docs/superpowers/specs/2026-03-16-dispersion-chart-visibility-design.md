# Dispersion Chart Visibility — Design Spec
_Date: 2026-03-16_

## Problem

The dispersion chart (Top-down view) is hard to read when multiple clubs are displayed:
- Tracer lines at 55% opacity overlap into a tangled mass
- Club colors blend together
- Landing dots are too small to spot individual shot clusters

## Approach: Ghost tracers + prominent landing dots

Fade tracers to near-invisible so they convey flight shape without dominating, and always render large, white-haloed landing dots so the dispersion cluster is the visual centrepiece.

## Changes to `app.py` (Top-down view only)

### 1. Tracer opacity
- **Before:** `opacity=0.55`
- **After:** `opacity=0.15`

Applies to the `go.Scatter` trace added in the main tracer loop (`mode="lines"`).

### 2. Landing dots — always rendered
Currently landing dots are only drawn when `dots_only=True`. Change so they are always drawn in Top-down view regardless of the tracer toggle.

Dot style:
- `size=10` (up from 7)
- `line=dict(color="white", width=1.5)` — white halo for contrast against any background
- `opacity=0.95` (up from 0.75 in the old dots-only branch)

The existing `landing_pts[club]` dict already collects the coordinates, so no data-model change is needed.

### 3. Replace "Dots only" checkbox with "Show tracers" toggle
- **Remove:** `dots_only = st.checkbox("Dots only (no tracers)", ...)`
- **Add:** `show_tracers = st.checkbox("Show tracers", value=True, key="disp_tracers")`
- The `xs.extend(...)` / `ys.extend(...)` lines inside the inner trajectory loop are guarded by `if show_tracers:` (replacing the old `if not dots_only:` guard)
- The existing `if xs:` guard is moved inside the `if show_tracers:` block; structure becomes: `if show_tracers: [extend xs/ys] ... if xs: [add_trace(lines)]`
- Landing dot traces are always added (independent of toggle)
- `has_any_traj = True` sits outside (before) the `if show_tracers:` block — it must remain there so that the "No trajectory data found" warning is correctly suppressed when tracers are hidden

### 4. Legend entries
- Tracer traces (`mode="lines"`) carry `name=club` and `showlegend=True` (owns the legend entry when visible)
- Landing dot traces (`mode="markers"`) use `showlegend=not show_tracers` — dots own the legend entry when tracers are hidden, suppressed when tracers are visible (avoiding duplicates)

## Out of scope
- Side view is unchanged
- Color palette unchanged (default Plotly qualitative)
- Dispersion circles (±1σ) unchanged
