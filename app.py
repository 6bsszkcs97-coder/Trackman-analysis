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
               "launch_angle", "total_spin", "attack_angle", "club_path", "face_angle",
               "face_to_path", "impact_offset", "impact_height"]


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
    return sort_clubs(db.get_clubs())

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


QUALITY_TIERS  = ["Tour Quality", "Solid", "Playable", "Scramble", "Mishit"]
QUALITY_COLORS = {
    "Tour Quality": "#2d6a4f",
    "Solid":        "#52b788",
    "Playable":     "#f4a261",
    "Scramble":     "#e63946",
    "Mishit":       "#6b0504",
}

# Canonical club order — longest to shortest (includes clubs not yet in DB for future-proofing)
CLUB_ORDER = [
    "Driver",
    "2Wood", "3Wood", "4Wood", "5Wood", "7Wood",
    "DrivingIron", "2Iron",
    "3Hybrid", "3Iron",
    "4Hybrid", "4Iron",
    "5Hybrid", "5Iron",
    "6Hybrid", "6Iron",
    "7Hybrid", "7Iron",
    "8Iron", "9Iron",
    "PitchingWedge",
    "GapWedge", "50Wedge", "52Wedge",
    "SandWedge", "54Wedge", "56Wedge",
    "LobWedge", "58Wedge", "60Wedge", "64Wedge",
]
_CLUB_RANK = {c: i for i, c in enumerate(CLUB_ORDER)}


def sort_clubs(clubs) -> list:
    """Sort a collection of club name strings by canonical longest-to-shortest order.
    Unrecognised clubs are appended alphabetically at the end."""
    known   = [c for c in clubs if c in _CLUB_RANK]
    unknown = sorted(c for c in clubs if c not in _CLUB_RANK)
    return sorted(known, key=lambda c: _CLUB_RANK[c]) + unknown


# PGA Tour carry benchmarks (yards) — fixed reference, not golfer-specific
TOUR_CARRY = {
    "Driver":         275, "3Wood": 243,  "3-Wood": 243,
    "3Hybrid":        225, "3-Hybrid": 225,
    "4Hybrid":        215, "4-Hybrid": 215,
    "4Iron":          210, "4-Iron": 210,
    "5Iron":          195, "5-Iron": 195,
    "6Iron":          183, "6-Iron": 183,
    "7Iron":          172, "7-Iron": 172,
    "8Iron":          160, "8-Iron": 160,
    "9Iron":          148, "9-Iron": 148,
    "PitchingWedge":  136, "PW": 136,
    "50Wedge":        120, "50° Wedge": 120,
    "54Wedge":        103, "54° Wedge": 103,
    "58Wedge":         86, "58° Wedge": 86,
    "SandWedge":      115, "Sand Wedge": 115,
}

# PGA Tour average dispersion benchmarks (yards)
TOUR_DISP = {
    "Driver":         18, "3Wood": 14,  "3-Wood": 14,
    "3Hybrid":        12, "3-Hybrid": 12,
    "4Hybrid":        11, "4-Hybrid": 11,
    "4Iron":          10, "4-Iron": 10,
    "5Iron":           9, "5-Iron": 9,
    "6Iron":           8, "6-Iron": 8,
    "7Iron":           7, "7-Iron": 7,
    "8Iron":           7, "8-Iron": 7,
    "9Iron":           6, "9-Iron": 6,
    "PitchingWedge":   6, "PW": 6,
    "50Wedge":         5, "50° Wedge": 5,
    "54Wedge":         5, "54° Wedge": 5,
    "58Wedge":         5, "58° Wedge": 5,
    "SandWedge":       5, "Sand Wedge": 5,
}


def _carry_score_vec(carry: np.ndarray, tour_carry: float) -> np.ndarray:
    """Vectorised carry score using a power curve vs PGA Tour benchmark."""
    pct   = carry / tour_carry
    score = np.where(
        pct >= 1.0, 100.0,
        np.where(
            pct <= 0.50, 0.0,
            # np.maximum guards against negative base when pct < 0.5 in unevaluated branch
            np.minimum(100.0, 100.0 * (np.maximum(0.0, pct - 0.50) / 0.50) ** 1.4),
        ),
    )
    # Missing carry → 0
    return np.where(np.isnan(carry), 0.0, score)


def _accuracy_score_vec(offline: np.ndarray, tour_disp: float) -> np.ndarray:
    """Vectorised accuracy score using club-specific PGA Tour dispersion zones."""
    x       = np.abs(offline)
    tight   = tour_disp * 0.4
    wide    = tour_disp * 2.5
    extreme = tour_disp * 4.0

    score = np.where(
        x <= tight,
        100.0,
        np.where(
            x <= tour_disp,
            100.0 - ((x - tight) / (tour_disp - tight)) * 15.0,
            np.where(
                x <= wide,
                85.0 - ((x - tour_disp) / (wide - tour_disp)) * 55.0,
                np.where(
                    x <= extreme,
                    30.0 - ((x - wide) / (extreme - wide)) * 30.0,
                    0.0,
                ),
            ),
        ),
    )
    # Missing offline → 50
    return np.where(np.isnan(offline), 50.0, score)


def score_shot_quality(df: pd.DataFrame) -> pd.DataFrame:
    """Score each shot 0–100 using fixed PGA Tour benchmarks.

    SQS = 0.60 × CarryScore + 0.40 × AccuracyScore
    Adds columns: _sqs, _carry_score, _acc_score, _quality
    """
    df = df.copy()
    df["_sqs"]         = np.nan
    df["_carry_score"] = np.nan
    df["_acc_score"]   = np.nan
    df["_quality"]     = "Playable"

    for club in df["club"].dropna().unique():
        tour_c = TOUR_CARRY.get(club)
        tour_d = TOUR_DISP.get(club)
        if tour_c is None or tour_d is None:
            continue

        idx   = df.index[df["club"] == club]
        carry = df.loc[idx, "carry"].values.astype(float)
        off   = df.loc[idx, "offline"].values.astype(float)

        cs  = _carry_score_vec(carry, tour_c)
        acc = _accuracy_score_vec(off, tour_d)
        sqs = np.clip(0.60 * cs + 0.40 * acc, 0.0, 100.0)
        # Cap 1: carry ≤ 50% of tour → Mishit ceiling (24)
        # A ball that barely moves is always a Mishit regardless of accuracy
        sqs = np.where(cs == 0.0, np.minimum(sqs, 24.0), sqs)
        # Cap 2: offline > 4× tour dispersion → Scramble ceiling (44)
        # A severely offline shot is never Playable regardless of carry
        sqs = np.where(acc == 0.0, np.minimum(sqs, 44.0), sqs)

        q = pd.Series("Playable", index=idx)
        q[sqs >= 87]                   = "Tour Quality"
        q[(sqs >= 70) & (sqs < 87)]   = "Solid"
        q[(sqs >= 50) & (sqs < 70)]   = "Playable"
        q[(sqs >= 25) & (sqs < 50)]   = "Scramble"
        q[sqs < 25]                    = "Mishit"

        df.loc[idx, "_carry_score"] = cs
        df.loc[idx, "_acc_score"]   = acc
        df.loc[idx, "_sqs"]         = sqs
        df.loc[idx, "_quality"]     = q.values

    return df


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


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert a 6-digit hex colour string (e.g. '#636EFA') to an rgba() CSS string."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"_hex_to_rgba expects a 6-digit hex string, got: {hex_color!r}")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


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
        "SQS = 60% Carry + 40% Accuracy vs PGA Tour benchmarks. "
        "Tour Quality ≥87 · Solid ≥70 · Playable ≥50 · Scramble ≥25 · Mishit <25"
    ),
)

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()

# ── Export all shots to CSV ───────────────────────────────────────────────────
@st.cache_data(ttl=60)
def build_export_csv() -> bytes:
    """Build a CSV of every shot from every session with all metrics + SQS."""
    export_df = load_shots()
    if export_df.empty:
        return b""
    export_df = apply_exclusions(export_df)
    export_df = score_shot_quality(export_df)

    # Friendly column ordering
    meta_cols  = ["date", "title", "shot_number", "club", "excluded"]
    score_cols = ["_sqs", "_quality"]
    metric_cols_list = list(METRIC_LABELS.keys())
    keep = [c for c in meta_cols + score_cols + metric_cols_list if c in export_df.columns]
    out = export_df[keep].copy()

    # Rename to human-readable headers
    rename = {
        "date":         "Date",
        "title":        "Session",
        "shot_number":  "Shot #",
        "club":         "Club",
        "excluded":     "Excluded",
        "_sqs":         "SQS",
        "_quality":     "Quality Tier",
    }
    rename.update({m: metric_col(m) for m in metric_cols_list})
    out = out.rename(columns=rename)
    out["Date"] = pd.to_datetime(out["Date"]).dt.strftime("%Y-%m-%d")
    out = out.sort_values(["Date", "Shot #"])
    return out.to_csv(index=False).encode("utf-8")

st.sidebar.download_button(
    label="⬇️ Export all shots (CSV)",
    data=build_export_csv(),
    file_name="trackman_shots.csv",
    mime="text/csv",
)


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

n_days = sessions_df["date"].dt.normalize().nunique() if not sessions_df.empty else 0
n_sess = len(sessions_df)
session_label = f"{n_days} day{'s' if n_days != 1 else ''}" + (f" ({n_sess} sessions)" if n_sess > n_days else "")
st.sidebar.caption(
    f"{session_label} · {len(all_shots):,} shots"
    + (f" · {n_manual} manually excluded" if n_manual else "")
)

# chart_shots = what every chart/average uses (manual exclusions + quality filter)
chart_shots = all_shots[~all_shots["_excluded"]]
if quality_filter and len(quality_filter) < len(QUALITY_TIERS) and not chart_shots.empty:
    chart_shots = chart_shots[chart_shots["_quality"].isin(quality_filter)]


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_overview, tab_trends, tab_session, tab_clubs, tab_dispersion, tab_quality = st.tabs(
    ["📋 Sessions", "📈 Trends", "🎯 Session Detail", "🏌️ Club Stats", "🗺️ Dispersion", "🔬 Quality Analysis"]
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
    display_df["_date_str"] = display_df["date"].dt.strftime("%Y-%m-%d")
    # Combine multiple sessions on the same day into one row
    overview = (
        display_df.groupby("_date_str", sort=False)
        .agg(
            _n        = ("id",         "count"),
            Location  = ("location",   "first"),
            Shots     = ("shot_count", "sum"),
        )
        .reset_index()
        .rename(columns={"_date_str": "Date"})
        .sort_values("Date", ascending=False)
    )
    overview["Sessions"] = overview["_n"].apply(
        lambda n: f"{n} combined" if n > 1 else "1"
    )
    # Join avg SQS per date from chart_shots
    if not chart_shots.empty and "_sqs" in chart_shots.columns:
        _sqs_by_date = (
            chart_shots.dropna(subset=["_sqs"]).copy()
        )
        _sqs_by_date["_date_str"] = _sqs_by_date["date"].dt.strftime("%Y-%m-%d")
        _sqs_by_date = (
            _sqs_by_date.groupby("_date_str")["_sqs"].mean().round(1).rename("Avg SQS")
        )
        overview = overview.join(_sqs_by_date, on="Date")
        _overview_cols = ["Date", "Sessions", "Location", "Shots", "Avg SQS"]
    else:
        _overview_cols = ["Date", "Sessions", "Location", "Shots"]
    st.dataframe(
        overview[_overview_cols],
        use_container_width=True, hide_index=True,
    )

    # ── Personal Records ──────────────────────────────────────────────────
    if not chart_shots.empty:
        st.markdown("---")
        st.subheader("Personal Records")

        pr_l, pr_r = st.columns(2)

        with pr_l:
            st.markdown("**All-time bests**")
            _pr_metrics = [
                ("_sqs",         "Best SQS",           "{:.1f}"),
                ("ball_speed",   "Best Ball Speed",     "{:.1f} mph"),
                ("club_speed",   "Best Club Speed",     "{:.1f} mph"),
                ("smash_factor", "Best Smash Factor",   "{:.3f}"),
                ("carry",        "Longest Carry",       "{:.1f} yds"),
                ("total",        "Longest Total Dist",  "{:.1f} yds"),
            ]
            _pr_cols = st.columns(len(_pr_metrics))
            for _i, (_m, _label, _fmt) in enumerate(_pr_metrics):
                if _m in chart_shots.columns and chart_shots[_m].notna().any():
                    _best = chart_shots[_m].max()
                    _pr_cols[_i].metric(_label, _fmt.format(_best))

        with pr_r:
            st.markdown("**Best carry by club**")
            if "carry" in chart_shots.columns:
                _best_carry = (
                    chart_shots.dropna(subset=["carry"])
                    .groupby("club")["carry"]
                    .max().reset_index()
                    .rename(columns={"carry": "Best Carry (yds)"})
                    .sort_values("Best Carry (yds)", ascending=False)
                    .reset_index(drop=True)
                )
                st.dataframe(_best_carry, hide_index=True, use_container_width=True)


# ============================================================
# TAB 2 – Trends Over Time
# ============================================================
with tab_trends:
    st.header("Metrics Over Time")

    if chart_shots.empty:
        st.info("No shot data available for the selected filters.")
    else:
        # Normalize date to date-only so same-day sessions merge into one point
        ts = chart_shots.copy()
        ts["date"] = ts["date"].dt.normalize()

        col_left, col_right = st.columns([1, 3])
        with col_left:
            metric = st.selectbox("Metric",
                [m for m in KEY_METRICS if m in ts.columns],
                format_func=metric_col)
            group_by_club = st.checkbox("Break out by club", value=True)
            show_rolling  = st.checkbox("Show rolling avg", value=False)
            rolling_window = 3
            if show_rolling and not group_by_club:
                rolling_window = st.slider(
                    "Window (sessions)", min_value=2, max_value=8, value=3,
                    key="rolling_window",
                )

        with col_right:
            if group_by_club:
                trend_df = (
                    ts.dropna(subset=[metric])
                    .groupby(["date", "club"])[metric].mean()
                    .reset_index().sort_values("date")
                )
                fig = px.line(trend_df, x="date", y=metric, color="club", markers=True,
                              labels={"date": "Date", metric: metric_col(metric), "club": "Club"},
                              title=f"{metric_col(metric)} Over Time by Club")
            else:
                trend_df = (
                    ts.dropna(subset=[metric])
                    .groupby("date")[metric].mean()
                    .reset_index().sort_values("date")
                )
                if show_rolling:
                    trend_df["rolling"] = trend_df[metric].rolling(rolling_window, min_periods=1).mean()
                    fig = go.Figure()
                    fig.add_scatter(x=trend_df["date"], y=trend_df[metric],
                                    mode="markers+lines", name="Session avg",
                                    line=dict(color="#adb5bd"))
                    fig.add_scatter(x=trend_df["date"], y=trend_df["rolling"],
                                    mode="lines", name=f"{rolling_window}-session avg",
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
        hist_df = ts.dropna(subset=[metric])
        if not hist_df.empty:
            fig2 = px.histogram(hist_df, x=metric,
                                color="club" if group_by_club else None,
                                nbins=30, marginal="box",
                                labels={metric: metric_col(metric)})
            fig2.update_layout(height=300, plot_bgcolor="white")
            st.plotly_chart(fig2, use_container_width=True)

        # ── Shot quality over time ────────────────────────────────────────────
        if "_quality" in ts.columns and ts["_quality"].notna().any():
            st.markdown("---")
            st.subheader("Shot Quality Over Time")
            st.caption(
                "**SQS (0–100):** 60% Carry + 40% Accuracy vs PGA Tour benchmarks. "
                "A score of 87 means the shot was Tour Quality. "
                "**Tour Quality** ≥87 · **Solid** ≥70 · **Playable** ≥50 · **Scramble** ≥25 · **Mishit** <25"
            )

            qual_shots = ts[ts["_quality"].notna()]

            # ── Normalize toggle — shared by both quality charts ───────────────
            normalize_mix = st.checkbox(
                "Normalize by club mix",
                value=False,
                key="sqs_normalize",
                help=(
                    "Gives each club equal weight per session regardless of shot count. "
                    "Removes bias from hitting mostly your best (or worst) clubs in a session — "
                    "so a session of all wedges doesn't look artificially better than one of all drivers."
                ),
            )

            # ── Shot quality distribution (stacked bar) ───────────────────────
            if normalize_mix and "club" in qual_shots.columns:
                # Per-club: compute tier % per session, then average across clubs (equal club weight)
                club_tier = (
                    qual_shots
                    .groupby(["date", "club", "_quality"])
                    .size()
                    .reset_index(name="count")
                )
                club_totals = club_tier.groupby(["date", "club"])["count"].transform("sum")
                club_tier["club_pct"] = club_tier["count"] / club_totals * 100
                qual_trend = (
                    club_tier
                    .groupby(["date", "_quality"])["club_pct"]
                    .mean()
                    .reset_index()
                    .rename(columns={"club_pct": "pct"})
                )
                qual_trend["pct"] = qual_trend["pct"].round(1)
                bar_title = "Shot Quality Distribution Per Session (club-normalized)"
            else:
                qual_trend = (
                    qual_shots
                    .groupby(["date", "_quality"])
                    .size()
                    .reset_index(name="count")
                )
                totals = qual_trend.groupby("date")["count"].transform("sum")
                qual_trend["pct"] = (qual_trend["count"] / totals * 100).round(1)
                bar_title = "Shot Quality Distribution Per Session"

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
                title=bar_title,
            )
            fig_q.update_traces(texttemplate="%{text:.0f}%", textposition="inside",
                                textfont_size=10)
            fig_q.update_layout(
                height=400, plot_bgcolor="white", barmode="stack",
                yaxis=dict(range=[0, 100], ticksuffix="%"),
            )
            st.plotly_chart(fig_q, use_container_width=True)

            # ── Avg SQS trend ─────────────────────────────────────────────
            if "_sqs" in ts.columns and ts["_sqs"].notna().any():
                sqs_group = st.radio(
                    "SQS trend grouping", ["Overall", "By club"],
                    horizontal=True, key="sqs_group_mode",
                )
                if sqs_group == "Overall":
                    sqs_raw = ts.dropna(subset=["_sqs"])
                    if normalize_mix:
                        # Step 1: avg SQS per club per session → Step 2: avg of those (equal club weight)
                        sqs_trend = (
                            sqs_raw
                            .groupby(["date", "club"])["_sqs"].mean()
                            .groupby("date").mean()
                            .reset_index()
                            .sort_values("date")
                        )
                        sqs_title = "Average SQS Per Session (club-normalized)"
                    else:
                        sqs_trend = (
                            sqs_raw.groupby("date")["_sqs"].mean()
                            .reset_index().sort_values("date")
                        )
                        sqs_title = "Average SQS Per Session"
                    sqs_trend["session"] = sqs_trend["date"].dt.strftime("%m/%d/%y")
                    fig_sqs = go.Figure()
                    # Shaded area fill under the line
                    fig_sqs.add_trace(go.Scatter(
                        x=sqs_trend["session"], y=sqs_trend["_sqs"],
                        mode="lines+markers",
                        line=dict(color="#2d6a4f", width=2.5),
                        marker=dict(size=8, color="#2d6a4f"),
                        fill="tozeroy",
                        fillcolor="rgba(82,183,136,0.15)",
                        name="Avg SQS",
                    ))
                    fig_sqs.update_layout(title=sqs_title)
                else:
                    sqs_trend = (
                        ts.dropna(subset=["_sqs"])
                        .groupby(["date", "club"])["_sqs"].mean().reset_index()
                        .sort_values("date")
                    )
                    sqs_trend["session"] = sqs_trend["date"].dt.strftime("%m/%d/%y")
                    _sqs_club_order = sqs_trend["session"].unique().tolist()
                    fig_sqs = px.line(
                        sqs_trend, x="session", y="_sqs", color="club", markers=True,
                        labels={"session": "Session", "_sqs": "Avg SQS", "club": "Club"},
                        title="Average SQS Per Session by Club",
                        category_orders={"session": _sqs_club_order},
                    )
                # Coloured tier bands (bottom to top)
                tier_bands = [
                    (0,  25, "rgba(107,5,4,0.08)"),     # Mishit
                    (25, 50, "rgba(230,57,70,0.08)"),    # Scramble
                    (50, 70, "rgba(244,162,97,0.10)"),   # Playable
                    (70, 87, "rgba(82,183,136,0.10)"),   # Solid
                    (87, 100, "rgba(45,106,79,0.12)"),   # Tour Quality
                ]
                for y0, y1, col in tier_bands:
                    fig_sqs.add_hrect(
                        y0=y0, y1=y1, fillcolor=col, line_width=0,
                    )
                fig_sqs.add_hline(y=87, line_dash="dot", line_color="#2d6a4f",
                                  annotation_text="Tour Quality", annotation_position="right",
                                  opacity=0.6)
                fig_sqs.add_hline(y=70, line_dash="dot", line_color="#52b788",
                                  annotation_text="Solid", annotation_position="right",
                                  opacity=0.6)
                fig_sqs.add_hline(y=50, line_dash="dot", line_color="#f4a261",
                                  annotation_text="Playable", annotation_position="right",
                                  opacity=0.5)
                fig_sqs.update_layout(
                    height=480, plot_bgcolor="white",
                    yaxis=dict(range=[0, 100], title="Avg SQS"),
                    xaxis_title="Session",
                    showlegend=(sqs_group != "Overall"),
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
        session_labels = list(session_options.keys())

        select_all = st.checkbox("All sessions", value=False, key="detail_all_sessions")
        if select_all:
            selected_labels = session_labels
        else:
            selected_labels = st.multiselect(
                "Select session(s)", session_labels,
                default=[session_labels[0]],
                key="detail_session_multi",
            )
            if not selected_labels:
                selected_labels = [session_labels[0]]

        selected_ids = [session_options[l] for l in selected_labels]
        multi_session = len(selected_ids) > 1

        frames = [load_shots(session_id=sid) for sid in selected_ids]
        session_shots_raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if not session_shots_raw.empty:
            session_shots_raw["date"] = pd.to_datetime(session_shots_raw["date"], errors="coerce")
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

            # ── Previous-session baseline for delta ──────────────────────────
            _prev_means: dict = {}
            if not multi_session and not session_shots.empty:
                _sel_date = session_shots["date"].min()
                _prev_sess = sessions_df[sessions_df["date"] < _sel_date].sort_values(
                    "date", ascending=False
                )
                if not _prev_sess.empty:
                    _prev_raw = load_shots(session_id=_prev_sess.iloc[0]["id"])
                    if not _prev_raw.empty:
                        _prev_raw = apply_exclusions(_prev_raw)
                        _prev_raw = score_shot_quality(_prev_raw)
                        _prev_clean = _prev_raw[~_prev_raw["_excluded"]]
                        for _pm in KEY_METRICS + ["_sqs"]:
                            if _pm in _prev_clean.columns and _prev_clean[_pm].notna().any():
                                _prev_means[_pm] = _prev_clean[_pm].mean()

            def _delta(m, cur_val):
                """Return delta string vs previous session, or None."""
                if m not in _prev_means or pd.isna(_prev_means[m]) or pd.isna(cur_val):
                    return None
                diff = cur_val - _prev_means[m]
                return f"{diff:+.1f} vs prev"

            # ── Averages ────────────────────────────────────────────────────
            st.markdown("#### Averages")
            if _prev_means:
                st.caption("Δ vs previous session shown below each metric.")
            avail = [m for m in KEY_METRICS
                     if m in sess_clean.columns and sess_clean[m].notna().any()]

            # Show avg SQS first if available
            avg_sqs = sess_clean["_sqs"].mean() if "_sqs" in sess_clean.columns else None
            n_avail = len(avail[:10])
            n_cols  = min(5, n_avail + (1 if avg_sqs is not None and not pd.isna(avg_sqs) else 0))
            metric_cols = st.columns(n_cols)

            col_idx = 0
            if avg_sqs is not None and not pd.isna(avg_sqs):
                metric_cols[col_idx % 5].metric(
                    "Avg SQS", f"{avg_sqs:.1f}",
                    delta=_delta("_sqs", avg_sqs),
                )
                col_idx += 1
            for m in avail[:10]:
                cur = sess_clean[m].mean()
                metric_cols[col_idx % 5].metric(
                    metric_col(m), fmt_metric(cur, m),
                    delta=_delta(m, cur), delta_color="off",
                )
                col_idx += 1

            n_sess_excl = int(session_shots["_excluded"].sum())
            if n_sess_excl:
                st.caption(f"ⓘ {n_sess_excl} manually excluded shot(s) not in averages above.")

            st.markdown("---")

            # ── Scatter ──────────────────────────────────────────────────────
            avail_all = [m for m in METRIC_LABELS
                         if m in session_shots.columns and session_shots[m].notna().any()]
            # Prepend SQS if available
            sqs_label = "_sqs"
            if sqs_label in sess_clean.columns and sess_clean[sqs_label].notna().any():
                avail_all = [sqs_label] + avail_all

            def scatter_metric_label(col):
                if col == "_sqs": return "SQS"
                return metric_col(col)

            col_l, col_r = st.columns(2)
            with col_l:
                x_metric = st.selectbox("X axis", avail_all,
                    index=avail_all.index("club_speed") if "club_speed" in avail_all else 0,
                    format_func=scatter_metric_label, key="x_metric")
            with col_r:
                y_metric = st.selectbox("Y axis", avail_all,
                    index=avail_all.index("carry") if "carry" in avail_all else 1,
                    format_func=scatter_metric_label, key="y_metric")

            scatter_df = sess_clean.dropna(subset=[x_metric, y_metric])
            if not scatter_df.empty:
                if multi_session:
                    scatter_df = scatter_df.copy()
                    scatter_df["_session"] = scatter_df["date"].dt.strftime("%m/%d/%y")
                    fig = px.scatter(scatter_df, x=x_metric, y=y_metric,
                        color="_session", symbol="club",
                        hover_data=["shot_number", "club", "_session"],
                        labels={x_metric: scatter_metric_label(x_metric),
                                y_metric: scatter_metric_label(y_metric),
                                "_session": "Session"},
                        title=f"{scatter_metric_label(x_metric)} vs {scatter_metric_label(y_metric)}")
                else:
                    fig = px.scatter(scatter_df, x=x_metric, y=y_metric, color="club",
                        hover_data=["shot_number", "club"],
                        labels={x_metric: scatter_metric_label(x_metric),
                                y_metric: scatter_metric_label(y_metric)},
                        title=f"{scatter_metric_label(x_metric)} vs {scatter_metric_label(y_metric)}")
                fig.update_layout(height=520, plot_bgcolor="white")
                st.plotly_chart(fig, use_container_width=True)

            # ── Shot sequence chart ───────────────────────────────────────────
            st.markdown("---")
            st.subheader("Shot Sequence")
            st.caption(
                "Metric values in shot order — reveals warm-up effects, fatigue, or hot streaks within a session."
            )
            seq_l, seq_r = st.columns([1, 3])
            with seq_l:
                seq_metric = st.selectbox(
                    "Metric", avail_all,
                    index=avail_all.index("_sqs") if "_sqs" in avail_all else 0,
                    format_func=scatter_metric_label,
                    key="seq_metric",
                )
                seq_color_by = st.radio(
                    "Color by", ["Club", "Quality Tier"],
                    horizontal=True, key="seq_color_by",
                )
            with seq_r:
                # Sort by actual shot timestamp when available (Trackman groups strokes
                # by club in StrokeGroups, not chronologically, so shot_number alone is
                # unreliable for existing data — run sync.py --all to fix permanently).
                _seq_df = sess_clean.copy()
                if "shot_time" in _seq_df.columns and _seq_df["shot_time"].notna().any():
                    _seq_df["_sort_key"] = pd.to_datetime(_seq_df["shot_time"], errors="coerce")
                    _seq_df = _seq_df.sort_values("_sort_key").reset_index(drop=True)
                else:
                    _seq_df = _seq_df.sort_values("shot_number").reset_index(drop=True)
                _seq_df["_seq_pos"] = range(1, len(_seq_df) + 1)
                if not _seq_df.empty:
                    if seq_color_by == "Club":
                        fig_seq = px.scatter(
                            _seq_df, x="_seq_pos", y=seq_metric, color="club",
                            labels={"_seq_pos": "Shot #", seq_metric: scatter_metric_label(seq_metric)},
                            title=f"{scatter_metric_label(seq_metric)} by Shot Order",
                        )
                    else:
                        fig_seq = px.scatter(
                            _seq_df, x="_seq_pos", y=seq_metric, color="_quality",
                            color_discrete_map=QUALITY_COLORS,
                            category_orders={"_quality": QUALITY_TIERS},
                            labels={"_seq_pos": "Shot #", seq_metric: scatter_metric_label(seq_metric),
                                    "_quality": "Tier"},
                            title=f"{scatter_metric_label(seq_metric)} by Shot Order",
                        )
                    # Rolling mean trend line (skip if too few non-null values)
                    _seq_valid = _seq_df[seq_metric].notna()
                    if _seq_valid.sum() >= 3:
                        _win = max(3, int(_seq_valid.sum()) // 8)
                        _seq_df["_roll"] = _seq_df[seq_metric].rolling(_win, center=True, min_periods=1).mean()
                        fig_seq.add_scatter(
                            x=_seq_df["_seq_pos"], y=_seq_df["_roll"],
                            mode="lines", name=f"{_win}-shot avg",
                            line=dict(color="#555555", width=2, dash="dash"),
                            showlegend=True,
                        )
                    fig_seq.update_layout(height=380, plot_bgcolor="white")
                    st.plotly_chart(fig_seq, use_container_width=True)

            st.markdown("---")

            # ── Shot log + manual exclusion editor ───────────────────────────
            st.subheader("Shot Log")
            st.caption("Check **Exclude** to permanently remove a shot from all charts and averages.")

            display_metrics = [m for m in KEY_METRICS
                                if m in session_shots.columns and session_shots[m].notna().any()]

            edit_df  = session_shots.reset_index(drop=True)
            shot_ids = edit_df["id"].tolist()

            base_cols = ["shot_number", "club"]
            if multi_session:
                edit_df["_sess_label"] = edit_df["date"].dt.strftime("%m/%d/%y")
                base_cols = ["_sess_label"] + base_cols
            editor_input = edit_df[base_cols + display_metrics].copy()
            editor_input.insert(len(base_cols), "Exclude", edit_df["_excluded"].astype(bool))

            # Add SQS and Tier columns if available
            extra_disabled = []
            if "_sqs" in edit_df.columns:
                editor_input.insert(3, "SQS",  edit_df["_sqs"].round(1))
                editor_input.insert(4, "Tier", edit_df["_quality"].fillna("–"))
                extra_disabled = ["SQS", "Tier"]

            rename_map = {"shot_number": "#", "club": "Club", "_sess_label": "Session"}
            rename_map.update({m: metric_col(m) for m in display_metrics})
            editor_display = editor_input.rename(columns=rename_map)

            always_disabled = (["Session"] if multi_session else []) + ["#", "Club"]
            edited = st.data_editor(
                editor_display,
                column_config={
                    "Exclude": st.column_config.CheckboxColumn("Exclude", width="small"),
                    "Session": st.column_config.TextColumn("Session", width="small"),
                    "#":       st.column_config.NumberColumn("#", width="small"),
                    "SQS":     st.column_config.NumberColumn("SQS", width="small", format="%.1f"),
                    "Tier":    st.column_config.TextColumn("Tier", width="small"),
                },
                disabled=always_disabled + extra_disabled + [metric_col(m) for m in display_metrics],
                hide_index=True,
                use_container_width=True,
                key=f"shot_editor_{'_'.join(sorted(selected_ids))}",
            )

            if st.button("💾 Save exclusions", key="save_btn"):
                orig_vals = editor_display["Exclude"].values
                new_vals  = edited["Exclude"].values
                changed = [(i, bool(new_vals[i]))
                           for i in range(len(orig_vals)) if orig_vals[i] != new_vals[i]]

                if changed:
                    for i, new_val in changed:
                        db.update_shot_excluded(shot_ids[i], 1 if new_val else None)
                    editor_key = f"shot_editor_{'_'.join(sorted(selected_ids))}"
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
            )
            if not show_all_clubs:
                top = club_agg.nlargest(8, "Shots")["club"].tolist()
                club_agg = club_agg[club_agg["club"].isin(top)]
            # Order bars by canonical club order (longest → shortest)
            club_agg["_order"] = club_agg["club"].map(lambda c: _CLUB_RANK.get(c, 999))
            club_agg = club_agg.sort_values("_order").drop(columns="_order")

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
        # Order rows by canonical club order
        full_agg["_order"] = full_agg["club"].map(lambda c: _CLUB_RANK.get(c, 999))
        full_agg = full_agg.sort_values("_order").drop(columns="_order")
        if "_sqs" in chart_shots.columns and chart_shots["_sqs"].notna().any():
            sqs_by_club = (
                chart_shots.dropna(subset=["_sqs"])
                .groupby("club")["_sqs"].mean().round(1)
            )
            full_agg["_sqs"] = full_agg["club"].map(sqs_by_club)
            full_agg = full_agg[["club", "_sqs"] + avail_metrics]
            full_agg.columns = ["Club", "Avg SQS"] + [metric_col(m) for m in avail_metrics]
        else:
            full_agg.columns = ["Club"] + [metric_col(m) for m in avail_metrics]
        st.dataframe(full_agg.set_index("Club"), use_container_width=True)



# ============================================================
# TAB 5 – Dispersion
# ============================================================
with tab_dispersion:
    st.header("Shot Dispersion")

    if chart_shots.empty:
        st.info("No shot data available for the selected filters.")
    else:
        disp_clubs_avail = sort_clubs(chart_shots["club"].dropna().unique().tolist())
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
                show_tracers = st.checkbox("Show tracers", value=True, key="disp_tracers")
                show_circles = st.checkbox("Dispersion circles (±1σ)", value=False, key="disp_circles")
            else:
                show_tracers = True
                show_circles = False

        with col_r:
            if not sel_clubs:
                st.info("Select at least one club.")
            else:
                all_traj = load_trajectories()
                valid_ids = set(chart_shots[chart_shots["club"].isin(sel_clubs)]["id"].tolist())
                traj_data = [t for t in all_traj if t["id"] in valid_ids]

                palette = px.colors.qualitative.Plotly
                club_color = {c: palette[i % len(palette)] for i, c in enumerate(sort_clubs(sel_clubs))}

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
                                showlegend=False,
                                line=dict(color=club_color[club], width=1.2),
                                opacity=0.15,
                            ))

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

                if not has_any_traj:
                    st.warning("No trajectory data found. Make sure shots were synced with raw_json.")
                else:
                    if view_mode == "Top-down":
                        # Fix x-axis to the selected clubs' shots (not all shots) so one
                        # stray driver doesn't blow out the iron dispersion view.
                        _disp_off = (
                            chart_shots[chart_shots["club"].isin(sel_clubs)]["offline"].abs()
                            if sel_clubs else chart_shots["offline"].abs()
                        )
                        max_off = _disp_off.max() if not _disp_off.empty else 30
                        if pd.isna(max_off) or max_off == 0:
                            max_off = 30
                        x_pad = max(max_off + 3, 25)  # fixed 3 yd margin, minimum ±25 yds for visual context

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
                            yaxis=dict(rangemode="tozero"),
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
                        for i, club in enumerate(sort_clubs(sel_clubs)):
                            cd = impact_df[impact_df["club"] == club]
                            if cd.empty:
                                continue
                            c = club_color.get(club, palette[i % len(palette)])
                            fig_imp.add_trace(go.Scatter(
                                x=cd["impact_offset"],
                                y=cd["impact_height"],
                                mode="markers",
                                name=club,
                                customdata=cd[["shot_number", "carry", "smash_factor"]].fillna(-1).values,
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
                        height=480, plot_bgcolor="white",
                        xaxis=dict(
                            title="← Heel  ·  Horizontal (cm)  ·  Toe →",
                            range=[-3.5, 3.5],
                            fixedrange=True,
                        ),
                        yaxis=dict(
                            title="Vertical (cm)",
                            range=[-3.0, 3.0],
                            fixedrange=True,
                        ),
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


# ============================================================
# TAB 6 – Quality Analysis
# ============================================================
with tab_quality:
    st.header("Shot Quality Analysis")
    st.caption(
        "Compare swing characteristics across quality tiers to understand "
        "what separates your best shots from your worst."
    )

    # Use all non-excluded shots — ignore sidebar quality filter so all tiers are visible
    qa_base = all_shots[~all_shots["_excluded"]].copy()

    if qa_base.empty or "_quality" not in qa_base.columns or qa_base["_quality"].isna().all():
        st.info("No quality data available. Make sure shots have been synced and scored.")
    else:
        # ── Controls ──────────────────────────────────────────────────────────
        qa_ctrl_l, qa_ctrl_r = st.columns([1, 2])

        with qa_ctrl_l:
            qa_clubs_avail = sort_clubs(qa_base["club"].dropna().unique().tolist())
            qa_clubs = st.multiselect(
                "Filter by club",
                qa_clubs_avail,
                default=qa_clubs_avail,
                key="qa_clubs",
                help="Restrict the analysis to specific clubs, or leave all selected for a full-bag view.",
            )

        # Metrics available in the data — swing-first ordering
        _QA_METRIC_ORDER = [
            "face_to_path", "club_path", "face_angle", "attack_angle",
            "dynamic_loft", "spin_axis", "launch_direction",
            "impact_offset", "impact_height",
            "smash_factor", "launch_angle", "ball_speed", "club_speed",
            "total_spin", "carry",
        ]
        qa_metric_pool = [
            m for m in _QA_METRIC_ORDER
            if m in qa_base.columns and qa_base[m].notna().any()
        ]
        qa_defaults = [
            m for m in [
                "face_to_path", "club_path", "face_angle", "attack_angle",
                "dynamic_loft", "impact_offset", "impact_height", "smash_factor",
            ] if m in qa_metric_pool
        ]

        with qa_ctrl_r:
            qa_metrics = st.multiselect(
                "Metrics to analyse",
                qa_metric_pool,
                default=qa_defaults,
                format_func=metric_col,
                key="qa_metrics",
            )

        qa_chart_type = st.radio(
            "Chart style", ["Box", "Violin", "Bar (mean ± std)"],
            key="qa_chart_type", horizontal=True,
        )

        # ── Tier grouping controls ─────────────────────────────────────────
        use_groups = False
        grp_a_name, grp_b_name = "Upper", "Lower"
        grp_a_tiers: list = []
        grp_b_tiers: list = []
        with st.expander("🔗 Group tiers (optional)", expanded=False):
            use_groups = st.checkbox(
                "Combine tiers into custom groups",
                value=False,
                key="qa_use_groups",
                help="Merge quality tiers into two named groups for side-by-side comparison.",
            )
            if use_groups:
                grp_col1, grp_col2 = st.columns(2)
                with grp_col1:
                    grp_a_name = st.text_input("Group A name", "Upper", key="qa_grp_a_name")
                    grp_a_tiers = st.multiselect(
                        "Group A tiers",
                        QUALITY_TIERS,
                        default=["Tour Quality", "Solid"],
                        key="qa_grp_a_tiers",
                    )
                with grp_col2:
                    grp_b_name = st.text_input("Group B name", "Lower", key="qa_grp_b_name")
                    grp_b_tiers = st.multiselect(
                        "Group B tiers",
                        QUALITY_TIERS,
                        default=["Playable", "Scramble", "Mishit"],
                        key="qa_grp_b_tiers",
                    )
                st.caption("Tiers not assigned to either group are excluded from the grouped view.")

        if not qa_clubs or not qa_metrics:
            st.info("Select at least one club and one metric to begin.")
        else:
            qa_df = qa_base[
                qa_base["club"].isin(qa_clubs) &
                qa_base["_quality"].notna()
            ].copy()
            qa_df["_quality"] = pd.Categorical(
                qa_df["_quality"], categories=QUALITY_TIERS, ordered=True
            )

            # ── Resolve display tiers (individual or grouped) ─────────────────
            if use_groups and (grp_a_tiers or grp_b_tiers):
                _tier_map: dict = {}
                for _t in grp_a_tiers:
                    _tier_map[_t] = grp_a_name or "Group A"
                for _t in grp_b_tiers:
                    _tier_map[_t] = grp_b_name or "Group B"
                qa_df["_display_quality"] = qa_df["_quality"].map(_tier_map)
                qa_df = qa_df[qa_df["_display_quality"].notna()].copy()
                # Ordered: Group A first, then Group B (deduplicated)
                display_tiers: list = []
                for _n in [grp_a_name or "Group A", grp_b_name or "Group B"]:
                    if _n not in display_tiers:
                        display_tiers.append(_n)
                _grp_palette = ["#1d6fb8", "#e36200"]   # blue / orange
                display_colors: dict = {
                    display_tiers[i]: _grp_palette[i % len(_grp_palette)]
                    for i in range(len(display_tiers))
                }
            else:
                qa_df["_display_quality"] = qa_df["_quality"].astype(str)
                display_tiers = list(QUALITY_TIERS)
                display_colors = dict(QUALITY_COLORS)
            qa_df["_display_quality"] = pd.Categorical(
                qa_df["_display_quality"], categories=display_tiers, ordered=True
            )

            # ── Tier summary KPIs ─────────────────────────────────────────────
            st.markdown("---")
            total_qa = len(qa_df)
            tier_summary = (
                qa_df.groupby("_display_quality", observed=False)
                .agg(n=("_sqs", "count"), avg_sqs=("_sqs", "mean"))
            )
            kpi_cols = st.columns(len(display_tiers))
            for i, tier in enumerate(display_tiers):
                n   = int(tier_summary.loc[tier, "n"])   if tier in tier_summary.index else 0
                avg = tier_summary.loc[tier, "avg_sqs"] if tier in tier_summary.index else None
                pct = n / total_qa * 100 if total_qa > 0 else 0
                delta = f"Avg SQS {avg:.1f}" if (avg is not None and not pd.isna(avg) and n > 0) else "–"
                kpi_cols[i].metric(
                    tier,
                    f"{n:,} shots  ({pct:.0f}%)",
                    delta,
                )

            # ── Heatmap overview ──────────────────────────────────────────────
            st.markdown("---")
            st.subheader("Average Values by Tier")

            present_tiers = [t for t in display_tiers if t in qa_df["_display_quality"].unique()]
            heat_means = (
                qa_df.groupby("_display_quality", observed=True)[qa_metrics]
                .mean()
                .reindex(present_tiers)
            )

            # Metric direction rules for colour encoding
            # "abs_lower": best when absolute value is smallest (on-target / centred)
            # "higher":    best when raw value is highest (power/efficiency metrics)
            _ABS_LOWER_BETTER = {
                "face_to_path", "club_path", "face_angle",
                "impact_offset", "impact_height",
                "spin_axis", "launch_direction", "attack_angle",
            }
            _HIGHER_BETTER = {
                "smash_factor", "ball_speed", "club_speed", "carry",
            }

            # Build a normalised colour matrix where green always = better
            heat_norm_cols = {}
            for m in qa_metrics:
                col = heat_means[m]
                if m in _ABS_LOWER_BETTER:
                    # Colour based on absolute deviation; invert so smaller abs = greener
                    abs_col = col.abs()
                    abs_mn, abs_mx = abs_col.min(), abs_col.max()
                    heat_norm_cols[m] = 1.0 - (abs_col - abs_mn) / (abs_mx - abs_mn + 1e-9)
                elif m in _HIGHER_BETTER:
                    mn, mx = col.min(), col.max()
                    heat_norm_cols[m] = (col - mn) / (mx - mn + 1e-9)
                else:
                    # Neutral: show gradient without strong directional claim
                    mn, mx = col.min(), col.max()
                    heat_norm_cols[m] = (col - mn) / (mx - mn + 1e-9)

            # Compress values into [0.18, 0.82] so colours stay pastel and numbers are legible
            heat_norm_df = pd.DataFrame(
                {m: 0.18 + v * 0.64 for m, v in heat_norm_cols.items()},
                index=present_tiers,
            )
            heat_norm_display = heat_norm_df.rename(columns={m: metric_col(m) for m in qa_metrics})

            fig_heat = px.imshow(
                heat_norm_display.T,
                color_continuous_scale="RdYlGn",
                aspect="auto",
                title="Metric Averages by Quality Tier  (green = better, direction-aware per metric)",
                labels=dict(x="Quality Tier", y="Metric", color="Score"),
            )
            # Overlay actual signed averages as annotation text
            heat_annotations = []
            for c_i, tier in enumerate(present_tiers):
                for r_i, m in enumerate(qa_metrics):
                    val = heat_means.loc[tier, m]
                    if not pd.isna(val):
                        heat_annotations.append(dict(
                            x=tier, y=metric_col(m),
                            text=f"{val:.2f}",
                            showarrow=False,
                            font=dict(size=10, color="black"),
                        ))
            fig_heat.update_layout(
                height=max(280, 52 * len(qa_metrics)),
                annotations=heat_annotations,
                coloraxis_showscale=False,
                plot_bgcolor="white",
                xaxis=dict(side="top"),
            )
            st.plotly_chart(fig_heat, use_container_width=True)
            st.caption(
                "🟢 **Green = better** for each metric individually. "
                "Deviation metrics (Face to Path, Club Path, Face Angle, Impact Offset/Height, etc.) "
                "— colour based on absolute value, so closer to 0 is greener. "
                "Performance metrics (Smash Factor, Ball Speed, Carry) — higher is greener. "
                "Numbers show actual signed averages."
            )

            # ── Per-metric distribution charts ────────────────────────────────
            st.markdown("---")
            st.subheader("Distribution by Tier")

            for row_i in range(0, len(qa_metrics), 2):
                grid_cols = st.columns(2)
                for col_j, m in enumerate(qa_metrics[row_i:row_i + 2]):
                    m_df = qa_df.dropna(subset=[m])
                    if m_df.empty:
                        continue
                    with grid_cols[col_j]:
                        if qa_chart_type == "Box":
                            fig_qa = px.box(
                                m_df, x="_display_quality", y=m,
                                color="_display_quality",
                                color_discrete_map=display_colors,
                                category_orders={"_display_quality": display_tiers},
                                points="outliers",
                                labels={"_display_quality": "", m: metric_col(m)},
                                title=metric_col(m),
                            )
                        elif qa_chart_type == "Violin":
                            fig_qa = px.violin(
                                m_df, x="_display_quality", y=m,
                                color="_display_quality",
                                color_discrete_map=display_colors,
                                category_orders={"_display_quality": display_tiers},
                                box=True, points="outliers",
                                labels={"_display_quality": "", m: metric_col(m)},
                                title=metric_col(m),
                            )
                        else:  # Bar mean ± std
                            bar_agg = (
                                m_df.groupby("_display_quality", observed=False)[m]
                                .agg(mean="mean", std="std")
                                .reindex(display_tiers).reset_index()
                            )
                            fig_qa = px.bar(
                                bar_agg, x="_display_quality", y="mean", error_y="std",
                                color="_display_quality",
                                color_discrete_map=display_colors,
                                category_orders={"_display_quality": display_tiers},
                                labels={"_display_quality": "", "mean": metric_col(m)},
                                title=metric_col(m),
                                text="mean",
                            )
                            fig_qa.update_traces(
                                texttemplate="%{text:.2f}", textposition="outside"
                            )
                        fig_qa.update_layout(
                            height=380, plot_bgcolor="white",
                            showlegend=False, xaxis_title="",
                        )
                        st.plotly_chart(fig_qa, use_container_width=True)

            # ── Correlation matrix: metrics vs SQS by club ────────────────────
            st.markdown("---")
            st.subheader("Metric Correlations with SQS")
            st.caption(
                "Pearson r of each swing metric against Shot Quality Score, computed per club. "
                "Strong positive r → metric rises with shot quality. "
                "Strong negative r → lower (or closer-to-zero) values tend to accompany better shots. "
                "Grey cells have too few shots to compute reliably (< 10)."
            )
            _corr_pool = [m for m in qa_metric_pool if m in qa_base.columns]
            _corr_source = qa_base.dropna(subset=["_sqs"])
            if qa_clubs:
                _corr_source = _corr_source[_corr_source["club"].isin(qa_clubs)]

            _corr_clubs = sort_clubs(_corr_source["club"].dropna().unique().tolist())
            _corr_cols  = ["Overall"] + _corr_clubs

            _corr_matrix: dict = {}
            for _cc in _corr_cols:
                _cd = _corr_source if _cc == "Overall" else _corr_source[_corr_source["club"] == _cc]
                _row: dict = {}
                for _cm in _corr_pool:
                    _pair = _cd[["_sqs", _cm]].dropna()
                    if len(_pair) >= 10:
                        _row[_cm] = round(float(_pair.corr().loc["_sqs", _cm]), 2)
                    else:
                        _row[_cm] = np.nan
                _corr_matrix[_cc] = _row

            _corr_df = pd.DataFrame(_corr_matrix, index=_corr_pool)   # metrics × clubs
            _corr_display = _corr_df.rename(index={m: metric_col(m) for m in _corr_pool})

            fig_corr = px.imshow(
                _corr_display,
                color_continuous_scale="RdBu",
                zmin=-1, zmax=1,
                aspect="auto",
                title="Pearson r (metric vs SQS)  —  blue = positive correlation, red = negative",
                labels=dict(x="Club", y="Metric", color="r"),
            )
            # Annotate cells with r value
            _corr_annots = []
            for _ci, _cc in enumerate(_corr_cols):
                for _ri, _cm in enumerate(_corr_pool):
                    _rv = _corr_matrix[_cc].get(_cm, np.nan)
                    if not pd.isna(_rv):
                        _corr_annots.append(dict(
                            x=_cc, y=metric_col(_cm),
                            text=f"{_rv:.2f}",
                            showarrow=False,
                            font=dict(size=10, color="black"),
                        ))
            fig_corr.update_layout(
                height=max(280, 45 * len(_corr_pool)),
                annotations=_corr_annots,
                coloraxis_colorbar=dict(title="r"),
                plot_bgcolor="white",
                xaxis=dict(side="top"),
            )
            st.plotly_chart(fig_corr, use_container_width=True)
