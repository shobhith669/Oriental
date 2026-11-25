"""Local multi-view pilot with transactional portfolio review decisions."""
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from portfolio import ROOT, portfolio

ACTIONS = {
    "siting": ("Shortlist for survey", "Defer survey"),
    "build": ("Accept visible milestone", "Request inspection"),
    "watch": ("Request HAPS watch", "Request field evidence", "Dismiss signal"),
}


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: str = Field(min_length=1, max_length=50)
    version: int = Field(ge=0, le=2**31-1)


def create_app(database=None):
    db = Path(database or os.environ.get("ORBITWORKS_DB", ROOT / ".local/reviews.sqlite3"))
    db.parent.mkdir(parents=True, exist_ok=True)
    catalog = portfolio()
    records = {f"siting-{mode}-{s['id']}": "siting"
               for mode, sites in catalog["siting"].items() for s in sites}
    for view in ("build", "watch"):
        records.update({f"{view}-{s['id']}": view for s in catalog[view]})
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS reviews (record TEXT NOT NULL, version INTEGER NOT NULL, "
                     "action TEXT NOT NULL, saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                     "PRIMARY KEY(record,version))")
        conn.commit()

    app = FastAPI(title="OrbitWorks", docs_url="/api/docs", redoc_url=None)

    @app.get("/api/portfolio")
    def get_portfolio():
        return {"portfolio": catalog, "actions": ACTIONS}

    @app.get("/api/reviews/{record}")
    def history(record: str):
        if record not in records:
            raise HTTPException(404, "Unknown record")
        with closing(sqlite3.connect(db)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(
                "SELECT version, action, saved_at FROM reviews WHERE record=? ORDER BY version DESC", (record,)
            )]

    @app.post("/api/reviews/{record}", status_code=201)
    def save(record: str, review: Review):
        if record not in records:
            raise HTTPException(404, "Unknown record")
        if review.action not in ACTIONS[records[record]]:
            raise HTTPException(422, "Invalid action for this record")
        try:
            with closing(sqlite3.connect(db, timeout=2)) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                version = conn.execute("SELECT COALESCE(MAX(version),0) FROM reviews WHERE record=?",
                                       (record,)).fetchone()[0]
                if review.version != version:
                    raise HTTPException(409, "The decision history has changed. Review the latest entry.")
                conn.execute("INSERT INTO reviews(record,version,action) VALUES (?,?,?)",
                             (record, version + 1, review.action))
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise HTTPException(503, "Review store busy. Try again.") from exc
            raise
        return {"version": version + 1}

    @app.get("/", response_class=HTMLResponse)
    @app.get("/index.html", response_class=HTMLResponse)
    def index():
        return (ROOT / "docs/index.html").read_text(encoding="utf-8").replace('data-mode="preview"', 'data-mode="connected"')

    app.mount("/", StaticFiles(directory=ROOT / "docs"), name="frontend")
    return app
