"""
Trackman Golf Dashboard
=======================
Run with:  streamlit run app.py
"""
import json

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import db

st.set_page_config(page_title="Trackman Dashboard", page_icon="⛳", layout="wide")

METRIC_LABELS = {
    "ball_speed":       "Ball Speed (mph)",
    "club_speed":       "Club Speed (mph)",
    "smash_factor":     "Smash Factor",
    "launch_angle":     "Launch Angle (°)",
    "launch_direction": "Launch Direction (°)",
    "total_spin":       "Total Spin (rpm)",
    "spin_axis":        "Spin Axis (°)",
    "attack_angle":     "Attack Angle (°)",
    "club_path":        "Club Path (°)",
    "face_angle":       "Face Angle (°)",
    "face_to_path":     "Face to Path (°)",
    "dynamic_loft":     "Dynamic Loft (°)",
    "carry":            "Carry (yds)",
    "total":            "Total Distance (yds)",
    "offline":          "Offline (yds)",
    "peak_height":      "Peak Height (yds)",
    "descent_angle":    "Descent Angle (°)",
    "impact_offset":    "Impact Offset (cm)",
    "impact_height":    "Impact Height (cm)",
}

KEY_METRICS = ["ball_speed", "club_speed", "smash_factor", "carry", "total",
               "launch_angle", "total_spin", "attack_angle", "club_path", "face_angle"]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
@st.cache_data(ttl=30)
def load_sessions():
    return pd.DataFrame(db.get_sessions())

@st.cache_data(ttl=30)
def load_shots(session_id=None, club=None):
    return pd.DataFrame(db.get_shots(session_id=session_id, club=club))

@st.cache_data(ttl=30)
def load_clubs():
    return db.get_clubs()

@st.cache_data(ttl=30)
def load_trajectories():
    return db.get_trajectories()

def parse_trajectory(raw_json_str):
    """Extract BallTrajectory list from a shot's raw_json string."""
    try:
        stroke = json.loads(raw_json_str)
        traj = stroke.get("BallTrajectory") or stroke.get("Measurement", {}).get("BallTrajectory", [])
        return traj or []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Manual exclusion
# ---------------------------------------------------------------------------
def apply_exclusions(df: pd.DataFrame) -> pd.DataFrame:
    """Mark shots manually excluded by the user (excluded == 1 in DB)."""
    df = df.copy()
    df["_excluded"] = df["excluded"].apply(lambda e: e == 1 if pd.notna(e) else False)
    return df


QUALITY_TIERS  = ["Great", "Good", "Average", "Poor", "Miss"]
QUALITY_COLORS = {
    "Great":   "#2d6a4f",
    "Good":    "#52b788",
    "Average": "#f4a261",
    "Poor":    "#e63946",
    "Miss":    "#6b0504",
}


def _build_sqs_baselines(df: pd.DataFrame) -> dict:
    """Build per-club SQS baselines (medians, IQR tolerances, optional regression)."""
    baselines = {}
    for club in df["club"].dropna().unique():
        cd = df[df["club"] == club]
        b: dict = {}

        carry = cd["carry"].dropna()
        if len(carry) >= 2:
            b["median_carry"] = float(carry.median())
            b["carry_tol"]    = max(float(carry.quantile(0.75) - carry.quantile(0.25)), 5.0)

        offline = cd["offline"].dropna().abs()
        if len(offline) >= 2:
            b["offline_tol"] = max(float(offline.quantile(0.75) - offline.quantile(0.25)), 3.0)

        baselines[club] = b
    return baselines


def _apply_sqs(df: pd.DataFrame, baselines: dict) -> pd.DataFrame:
    """Score each shot 0–100 with the SQS system.

    CarryScore (60%): how far relative to the club's median carry.
    AccuracyScore (40%): how straight (offline vs club tolerance).

    Adds columns: _sqs, _carry_score, _acc_score, _quality
    """
    df = df.copy()
    for col in ["_sqs", "_carry_score", "_acc_score"]:
        df[col] = np.nan
    df["_quality"] = "Average"

    for club, b in baselines.items():
        if not b or "median_carry" not in b:
            continue
        mask = df["club"] == club
        if not mask.any():
            continue
        idx = df.index[mask]
        cd  = df.loc[idx]

        carry = cd["carry"].values.astype(float)
        off   = np.abs(cd["offline"].values.astype(float))

        # ── Expected carry = club median (no speed adjustment) ────────────
        exp_carry = np.full(len(cd), b["median_carry"])

        # ── Component scores ──────────────────────────────────────────────
        # CarryScore: 50 = hit your expected distance, 100 = 1 IQR above, 0 = 1 IQR below
        carry_score = np.where(
            ~np.isnan(carry),
            np.clip(50 + 50 * (carry - exp_carry) / b["carry_tol"], 0, 100),
            np.nan,
        )

        # AccuracyScore: 100 = dead straight, 0 = 2× offline tolerance
        if "offline_tol" in b:
            acc_score = np.where(
                ~np.isnan(off),
                np.clip(100 - 100 * off / (2 * b["offline_tol"]), 0, 100),
                np.nan,
            )
        else:
            acc_score = np.full(len(cd), np.nan)

        # ── Weighted base score (redistribute if a component is missing) ──
        w0    = np.where(~np.isnan(carry_score), 0.60, 0.0)
        w1    = np.where(~np.isnan(acc_score),   0.40, 0.0)
        tot_w = w0 + w1
        base  = np.where(
            tot_w > 0,
            (np.where(~np.isnan(carry_score), carry_score, 0) * w0
             + np.where(~np.isnan(acc_score),  acc_score,  0) * w1) / tot_w,
            np.nan,
        )

        # ── Bonus: +5 if both ≥70, +3 more if both ≥85 ───────────────────
        both = ~np.isnan(carry_score) & ~np.isnan(acc_score)
        ge70 = both & (carry_score >= 70) & (acc_score >= 70)
        ge85 = both & (carry_score >= 85) & (acc_score >= 85)
        bonus = np.where(ge70, 5.0, 0.0) + np.where(ge85, 3.0, 0.0)

        # ── Penalties: −8 extreme offline, −8 way short ───────────────────
        off_tol = b.get("offline_tol", 1e9)
        penalty = (np.where(~np.isnan(off)   & (off   > 3 * off_tol),       8.0, 0.0)
                   + np.where(~np.isnan(carry) & (carry < 0.65 * exp_carry), 8.0, 0.0))

        # ── Final SQS ─────────────────────────────────────────────────────
        sqs = np.where(~np.isnan(base), np.clip(base + bonus - penalty, 0, 100), np.nan)

        # ── Tier assignment ───────────────────────────────────────────────
        sqs_s = pd.Series(sqs, index=idx)
        q     = pd.Series("Average", index=idx)
        q[sqs_s >= 75]                   = "Great"
        q[(sqs_s >= 55) & (sqs_s < 75)] = "Good"
        q[(sqs_s >= 35) & (sqs_s < 55)] = "Average"
        q[(sqs_s >= 20) & (sqs_s < 35)] = "Poor"
        q[sqs_s < 20]                    = "Miss"
        q[sqs_s.isna()]                  = "Average"

        df.loc[idx, "_sqs"]         = sqs
        df.loc[idx, "_carry_score"] = carry_score
        df.loc[idx, "_acc_score"]   = acc_score
        df.loc[idx, "_quality"]     = q.values

    return df


def score_shot_quality(df: pd.DataFrame) -> pd.DataFrame:
    """Compute SQS for every shot in df using cross-session baselines."""
    return _apply_sqs(df, _build_sqs_baselines(df))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fmt_metric(val, col):
    if val is None or pd.isna(val):
        return "–"
    unit = METRIC_LABELS.get(col, col)
    if "mph" in unit:  return f"{val:.1f} mph"
    if "rpm" in unit:  return f"{val:,.0f} rpm"
    if "yds" in unit:  return f"{val:.1f} yds"
    if "°" in unit:    return f"{val:.1f}°"
    return f"{val:.2f}"

def metric_col(col):
    return METRIC_LABELS.get(col, col.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("⛳ Trackman Dashboard")
st.sidebar.markdown("---")

sessions_df = load_sessions()
clubs = load_clubs()

if sessions_df.empty:
    st.title("⛳ Trackman Dashboard")
    st.warning("No data yet. Run `python sync.py` to pull your sessions.", icon="⚠️")
    st.code("python sync.py", language="bash")
    st.stop()

# Date range
sessions_df["date"] = pd.to_datetime(sessions_df["date"], errors="coerce")
min_date, max_date = sessions_df["date"].min().date(), sessions_df["date"].max().date()
date_range = st.sidebar.date_input("Date range", value=(min_date, max_date),
                                    min_value=min_date, max_value=max_date)
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    d0, d1 = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1]) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    sessions_df = sessions_df[(sessions_df["date"] >= d0) & (sessions_df["date"] <= d1)]

# Club filter
club_filter = st.sidebar.multiselect("Filter by club", clubs, default=[])

# Quality filter
st.sidebar.markdown("---")
st.sidebar.subheader("Shot Quality")
quality_filter = st.sidebar.multiselect(
    "Show tiers",
    QUALITY_TIERS,
    default=QUALITY_TIERS,
    help=(
        "SQS (0–100): Carry 60% · Accuracy 40%. "
        "Carry expectation adjusted for your actual club speed that swing. "
        "Great ≥75 · Good ≥55 · Average ≥35 · Poor ≥20 · Miss <20"
    ),
)

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()


# ---------------------------------------------------------------------------
# Load shots, apply filters, score quality
# ---------------------------------------------------------------------------
all_shots = load_shots()
if not all_shots.empty:
    all_shots["date"] = pd.to_datetime(all_shots["date"], errors="coerce")
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        all_shots = all_shots[(all_shots["date"] >= d0) & (all_shots["date"] <= d1)]
    if club_filter:
        all_shots = all_shots[all_shots["club"].isin(club_filter)]
    all_shots = apply_exclusions(all_shots)
    all_shots = score_shot_quality(all_shots)

n_manual = int((all_shots["excluded"] == 1).sum()) if not all_shots.empty else 0

st.sidebar.caption(
    f"{len(sessions_df)} sessions · {len(all_shots):,} shots"
    + (f" · {n_manual} manually excluded" if n_manual else "")
)

# chart_shots = what every chart/average uses (manual exclusions + quality filter)
chart_shots = all_shots[~all_shots["_excluded"]]
if quality_filter and len(quality_filter) < len(QUALITY_TIERS) and not chart_shots.empty:
    chart_shots = chart_shots[chart_shots["_quality"].isin(quality_filter)]


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_overview, tab_trends, tab_session, tab_clubs, tab_dispersion = st.tabs(
    ["📋 Sessions", "📈 Trends", "🎯 Session Detail", "🏌️ Club Stats", "🗺️ Dispersion"]
)


# ============================================================
# TAB 1 – Sessions Overview
# ============================================================
with tab_overview:
    st.header("Session Overview")

    if not chart_shots.empty:
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Sessions", len(sessions_df))
        col2.metric("Shots (filtered)", f"{len(chart_shots):,}")
        avg_ball  = chart_shots["ball_speed"].mean()
        avg_carry = chart_shots["carry"].mean()
        avg_smash = chart_shots["smash_factor"].mean()
        col3.metric("Avg Ball Speed", f"{avg_ball:.1f} mph"  if not pd.isna(avg_ball)  else "–")
        col4.metric("Avg Carry",      f"{avg_carry:.1f} yds" if not pd.isna(avg_carry) else "–")
        col5.metric("Avg Smash",      f"{avg_smash:.2f}"     if not pd.isna(avg_smash) else "–")
        st.markdown("---")

    display_df = sessions_df.copy()
    display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
    display_df = display_df.rename(columns={
        "date": "Date", "title": "Session", "location": "Location", "shot_count": "Shots",
    })
    st.dataframe(display_df[["Date", "Session", "Location", "Shots"]],
                 use_container_width=True, hide_index=True)


# ============================================================
# TAB 2 – Trends Over Time
# ============================================================
with tab_trends:
    st.header("Metrics Over Time")

    if chart_shots.empty:
        st.info("No shot data available for the selected filters.")
    else:
        col_left, col_right = st.columns([1, 3])
        with col_left:
            metric = st.selectbox("Metric",
                [m for m in KEY_METRICS if m in chart_shots.columns],
                format_func=metric_col)
            group_by_club = st.checkbox("Break out by club", value=True)
            show_rolling  = st.checkbox("Show 3-session rolling avg", value=False)

        with col_right:
            if group_by_club:
                trend_df = (
                    chart_shots.dropna(subset=[metric])
                    .groupby(["date", "club"])[metric].mean()
                    .reset_index().sort_values("date")
                )
                fig = px.line(trend_df, x="date", y=metric, color="club", markers=True,
                              labels={"date": "Date", metric: metric_col(metric), "club": "Club"},
                              title=f"{metric_col(metric)} Over Time by Club")
            else:
                trend_df = (
                    chart_shots.dropna(subset=[metric])
                    .groupby("date")[metric].mean()
                    .reset_index().sort_values("date")
                )
                if show_rolling:
                    trend_df["rolling"] = trend_df[metric].rolling(3, min_periods=1).mean()
                    fig = go.Figure()
                    fig.add_scatter(x=trend_df["date"], y=trend_df[metric],
                                    mode="markers+lines", name="Session avg",
                                    line=dict(color="#adb5bd"))
                    fig.add_scatter(x=trend_df["date"], y=trend_df["rolling"],
                                    mode="lines", name="3-session avg",
                                    line=dict(color="#2d6a4f", width=3))
                    fig.update_layout(title=f"{metric_col(metric)} Over Time",
                                      xaxis_title="Date", yaxis_title=metric_col(metric))
                else:
                    fig = px.line(trend_df, x="date", y=metric, markers=True,
                                  labels={"date": "Date", metric: metric_col(metric)},
                                  title=f"{metric_col(metric)} Over Time")
            fig.update_layout(height=420, plot_bgcolor="white")
            st.plotly_chart(fig, use_container_width=True)

        st.subheader(f"Distribution — {metric_col(metric)}")
        hist_df = chart_shots.dropna(subset=[metric])
        if not hist_df.empty:
            fig2 = px.histogram(hist_df, x=metric,
                                color="club" if group_by_club else None,
                                nbins=30, marginal="box",
                                labels={metric: metric_col(metric)})
            fig2.update_layout(height=300, plot_bgcolor="white")
            st.plotly_chart(fig2, use_container_width=True)

        # ── Shot quality over time ────────────────────────────────────────────
        if "_quality" in chart_shots.columns and chart_shots["_quality"].notna().any():
            st.markdown("---")
            st.subheader("Shot Quality Over Time")
            st.caption(
                "**SQS (0–100):** Carry 60% + Accuracy 40%, "
                "carry expectation adjusted for your actual club speed that swing. "
                "Bonus +5 if both ≥70, +3 more if both ≥85. "
                "Penalty −8 for extreme offline (>3× tolerance) or way short (<65% expected). "
                "**Great** ≥75 · **Good** ≥55 · **Average** ≥35 · **Poor** ≥20 · **Miss** <20"
            )

            qual_shots = chart_shots[chart_shots["_quality"].notna()]
            qual_trend = (
                qual_shots
                .groupby(["date", "_quality"])
                .size()
                .reset_index(name="count")
            )
            totals = qual_trend.groupby("date")["count"].transform("sum")
            qual_trend["pct"] = (qual_trend["count"] / totals * 100).round(1)
            qual_trend["_quality"] = pd.Categorical(
                qual_trend["_quality"], categories=QUALITY_TIERS, ordered=True
            )
            # Use short string dates so bars are evenly spaced regardless of gaps
            qual_trend["session"] = qual_trend["date"].dt.strftime("%m/%d/%y")
            session_order = qual_trend.sort_values("date")["session"].unique().tolist()
            qual_trend = qual_trend.sort_values(["date", "_quality"])

            fig_q = px.bar(
                qual_trend, x="session", y="pct", color="_quality",
                color_discrete_map=QUALITY_COLORS,
                category_orders={"_quality": QUALITY_TIERS, "session": session_order},
                text="pct",
                labels={"session": "Session", "pct": "% of shots", "_quality": "Tier"},
                title="Shot Quality Distribution Per Session",
            )
            fig_q.update_traces(texttemplate="%{text:.0f}%", textposition="inside",
                                textfont_size=10)
            fig_q.update_layout(
                height=400, plot_bgcolor="white", barmode="stack",
                yaxis=dict(range=[0, 100], ticksuffix="%"),
            )
            st.plotly_chart(fig_q, use_container_width=True)

            # ── Avg SQS trend ─────────────────────────────────────────────
            if "_sqs" in chart_shots.columns and chart_shots["_sqs"].notna().any():
                sqs_group = st.radio(
                    "SQS trend grouping", ["Overall", "By club"],
                    horizontal=True, key="sqs_group_mode",
                )
                if sqs_group == "Overall":
                    sqs_trend = (
                        chart_shots.dropna(subset=["_sqs"])
                        .groupby("date")["_sqs"].mean().reset_index()
                        .sort_values("date")
                    )
                    sqs_trend["session"] = sqs_trend["date"].dt.strftime("%m/%d/%y")
                    fig_sqs = px.line(
                        sqs_trend, x="session", y="_sqs", markers=True,
                        labels={"session": "Session", "_sqs": "Avg SQS"},
                        title="Average SQS Per Session",
                    )
                else:
                    sqs_trend = (
                        chart_shots.dropna(subset=["_sqs"])
                        .groupby(["date", "club"])["_sqs"].mean().reset_index()
                        .sort_values("date")
                    )
                    sqs_trend["session"] = sqs_trend["date"].dt.strftime("%m/%d/%y")
                    fig_sqs = px.line(
                        sqs_trend, x="session", y="_sqs", color="club", markers=True,
                        labels={"session": "Session", "_sqs": "Avg SQS", "club": "Club"},
                        title="Average SQS Per Session by Club",
                    )
                fig_sqs.add_hline(y=75, line_dash="dot", line_color="#2d6a4f",
                                  annotation_text="Great", annotation_position="right",
                                  opacity=0.6)
                fig_sqs.add_hline(y=55, line_dash="dot", line_color="#52b788",
                                  annotation_text="Good", annotation_position="right",
                                  opacity=0.6)
                fig_sqs.update_layout(
                    height=360, plot_bgcolor="white",
                    yaxis=dict(range=[0, 100]),
                    xaxis_title="Session",
                )
                st.plotly_chart(fig_sqs, use_container_width=True)


# ============================================================
# TAB 3 – Session Detail
# ============================================================
with tab_session:
    st.header("Session Detail")

    if sessions_df.empty:
        st.info("No sessions available.")
    else:
        session_options = {
            f"{row['date'].strftime('%Y-%m-%d')} – {row['title']}": row["id"]
            for _, row in sessions_df.iterrows()
        }
        selected_label = st.selectbox("Select session", list(session_options.keys()))
        selected_id    = session_options[selected_label]

        session_shots_raw = load_shots(session_id=selected_id)
        if club_filter:
            session_shots_raw = session_shots_raw[session_shots_raw["club"].isin(club_filter)]
        session_shots = apply_exclusions(session_shots_raw)

        # Merge SQS/quality from all_shots (uses cross-session baselines)
        if not all_shots.empty and "_sqs" in all_shots.columns:
            sqs_lookup = all_shots.set_index("id")[["_sqs", "_quality"]]
            session_shots = session_shots.join(sqs_lookup, on="id")

        if session_shots.empty:
            st.info("No shot data for this session (may need to re-sync).")
        else:
            sess_clean = session_shots[~session_shots["_excluded"]]

            # ── Averages ────────────────────────────────────────────────────
            st.markdown("#### Session Averages")
            avail = [m for m in KEY_METRICS
                     if m in sess_clean.columns and sess_clean[m].notna().any()]

            # Show avg SQS first if available
            avg_sqs = sess_clean["_sqs"].mean() if "_sqs" in sess_clean.columns else None
            n_avail = len(avail[:10])
            n_cols  = min(5, n_avail + (1 if avg_sqs is not None and not pd.isna(avg_sqs) else 0))
            metric_cols = st.columns(n_cols)

            col_idx = 0
            if avg_sqs is not None and not pd.isna(avg_sqs):
                metric_cols[col_idx % 5].metric("Avg SQS", f"{avg_sqs:.1f}")
                col_idx += 1
            for m in avail[:10]:
                metric_cols[col_idx % 5].metric(metric_col(m), fmt_metric(sess_clean[m].mean(), m))
                col_idx += 1

            n_sess_excl = int(session_shots["_excluded"].sum())
            if n_sess_excl:
                st.caption(f"ⓘ {n_sess_excl} manually excluded shot(s) not in averages above.")

            st.markdown("---")

            # ── Scatter ──────────────────────────────────────────────────────
            avail_all = [m for m in METRIC_LABELS
                         if m in session_shots.columns and session_shots[m].notna().any()]
            col_l, col_r = st.columns(2)
            with col_l:
                x_metric = st.selectbox("X axis", avail_all,
                    index=avail_all.index("club_speed") if "club_speed" in avail_all else 0,
                    format_func=metric_col, key="x_metric")
            with col_r:
                y_metric = st.selectbox("Y axis", avail_all,
                    index=avail_all.index("carry") if "carry" in avail_all else 1,
                    format_func=metric_col, key="y_metric")

            scatter_df = sess_clean.dropna(subset=[x_metric, y_metric])
            if not scatter_df.empty:
                fig = px.scatter(scatter_df, x=x_metric, y=y_metric, color="club",
                    hover_data=["shot_number", "club"],
                    labels={x_metric: metric_col(x_metric), y_metric: metric_col(y_metric)},
                    title=f"{metric_col(x_metric)} vs {metric_col(y_metric)}")
                fig.update_layout(height=380, plot_bgcolor="white")
                st.plotly_chart(fig, use_container_width=True)

            st.markdown("---")

            # ── Shot log + manual exclusion editor ───────────────────────────
            st.subheader("Shot Log")
            st.caption("Check **Exclude** to permanently remove a shot from all charts and averages.")

            display_metrics = [m for m in KEY_METRICS
                                if m in session_shots.columns and session_shots[m].notna().any()]

            edit_df  = session_shots.reset_index(drop=True)
            shot_ids = edit_df["id"].tolist()

            editor_input = edit_df[["shot_number", "club"] + display_metrics].copy()
            editor_input.insert(2, "Exclude", edit_df["_excluded"].astype(bool))

            # Add SQS and Tier columns if available
            extra_disabled = []
            if "_sqs" in edit_df.columns:
                editor_input.insert(3, "SQS",  edit_df["_sqs"].round(1))
                editor_input.insert(4, "Tier", edit_df["_quality"].fillna("–"))
                extra_disabled = ["SQS", "Tier"]

            rename_map = {"shot_number": "#", "club": "Club"}
            rename_map.update({m: metric_col(m) for m in display_metrics})
            editor_display = editor_input.rename(columns=rename_map)

            edited = st.data_editor(
                editor_display,
                column_config={
                    "Exclude": st.column_config.CheckboxColumn("Exclude", width="small"),
                    "#":       st.column_config.NumberColumn("#", width="small"),
                    "SQS":     st.column_config.NumberColumn("SQS", width="small", format="%.1f"),
                    "Tier":    st.column_config.TextColumn("Tier", width="small"),
                },
                disabled=["#", "Club"] + extra_disabled + [metric_col(m) for m in display_metrics],
                hide_index=True,
                use_container_width=True,
                key=f"shot_editor_{selected_id}",
            )

            if st.button("💾 Save exclusions", key="save_btn"):
                orig_vals = editor_display["Exclude"].values
                new_vals  = edited["Exclude"].values
                changed = [(i, bool(new_vals[i]))
                           for i in range(len(orig_vals)) if orig_vals[i] != new_vals[i]]

                if changed:
                    for i, new_val in changed:
                        db.update_shot_excluded(shot_ids[i], 1 if new_val else None)
                    editor_key = f"shot_editor_{selected_id}"
                    if editor_key in st.session_state:
                        del st.session_state[editor_key]
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.info("No changes to save.")


# ============================================================
# TAB 4 – Club Stats
# ============================================================
with tab_clubs:
    st.header("Club Statistics")

    if chart_shots.empty or not clubs:
        st.info("No club data available.")
    else:
        avail_metrics = [m for m in METRIC_LABELS
                         if m in chart_shots.columns and chart_shots[m].notna().any()]
        col_l, col_r = st.columns([1, 3])
        with col_l:
            club_metric = st.selectbox("Metric to compare", avail_metrics,
                index=avail_metrics.index("carry") if "carry" in avail_metrics else 0,
                format_func=metric_col, key="club_metric")
            show_all_clubs = st.checkbox("Show all clubs", value=True)

        with col_r:
            club_agg = (
                chart_shots.dropna(subset=[club_metric])
                .groupby("club")[club_metric]
                .agg(["mean", "std", "count"])
                .reset_index()
                .rename(columns={"mean": "Average", "std": "Std Dev", "count": "Shots"})
                .sort_values("Average", ascending=False)
            )
            if not show_all_clubs:
                top = club_agg.nlargest(8, "Shots")["club"].tolist()
                club_agg = club_agg[club_agg["club"].isin(top)]

            fig = px.bar(club_agg, x="club", y="Average", error_y="Std Dev",
                         text="Average",
                         labels={"club": "Club", "Average": metric_col(club_metric)},
                         title=f"Average {metric_col(club_metric)} by Club",
                         color="Average", color_continuous_scale="teal")
            fig.update_traces(texttemplate="%{text:.1f}", textposition="outside")
            fig.update_layout(height=430, plot_bgcolor="white", showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Club Averages Table")
        full_agg = (
            chart_shots.dropna(how="all", subset=avail_metrics)
            .groupby("club")[avail_metrics].mean().round(1).reset_index()
        )
        full_agg.columns = ["Club"] + [metric_col(m) for m in avail_metrics]
        st.dataframe(full_agg.set_index("Club"), use_container_width=True)

        radar_metrics = ["ball_speed", "club_speed", "smash_factor",
                          "carry", "launch_angle", "total_spin"]
        radar_avail = [m for m in radar_metrics
                       if m in chart_shots.columns and chart_shots[m].notna().any()]
        if len(radar_avail) >= 3:
            st.subheader("Club Profile (Radar)")
            top_clubs_df = (
                chart_shots[chart_shots["club"] != ""]
                .groupby("club")["club"].count().nlargest(6)
            )
            radar_df = (
                chart_shots[chart_shots["club"].isin(top_clubs_df.index)]
                .groupby("club")[radar_avail].mean()
            )
            normed = (radar_df - radar_df.min()) / (radar_df.max() - radar_df.min() + 1e-9)
            fig_r = go.Figure()
            for club in normed.index:
                vals = normed.loc[club].tolist() + [normed.loc[club].tolist()[0]]
                cats = [metric_col(m) for m in radar_avail] + [metric_col(radar_avail[0])]
                fig_r.add_trace(go.Scatterpolar(r=vals, theta=cats, fill="toself", name=club))
            fig_r.update_layout(polar=dict(radialaxis=dict(visible=False)),
                                 height=450, title="Club Profiles (normalised)")
            st.plotly_chart(fig_r, use_container_width=True)


# ============================================================
# TAB 5 – Dispersion
# ============================================================
with tab_dispersion:
    st.header("Shot Dispersion")

    if chart_shots.empty:
        st.info("No shot data available for the selected filters.")
    else:
        disp_clubs_avail = sorted(chart_shots["club"].dropna().unique().tolist())
        col_l, col_r = st.columns([1, 3])

        with col_l:
            sel_clubs = st.multiselect(
                "Clubs to display",
                disp_clubs_avail,
                default=disp_clubs_avail[:min(4, len(disp_clubs_avail))],
                key="disp_clubs",
            )
            view_mode = st.radio("View", ["Top-down", "Side view"], key="disp_view")
            max_shots = st.slider("Max shots per club", 10, 200, 50, 10, key="disp_max",
                                  help="Limit tracers for readability.")
            if view_mode == "Top-down":
                dots_only    = st.checkbox("Dots only (no tracers)", value=False, key="disp_dots")
                show_circles = st.checkbox("Dispersion circles (±1σ)", value=False, key="disp_circles")
            else:
                dots_only    = False
                show_circles = False

        with col_r:
            if not sel_clubs:
                st.info("Select at least one club.")
            else:
                all_traj = load_trajectories()
                valid_ids = set(chart_shots[chart_shots["club"].isin(sel_clubs)]["id"].tolist())
                traj_data = [t for t in all_traj if t["id"] in valid_ids]

                palette = px.colors.qualitative.Plotly
                club_color = {c: palette[i % len(palette)] for i, c in enumerate(sorted(sel_clubs))}

                fig_disp = go.Figure()
                has_any_traj = False
                landing_pts: dict[str, list] = {c: [] for c in sel_clubs}

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

                # Dispersion circles: ±1σ ellipse around each club's landing centroid
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
                        fig_disp.add_trace(go.Scatter(
                            x=c_lat   + r_lat   * np.cos(theta),
                            y=c_carry + r_carry * np.sin(theta),
                            mode="lines",
                            name=f"{club} ±1σ",
                            line=dict(color=club_color[club], width=2, dash="dash"),
                            opacity=0.9,
                        ))
                        fig_disp.add_trace(go.Scatter(
                            x=[c_lat], y=[c_carry],
                            mode="markers",
                            name=f"{club} center",
                            marker=dict(color=club_color[club], size=9, symbol="cross-thin",
                                        line=dict(width=2, color=club_color[club])),
                            showlegend=False,
                        ))

                if not has_any_traj:
                    st.warning("No trajectory data found. Make sure shots were synced with raw_json.")
                else:
                    if view_mode == "Top-down":
                        # Fix axes to max values across ALL shots (ignore quality filter)
                        max_off = all_shots["offline"].abs().max() if not all_shots.empty else 50
                        if pd.isna(max_off) or max_off == 0:
                            max_off = 50
                        x_pad = max(max_off * 1.05, 5)  # 5% padding, minimum ±5 yds

                        max_carry = all_shots["carry"].max() if not all_shots.empty else 300
                        if pd.isna(max_carry) or max_carry == 0:
                            max_carry = 300
                        y_pad = max_carry * 1.05

                        fig_disp.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.4)
                        fig_disp.update_layout(
                            title="Shot Dispersion — Top-down View",
                            xaxis_title="← Left  ·  Offline (yds)  ·  Right →",
                            yaxis_title="Carry Distance (yds)",
                            xaxis=dict(range=[-x_pad, x_pad]),
                            yaxis=dict(range=[0, y_pad]),
                            height=560,
                            plot_bgcolor="white",
                        )
                    else:
                        fig_disp.update_layout(
                            title="Ball Flight Profile — Side View",
                            xaxis_title="Carry Distance (yds)",
                            yaxis_title="Height (yds)",
                            height=400,
                            plot_bgcolor="white",
                        )
                    st.plotly_chart(fig_disp, use_container_width=True)

        # ── Impact location ──────────────────────────────────────────────────
        if sel_clubs:
            impact_df = chart_shots[
                chart_shots["club"].isin(sel_clubs) &
                chart_shots["impact_offset"].notna() &
                chart_shots["impact_height"].notna()
            ].copy()

            st.markdown("---")
            st.subheader("Clubface Impact Location")

            if impact_df.empty:
                st.caption(
                    "No impact location data yet. "
                    "Run `python sync.py --all` to populate it."
                )
            else:
                imp_col_l, imp_col_r = st.columns([1, 3])

                with imp_col_l:
                    impact_view = st.radio(
                        "Display mode", ["Scatter", "Density"], key="impact_view",
                        help="Scatter = individual shots · Density = concentration contours per club",
                    )
                    if impact_view == "Scatter":
                        color_by = st.selectbox(
                            "Color by",
                            ["smash_factor", "carry", "club"],
                            format_func=lambda x: {
                                "smash_factor": "Smash Factor",
                                "carry":        "Carry (yds)",
                                "club":         "Club",
                            }[x],
                            key="impact_color",
                        )
                    else:
                        color_by = "club"

                with imp_col_r:
                    if impact_view == "Scatter":
                        if color_by == "club":
                            fig_imp = px.scatter(
                                impact_df,
                                x="impact_offset", y="impact_height",
                                color="club",
                                hover_data=["shot_number", "carry", "smash_factor"],
                                labels={"impact_offset": "Horizontal (cm)", "impact_height": "Vertical (cm)"},
                                title="Impact Location on Clubface",
                            )
                        else:
                            fig_imp = px.scatter(
                                impact_df,
                                x="impact_offset", y="impact_height",
                                color=color_by,
                                color_continuous_scale="RdYlGn",
                                hover_data=["club", "shot_number", "carry", "smash_factor"],
                                labels={
                                    "impact_offset": "Horizontal (cm)",
                                    "impact_height": "Vertical (cm)",
                                    color_by: metric_col(color_by),
                                },
                                title="Impact Location on Clubface",
                            )
                    else:  # Density contours, one per club
                        fig_imp = go.Figure()
                        for i, club in enumerate(sorted(sel_clubs)):
                            cd = impact_df[impact_df["club"] == club]
                            if len(cd) < 4:
                                continue
                            c = club_color.get(club, palette[i % len(palette)])
                            fig_imp.add_trace(go.Histogram2dContour(
                                x=cd["impact_offset"], y=cd["impact_height"],
                                name=club,
                                colorscale=[[0, "rgba(255,255,255,0.01)"], [1, c]],
                                showscale=False,
                                ncontours=6,
                                line_width=1.5,
                            ))
                        fig_imp.update_layout(title="Impact Density by Club")

                    # Clubface outline + crosshairs (shared for both modes)
                    fig_imp.add_shape(
                        type="rect", x0=-2.5, y0=-2.0, x1=2.5, y1=2.0,
                        line=dict(color="gray", dash="dot", width=1),
                        fillcolor="rgba(180,180,180,0.06)",
                    )
                    fig_imp.add_hline(y=0, line_dash="dot", line_color="lightgray", line_width=0.8)
                    fig_imp.add_vline(x=0, line_dash="dot", line_color="lightgray", line_width=0.8)
                    fig_imp.update_layout(
                        height=430, plot_bgcolor="white",
                        xaxis_title="← Heel  ·  Horizontal (cm)  ·  Toe →",
                        yaxis_title="Vertical (cm)",
                    )
                    st.plotly_chart(fig_imp, use_container_width=True)

                # ── Impact trend over time ─────────────────────────────────────
                st.markdown("#### Impact Trend Over Time")

                trend_group = st.radio(
                    "Group by", ["By club", "All clubs combined"],
                    horizontal=True, key="trend_group",
                    help="'All combined' averages across every selected club per session.",
                )

                if trend_group == "By club":
                    trend_impact = (
                        impact_df
                        .groupby(["date", "club"])[["impact_offset", "impact_height"]]
                        .mean().round(2).reset_index().sort_values("date")
                    )
                    color_col = "club"
                else:
                    trend_impact = (
                        impact_df
                        .groupby("date")[["impact_offset", "impact_height"]]
                        .mean().round(2).reset_index().sort_values("date")
                    )
                    color_col = None

                t_col1, t_col2 = st.columns(2)
                with t_col1:
                    fig_off = px.line(
                        trend_impact, x="date", y="impact_offset",
                        color=color_col, markers=True,
                        labels={"date": "Date", "impact_offset": "Avg Offset (cm)", "club": "Club"},
                        title="Horizontal Impact  ← Heel (−)  |  Toe (+) →",
                    )
                    fig_off.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5,
                                      annotation_text="Center", annotation_position="right")
                    fig_off.update_layout(height=300, plot_bgcolor="white")
                    st.plotly_chart(fig_off, use_container_width=True)

                with t_col2:
                    fig_hgt = px.line(
                        trend_impact, x="date", y="impact_height",
                        color=color_col, markers=True,
                        labels={"date": "Date", "impact_height": "Avg Height (cm)", "club": "Club"},
                        title="Vertical Impact  Low (−)  |  High (+)",
                    )
                    fig_hgt.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5,
                                      annotation_text="Center", annotation_position="right")
                    fig_hgt.update_layout(height=300, plot_bgcolor="white")
                    st.plotly_chart(fig_hgt, use_container_width=True)
