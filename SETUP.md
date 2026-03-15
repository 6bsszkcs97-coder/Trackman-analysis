# Trackman Golf Dashboard – Setup

## One-time setup

```bash
# 1. Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Playwright browser
playwright install chromium
```

## Syncing your data

Run this after every session (or whenever you want fresh data):

```bash
python sync.py
```

- A **Chrome window opens** – log in with your Trackman account
- Your session credentials are saved to `data/browser_session.json` so you only need to log in once
- All sessions are scraped and saved to `data/trackman.db`
- Raw API responses are saved to `data/raw/` in case you need to debug/reparse

To re-sync ALL sessions (not just new ones):
```bash
python sync.py --all
```

## Viewing the dashboard

```bash
streamlit run app.py
```

Opens at http://localhost:8501

## Troubleshooting

**"No data yet" screen** – Run `python sync.py` first.

**Parser misses data** – The scraper saves all raw API responses to `data/raw/*.json`.
Open a few of those files to see the actual field names Trackman uses, then update
the `FIELD_MAP` dictionary in `sync.py` to match.

**Login expires** – Delete `data/browser_session.json` and re-run `python sync.py`.

**New sessions not showing** – Click "Refresh data" in the sidebar, or restart the
Streamlit app.
