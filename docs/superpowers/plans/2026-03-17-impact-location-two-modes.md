# Impact Location Two-Mode Redesign — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Clubface Impact Location chart's broken multi-option controls with two clean, mutually exclusive modes: Aggregate (one centroid per club) and Scatter (all shots per club).

**Architecture:** Single contiguous block in `app.py` (~lines 1216–1339) is replaced. The `imp_col_l` controls section is simplified to one radio; the `imp_col_r` rendering section is replaced with two clean branches. All other code (impact data filter, subheader, empty check, trend section) is untouched.

**Tech Stack:** Python, Streamlit, Plotly `go.Scatter`

---

## Chunk 1: Replace controls + rendering block

### Task 1: Rewrite the impact location controls and chart

**Files:**
- Modify: `/Users/stevenmoretti/Documents/Projects/Trackman analysis/app.py:1216-1339`

**Context:** The current block (lines 1216–1339) has:
- A radio `["Scatter", "Density"]` + `color_by` selectbox + `show_individual` checkbox in `imp_col_l`
- Complex rendering logic with `px.scatter`, `go.Histogram2dContour`, and always-on centroid overlay in `imp_col_r`

This causes duplicate legend entries and broken Plotly toggles.

**Spec:** `docs/superpowers/specs/2026-03-17-impact-location-two-modes-design.md`

- [ ] **Step 1: Replace the entire block lines 1216–1339**

Replace from `with imp_col_l:` through `st.plotly_chart(fig_imp, use_container_width=True)` with:

```python
                with imp_col_l:
                    impact_view = st.radio(
                        "Display mode", ["Aggregate", "Scatter"],
                        key="impact_view",
                        help="Aggregate = one centroid per club · Scatter = all individual shots",
                    )

                with imp_col_r:
                    fig_imp = go.Figure()

                    if impact_view == "Aggregate":
                        centroid_df = (
                            impact_df.groupby("club")[["impact_offset", "impact_height"]]
                            .agg(
                                impact_offset=("impact_offset", "mean"),
                                impact_height=("impact_height", "mean"),
                                n=("impact_offset", "count"),
                            )
                            .reset_index()
                        )
                        for _, row in centroid_df.iterrows():
                            c = club_color.get(row["club"], "#333333")
                            fig_imp.add_trace(go.Scatter(
                                x=[row["impact_offset"]],
                                y=[row["impact_height"]],
                                mode="markers+text",
                                name=row["club"],
                                text=[row["club"]],
                                textposition="top center",
                                textfont=dict(size=10, color=c),
                                customdata=[[int(row["n"])]],
                                hovertemplate=(
                                    "<b>%{text}</b><br>"
                                    "Horizontal: %{x:.2f} cm<br>"
                                    "Vertical: %{y:.2f} cm<br>"
                                    "n=%{customdata[0]}<extra></extra>"
                                ),
                                marker=dict(
                                    size=14,
                                    color=c,
                                    line=dict(width=2.5, color="white"),
                                ),
                                showlegend=True,
                            ))
                        fig_imp.update_layout(title="Impact Location — Club Averages")

                    else:  # Scatter
                        for i, club in enumerate(sorted(sel_clubs)):
                            cd = impact_df[impact_df["club"] == club]
                            if cd.empty:
                                continue
                            c = club_color.get(club, palette[i % len(palette)])
                            fig_imp.add_trace(go.Scatter(
                                x=cd["impact_offset"],
                                y=cd["impact_height"],
                                mode="markers",
                                name=club,
                                customdata=cd[["shot_number", "carry", "smash_factor"]].values,
                                hovertemplate=(
                                    "<b>Shot %{customdata[0]}</b><br>"
                                    "Carry: %{customdata[1]:.0f} yds<br>"
                                    "Smash: %{customdata[2]:.2f}<extra></extra>"
                                ),
                                marker=dict(
                                    size=8,
                                    color=c,
                                    opacity=0.6,
                                    line=dict(width=1.5, color="white"),
                                ),
                                showlegend=True,
                            ))
                        fig_imp.update_layout(title="Impact Location — All Shots")

                    # Clubface outline + crosshairs (shared)
                    fig_imp.add_shape(
                        type="rect", x0=-2.5, y0=-2.0, x1=2.5, y1=2.0,
                        line=dict(color="gray", dash="dot", width=1),
                        fillcolor="rgba(180,180,180,0.06)",
                    )
                    fig_imp.add_hline(y=0, line_dash="dot", line_color="lightgray", line_width=0.8)
                    fig_imp.add_vline(x=0, line_dash="dot", line_color="lightgray", line_width=0.8)

                    fig_imp.update_layout(
                        height=810, plot_bgcolor="white",
                        xaxis=dict(
                            title="← Heel  ·  Horizontal (cm)  ·  Toe →",
                            range=[-3.5, 3.5],
                            constrain="domain",
                            fixedrange=True,
                        ),
                        yaxis=dict(
                            title="Vertical (cm)",
                            range=[-3.0, 3.0],
                            scaleanchor="x",
                            scaleratio=1,
                            fixedrange=True,
                        ),
                    )
                    st.plotly_chart(fig_imp, use_container_width=True)
```

- [ ] **Step 2: Verify syntax**

```bash
cd "/Users/stevenmoretti/Documents/Projects/Trackman analysis" && python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Verify deleted variables are not referenced downstream**

```bash
grep -n "color_by\|show_individual\|Density\|Histogram2dContour" "/Users/stevenmoretti/Documents/Projects/Trackman analysis/app.py" | grep -v "^Binary"
```

Expected: no matches in the impact section (lines 1197–1400). Any match outside that range is pre-existing and fine.

- [ ] **Step 4: Commit**

```bash
cd "/Users/stevenmoretti/Documents/Projects/Trackman analysis"
git add app.py
git commit -m "refactor: replace impact location chart with Aggregate/Scatter two-mode design

- Removes duplicate legend entries (dots + centroid both named by club)
- Fixes broken Plotly legend toggles
- Aggregate mode: one centroid per club with hover showing avg + n
- Scatter mode: all shots per club, one legend entry, toggleable
- Removes: Density contours, Color-by selector, Show individual shots toggle"
```
