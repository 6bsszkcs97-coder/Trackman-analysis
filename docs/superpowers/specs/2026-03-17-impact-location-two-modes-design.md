# Clubface Impact Location — Two-Mode Redesign

## Problem

The current Clubface Impact Location chart has two bugs:

1. **Duplicate legend entries** — scatter dots and centroid markers both use `name=club`, producing two legend entries per club.
2. **Broken Plotly toggles** — clicking a club in the legend only hides one of the two traces for that club (the other stays visible).

Root cause: the current implementation always overlays centroid markers on top of individual shot scatter dots, creating two independent traces per club with the same name.

## Solution

Replace the current multi-option control set with a single radio toggle: **Aggregate | Scatter**. The two modes are mutually exclusive — only one is ever rendered at a time.

### Mode 1: Aggregate

- One `go.Scatter` trace per selected club
- Each trace plots a single point: the mean `impact_offset` (x) and mean `impact_height` (y) for that club
- Marker: size 14, filled with club colour, white border via `line=dict(width=2.5, color="white")`
- Text label (club name) shown above the marker via `mode="markers+text"`, `textposition="top center"`
- Hover template: `"<b>%{text}</b><br>Horizontal: %{x:.2f} cm<br>Vertical: %{y:.2f} cm<br>n=%{customdata[0]}"` where `text=club`, `customdata=[[n_shots]]`
- One legend entry per club ✓

### Mode 2: Scatter

- One `go.Scatter` trace per selected club (replaces `px.scatter`)
- Each trace plots all individual shots for that club
- Marker: size 8, filled with club colour, white border (1.5px), opacity 0.6
- Hover template: `"<b>Shot %{customdata[0]}</b><br>Carry: %{customdata[1]:.0f} yds<br>Smash: %{customdata[2]:.2f}"` where `customdata=[[shot_number, carry, smash_factor]]` per row
- One legend entry per club; clicking in legend toggles all shots for that club ✓

### Shared elements (both modes)

- Clubface outline rectangle (`x0=-2.5, y0=-2.0, x1=2.5, y1=2.0`, dashed gray)
- Horizontal and vertical crosshairs at 0,0
- Fixed axis range: x `[-3.5, 3.5]`, y `[-3.0, 3.0]` (keep existing y range)
- `scaleanchor="x"`, `scaleratio=1` on y-axis (keep existing 1:1 aspect ratio)
- `plot_bgcolor="white"`, `height=810` (keep existing height)

## Controls — Before vs After

| Before | After |
|---|---|
| `st.radio("Display mode", ["Scatter", "Density"])` | `st.radio("Display mode", ["Aggregate", "Scatter"])` |
| `st.selectbox("Color by", [...])` | *(removed)* |
| `st.checkbox("Show individual shots")` | *(removed)* |
| Density contours (Histogram2dContour) | *(removed)* |

The **Impact Trend Over Time** section below the chart is unchanged.

## Files Changed

- `app.py` — dispersion tab, impact location section (~lines 1197–1339)

## Deleted Code Paths

The following branches are explicitly removed (not just the controls — the rendering logic too):

- `if show_individual: ... else: go.Figure()` centroid-only branch in Scatter mode
- All `Histogram2dContour` density contour rendering
- The `color_by` selectbox and its two `px.scatter` branches (club-colour and continuous-scale). Continuous metric colouring (e.g. "Color by Smash Factor") is intentionally dropped — out of scope.

## Out of Scope

- Impact trend charts (unchanged)
- Dispersion top-down/side-view charts (unchanged)
- Sidebar club selector (unchanged)
