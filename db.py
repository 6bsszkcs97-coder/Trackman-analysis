"""SQLite database layer for Trackman data."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path("data/trackman.db")

# All Trackman ball/club/result metrics we track
SHOT_METRICS = [
    "ball_speed", "club_speed", "smash_factor",
    "launch_angle", "launch_direction",
    "total_spin", "spin_axis",
    "attack_angle", "club_path", "face_angle", "face_to_path", "dynamic_loft",
    "carry", "total", "offline", "peak_height", "descent_angle",
    "impact_offset", "impact_height",
]


@contextmanager
def get_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with get_db() as conn:
        conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS sessions (
                id          TEXT PRIMARY KEY,
                title       TEXT,
                date        TEXT,
                location    TEXT,
                shot_count  INTEGER DEFAULT 0,
                raw_json    TEXT,
                synced_at   TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS shots (
                id              TEXT PRIMARY KEY,
                session_id      TEXT REFERENCES sessions(id),
                shot_number     INTEGER,
                club            TEXT,
                {",".join(f"{m} REAL" for m in SHOT_METRICS)},
                raw_json        TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_shots_session ON shots(session_id);
            CREATE INDEX IF NOT EXISTS idx_shots_club    ON shots(club);
            CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(date);
        """)
        # Migrations: add new columns if they don't exist yet
        for col_def in [
            "excluded INTEGER DEFAULT NULL",
            "impact_offset REAL",
            "impact_height REAL",
        ]:
            try:
                conn.execute(f"ALTER TABLE shots ADD COLUMN {col_def}")
            except Exception:
                pass  # already exists


def session_exists(session_id: str) -> bool:
    with get_db() as conn:
        return conn.execute(
            "SELECT 1 FROM sessions WHERE id=?", (session_id,)
        ).fetchone() is not None


def upsert_session(id, title, date, location, shot_count, raw_json):
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO sessions
               (id, title, date, location, shot_count, raw_json)
               VALUES (?,?,?,?,?,?)""",
            (id, title, date, location, shot_count, raw_json),
        )


def upsert_shot(id, session_id, shot_number, club, **metrics):
    cols = SHOT_METRICS + ["raw_json"]
    vals = [metrics.get(c) for c in cols]
    placeholders = ",".join(["?"] * len(cols))
    with get_db() as conn:
        conn.execute(
            f"""INSERT OR REPLACE INTO shots
                (id, session_id, shot_number, club, {",".join(cols)})
                VALUES (?,?,?,?,{placeholders})""",
            [id, session_id, shot_number, club] + vals,
        )


def get_sessions():
    """Return all sessions as a list of dicts, newest first."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id,title,date,location,shot_count FROM sessions ORDER BY date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_shot_excluded(shot_id: str, value):
    """Set manual exclusion. value=1 (exclude), 0 (force-include), None (auto)."""
    with get_db() as conn:
        conn.execute("UPDATE shots SET excluded=? WHERE id=?", (value, shot_id))


def get_shots(session_id=None, club=None):
    """Return shots, optionally filtered by session and/or club."""
    query = f"""
        SELECT s.id AS session_id, s.date, s.title,
               sh.id, sh.shot_number, sh.club, sh.excluded,
               json_extract(sh.raw_json, '$.Time') AS shot_time,
               {",".join(f"sh.{m}" for m in SHOT_METRICS)}
        FROM shots sh
        JOIN sessions s ON s.id = sh.session_id
        WHERE 1=1
    """
    args = []
    if session_id:
        query += " AND sh.session_id = ?"
        args.append(session_id)
    if club:
        query += " AND sh.club = ?"
        args.append(club)
    query += " ORDER BY s.date, sh.shot_number"

    with get_db() as conn:
        rows = conn.execute(query, args).fetchall()
    return [dict(r) for r in rows]


def get_clubs():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT club FROM shots WHERE club IS NOT NULL AND club != '' ORDER BY club"
        ).fetchall()
    return [r["club"] for r in rows]


def get_trajectories():
    """Return id, session_id, shot_number, club, raw_json for all shots (trajectory parsing)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT sh.id, sh.session_id, sh.shot_number, sh.club, sh.raw_json "
            "FROM shots sh "
            "JOIN sessions s ON s.id = sh.session_id "
            "WHERE sh.raw_json IS NOT NULL "
            "ORDER BY s.date, sh.shot_number"
        ).fetchall()
    return [dict(r) for r in rows]
