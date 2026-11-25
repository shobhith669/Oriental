import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from portfolio import ROOT
from server import create_app


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = Path(folder.name) / "reviews.sqlite3"
        self.client = TestClient(create_app(self.db))
        self.addCleanup(self.client.close)

    def test_snapshot_and_connected_entry(self):
        portfolio = self.client.get("/api/portfolio").json()["portfolio"]
        self.assertEqual(portfolio, json.loads((ROOT / "docs/pilot.json").read_text(encoding="utf-8")))
        self.assertEqual(portfolio["siting"]["Wind"][0]["id"], "B")
        self.assertEqual(portfolio["build"][0]["value"], "18.4 ha")
        self.assertEqual(len(portfolio["watch"]), 7)
        self.assertIn('data-mode="connected"', self.client.get("/index.html").text)

    def test_conflict_and_restart(self):
        route = "/api/reviews/siting-Solar-A"
        def save(_):
            return self.client.post(route, json={"action":"Shortlist for survey", "version":0}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(save, range(2))), [201,409])
        with TestClient(create_app(self.db)) as restarted:
            rows = restarted.get(route).json()
            self.assertEqual([row["version"] for row in rows], [1])
            self.assertEqual(rows[0]["action"], "Shortlist for survey")
            self.assertEqual(restarted.get("/api/reviews/siting-Wind-A").json(), [])

    def test_invalid_review(self):
        route = "/api/reviews/watch-2"
        for body in ({"action":"Shortlist for survey","version":0},
                     {"action":"Request HAPS watch","version":True}):
            self.assertEqual(self.client.post(route, json=body).status_code, 422)
        self.assertEqual(self.client.get("/api/reviews/watch-9").status_code, 404)
        self.assertEqual(self.client.get(route).json(), [])
