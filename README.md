# OrbitWorks

A Civic Brief dashboard for renewable project screening, orbital construction review and environmental case triage in Kutch, Gujarat. This first release uses illustrative land factors, synthetic construction masks and seven simulated environmental cases.

## Run the full app

Use Python 3.12 (64-bit on Windows), the version tested with the pinned NumPy dependency. From the repository root:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn server:create_app --factory --port 3000
```

Open the server at port 3000. Switch between solar and wind rankings, select a site and save a survey decision. In Construction, switch the date to inspect the two simulated masks. In Environmental watch, open a case to request follow-up. Decisions appear in the selected record’s history and Markdown export.

FastAPI serves the frontend and JSON API from the same origin. SQLite stores review history by record, and by resource for siting. Each save checks the version read by the client. The database defaults to `.local/reviews.sqlite3`. Set `ORBITWORKS_DB` to choose a persistent path. The pilot uses a shared review log without user accounts and defaults to a loopback listener. Public hosting of the writable API requires access control and persistent storage.

## Data and static preview

- `data/pilot.json` holds the illustrative siting inputs and environmental scenarios. `portfolio.py` calculates and sorts resource-specific weighted scores.
- `data/*.mask` are two synthetic 100 × 100 classifications at 100 m² per pixel. The reducer compares pixels valid on both dates and requires 70% common coverage. The fixture yields 18.4 ha newly visible across 82% common coverage. The PNGs in `docs/assets` visualize the same classifications.
- `python portfolio.py` regenerates the read-only portfolio snapshot in `docs/pilot.json`. GitHub Pages can serve `main/docs`. The static version supports comparison and export. Decision persistence runs in the Python app.

## Test and inspect

```sh
python -m pip install -r requirements-dev.txt
python -m unittest -v
```

Interactive API documentation is available at `/api/docs`. The portfolio endpoint is `GET /api/portfolio`. Read or append decisions using `GET` or `POST /api/reviews/{record}`. A write takes the selected action and latest version (0 for a new record). A stale write returns 409.
