# Trackman Golf Dashboard

A personal analytics dashboard for [Trackman](https://www.trackman.com/) golf data. Scrapes your shot history from the Trackman portal, stores it locally in SQLite, and visualizes it in an interactive Streamlit app — entirely on your own machine, no cloud required.

---

## Features

- **Sync your data** — logs into `portal.trackmangolf.com` with your own credentials and pulls your shot history into a local database
- **Shot Quality Score (SQS)** — proprietary 0–100 scoring system benchmarked against PGA Tour averages for carry distance and accuracy, not your personal averages
- **Trends page** — metrics over time, shot quality distribution per session, avg SQS trend by club
- **Session detail** — per-session shot log with manual exclusion, scatter plot explorer, session averages
- **Club comparison** — side-by-side averages and radar chart across clubs
- **Shot Dispersion** — top-down trajectory view with dots-only mode, ±1σ dispersion ellipses per club, and fixed axis scaling
- **CSV export** — one-click download of every shot with all metrics and SQS scores

---

## Metrics tracked

| Category | Metrics |
|---|---|
| Speed | Club Speed (mph), Ball Speed (mph), Smash Factor |
| Launch | Launch Angle, Launch Direction, Attack Angle |
| Spin | Total Spin (rpm), Spin Axis, Dynamic Loft |
| Shape | Club Path, Face Angle, Face to Path |
| Distance | Carry (yds), Total Distance (yds), Offline (yds), Peak Height (yds) |
| Landing | Descent Angle, Impact Offset (cm), Impact Height (cm) |

---

## Shot Quality Score (SQS)

```
SQS = (0.55 × Carry Score) + (0.45 × Accuracy Score)
```

**Carry Score** — actual carry vs PGA Tour average for that club, on a power curve (exponent 1.4). 100% of tour carry = 100. 50% or below = 0.

**Accuracy Score** — absolute offline distance scaled to club-specific PGA Tour dispersion. Dead straight = 100. Scales down through four zones (tight / tour average / wide / extreme).

| Tier | SQS |
|---|---|
| Tour Quality | 80–100 |
| Solid | 65–79 |
| Playable | 45–64 |
| Scramble | 25–44 |
| Mishit | 0–24 |

Benchmarks are fixed PGA Tour numbers — not derived from your personal data — so scores are consistent and comparable across sessions and golfers.

---

## Requirements

- Python 3.11+
- A [Trackman portal](https://portal.trackmangolf.com) account

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
cd trackman-analysis

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate       # macOS / Linux
.venv\Scripts\activate          # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install the Playwright browser
playwright install chromium
```

---

## Usage

### Sync your data

Run this after each session (or any time you want fresh data):

```bash
python sync.py
```

A Chrome window opens — log in with your Trackman account. Your session is saved to `data/browser_session.json` so you only need to log in once. All sessions and shots are stored in `data/trackman.db`.

To force a full re-sync of every session:

```bash
python sync.py --all
```

### Launch the dashboard

```bash
streamlit run app.py
```

Opens at [http://localhost:8501](http://localhost:8501).

---

## Project structure

```
├── app.py                  # Streamlit dashboard
├── sync.py                 # Data sync script (Playwright + REST API)
├── db.py                   # SQLite layer
├── requirements.txt
├── data/
│   ├── trackman.db         # Your shot database (gitignored)
│   ├── browser_session.json  # Saved login session (gitignored)
│   └── raw/                # Raw API responses, useful for debugging
```

---

## How sync works

1. A browser window opens and you log into your Trackman account normally
2. The sync script reads your session list from the network responses the portal already loads for you
3. Each session has a shareable report link — shot data is fetched from that link's public endpoint
4. Speeds are converted from m/s → mph; all distances are already in yards

---

## Troubleshooting

**No data showing** — Run `python sync.py` first.

**Login expired** — Delete `data/browser_session.json` and re-run `python sync.py`.

**New session not appearing** — Click **Refresh data** in the sidebar or restart the app.

**Missing metrics for some shots** — Some shots (topped balls, chips) may have incomplete TrackMan data. This is expected; those shots will have `null` for the affected fields.

**Parsing issues** — Raw API responses are saved to `data/raw/*.json`. Inspect those files to check field names if you need to modify `FIELD_MAP` in `sync.py`.

---

## Privacy

All data is stored locally on your machine. Nothing is sent to any external server beyond the Trackman API calls needed to fetch your own data.

---

## Disclaimer

This is an independent personal project and is not affiliated with, endorsed by, or associated with Trackman A/S in any way. Trackman is a registered trademark of Trackman A/S. This tool accesses only your own data using your own credentials and is intended strictly for personal use.
