# Dispersion Circles — Style & Mutual Exclusivity Design Spec
_Date: 2026-03-17_

## Problem

1. When dispersion circles are enabled, individual landing dots and circles are rendered on top of each other, creating visual clutter
2. The circles themselves are hard to see: thin dashed border, no fill, low contrast

## Changes to `app.py`

### 1. Mutual exclusivity — hide dots when circles are on (with fallback)

The landing dots block (currently `if view_mode == "Top-down":`) is modified to:
- Skip dot rendering for clubs that **have a valid ellipse** (≥3 shots and non-zero std in both axes)
- Still render dots for clubs that **do not qualify** for an ellipse (< 3 shots, or zero std in either axis)

Implementation: compute `clubs_with_ellipse: set[str]` before the dots block (during the ellipse loop), then use it in the dots block:

```python
# Dots block:
if view_mode == "Top-down":
    for club in sel_clubs:
        if show_circles and club in clubs_with_ellipse:
            continue  # ellipse is the spatial summary; skip dots for this club
        pts = landing_pts[club]
        if not pts:
            continue
        fig_disp.add_trace(go.Scatter(...dot trace...))
```

`clubs_with_ellipse` is a `set[str]` populated inside the existing ellipse loop immediately before `fig_disp.add_trace(...)` for each qualifying club. Clubs skipped by the `< 3 pts` or `std == 0` guards are not added to `clubs_with_ellipse` and therefore retain their dot traces even when `show_circles=True`.

### 2. Restyle ellipse traces (Option A — filled + solid border)

Current ellipse trace:
```python
fig_disp.add_trace(go.Scatter(
    x=c_lat + r_lat * np.cos(theta),
    y=c_carry + r_carry * np.sin(theta),
    mode="lines",
    name=f"{club} ±1σ",
    line=dict(color=club_color[club], width=2, dash="dash"),
    opacity=0.9,
))
```

New ellipse trace:
```python
fig_disp.add_trace(go.Scatter(
    x=c_lat + r_lat * np.cos(theta),
    y=c_carry + r_carry * np.sin(theta),
    mode="lines",
    name=f"{club} ±1σ",
    fill="toself",
    fillcolor=_hex_to_rgba(club_color[club], 0.12),
    line=dict(color=club_color[club], width=2.5),
    opacity=1.0,
    showlegend=True,  # explicit; Plotly default is True, but stated for clarity
))
```

Changes:
- `dash="dash"` removed → solid border
- `width=2` → `width=2.5`
- Added `fill="toself"` + `fillcolor` at 12% opacity
- `opacity=0.9` → `1.0` (fill opacity is controlled by `fillcolor` alpha; line is fully opaque)

### 3. Helper function `_hex_to_rgba`

Add immediately above the `# TAB 5 – Dispersion` comment (module-level, not inside any `with` block):

```python
def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert a hex color string to an rgba() CSS string."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"
```

`px.colors.qualitative.Plotly` colors are standard 6-digit hex strings (e.g. `"#636EFA"`), so this conversion is safe.

### 4. Centre crosshair — unchanged

The existing `go.Scatter` crosshair marker at `(c_lat, c_carry)` is kept as-is.

### 5. Legend

- When `show_circles=True`: only `{club} ±1σ` legend entries appear (dots are suppressed, crosshair already has `showlegend=False`)
- When `show_circles=False`: dot traces own the legend (existing behaviour)

## Out of scope
- Side view unchanged
- `show_tracers` checkbox unchanged
- No changes to how `landing_pts` is collected
