import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from observations import (
    CACHE,
    SOURCES,
    aggregate_ais,
    fetch_source,
    local_raster,
    NoData,
)
from portfolio import ROOT
from server import create_app

START, END = date(2024, 3, 1), date(2024, 3, 7)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def read(self, source, payloads, lat=23.9, lon=69.7):
        seen = []

        def transport(req):
            seen.append(req)
            item = payloads[len(seen) - 1]
            if isinstance(item, bytes):
                return httpx.Response(200, content=item)
            return httpx.Response(200, json=item)

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, ORBITWORKS_RASTERS=folder),
        ):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(transport)
            ) as client:
                return await fetch_source(source, lat, lon, START, END, client)

    async def test_worldwide_history(self):
        data = await self.read("history", [], lat=52.52, lon=13.405)
        self.assertIn("1° cell", data["summary"])
        self.assertTrue(data["rows"])
        self.assertTrue(all(row["quarter_end"] <= END.isoformat() for row in data["rows"]))

    async def test_real_quarterly_inventory(self):
        data = await self.read("history", [], lat=23.35, lon=69.2)
        self.assertGreater(sum(r["wind_turbines"] for r in data["rows"]), 0)
        self.assertTrue(all(r["quarter_end"] <= END.isoformat() for r in data["rows"]))

    async def test_power_uses_only_paired_valid_days(self):
        r = await self.read(
            "power",
            [
                {
                    "properties": {
                        "parameter": {
                            "ALLSKY_SFC_SW_DWN": {"a": 0, "b": 6, "c": -999},
                            "WS50M": {"a": 0, "b": 2, "c": 4},
                        }
                    }
                }
            ],
        )
        self.assertEqual(
            r["metrics"], {"mean_solar_kwh_m2_day": 3, "mean_wind_50m_ms": 1}
        )
        self.assertEqual(len(r["rows"]), 2)

    async def test_catalogs_point_sampling_and_granules(self):
        scene = {
            "id": "test",
            "properties": {"datetime": "2024-03-02", "eo:cloud_cover": 3},
            "assets": {},
        }
        for dataset in ("landsat", "sentinel1", "sentinel2"):
            r = await self.read(dataset, [{"features": [scene]}])
            self.assertEqual(r["rows"][0]["scene"], "test")
        self.assertEqual(
            (
                await self.read(
                    "worldcover", [{"features": [scene]}, {"values": [[80]]}]
                )
            )["summary"],
            "Permanent water",
        )
        with self.assertRaises(NoData):
            await self.read("viirs", [{"feed": {"entry": []}}])
        r = await self.read(
            "viirs",
            [{"feed": {"entry": [{"title": "tile", "time_start": "2024-03-01"}]}}],
        )
        self.assertEqual(r["rows"][0]["granule"], "tile")

    async def test_landsat_masks_and_scales_the_point(self):
        scenes = {
            "features": [
                {"id": "LC09_sample", "properties": {"datetime": "2024-03-03"}}
            ]
        }
        pixel = {
            "band_names": [
                "red_b1",
                "green_b1",
                "nir08_b1",
                "qa_pixel_b1",
                "qa_radsat_b1",
            ],
            "values": [12000, 14000, 18000, 128, 0],
        }
        row = (await self.read("landsat", [scenes, pixel]))["rows"][0]
        self.assertAlmostEqual(row["ndvi"], 0.165 / 0.425, places=4)
        self.assertLess(row["water_red_green_index"], 0)
        pixel["values"][3] = 8
        masked = (await self.read("landsat", [scenes, pixel]))["rows"][0]
        self.assertNotIn("ndvi", masked)
        self.assertIn("Masked", masked["pixel_status"])

    async def test_context_and_grid(self):
        r = await self.read(
            "osm",
            [
                {
                    "elements": [
                        {"type": "way", "id": 1, "center": {"lat": 24, "lon": 70}},
                        {"type": "node", "id": 2, "lat": 23.9, "lon": 69.7},
                    ]
                }
            ],
        )
        self.assertEqual(r["points"][0]["distance_km"], 0)
        self.assertEqual(
            (await self.read("dem", [{"elevation": [0, 500, 0, 0]}]))["rows"][0][
                "slope_deg"
            ],
            45,
        )
        for key in ("ghsl", "bhuvan"):
            r = await self.read(
                key,
                [
                    b"<WMS_Capabilities><Layer><Name>GHS_BUILT_S</Name><Title>Built-up</Title></Layer></WMS_Capabilities>"
                ],
            )
            self.assertEqual(r["rows"][0]["layer"], "GHS_BUILT_S")
        weather = await self.read(
            "weather",
            [
                {
                    "current": {
                        "wind_speed_10m": 3,
                        "shortwave_radiation": 0,
                        "time": "2024-03-01T23:00",
                    }
                }
            ],
        )
        self.assertIn("0 W/m", weather["summary"])
        ais = await self.read(
            "ais",
            [{"features": [{"geometry": {"coordinates": [24.1, 60]}}]}],
            lat=60,
            lon=24,
        )
        self.assertEqual(ais["rows"][0]["count"], 1)
        with self.assertRaises(NoData):
            await self.read("ais", [])
        self.assertEqual(
            (await self.read("debris", [[{"EPOCH": "2024-03-01"}]]))["rows"][0][
                "count"
            ],
            1,
        )


class SpatialTests(unittest.TestCase):
    def test_local_raster(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, ORBITWORKS_RASTERS=folder),
        ):
            path = Path(folder) / "ghsl.tif"
            with rasterio.open(
                path,
                "w",
                driver="GTiff",
                width=3,
                height=3,
                count=1,
                dtype="uint16",
                nodata=65535,
                crs="EPSG:4326",
                transform=from_origin(69, 24, 0.1, 0.1),
            ) as ds:
                ds.write(
                    np.array([[65535, 2, 3], [4, 5, 6], [7, 8, 9]], dtype=np.uint16), 1
                )
            self.assertEqual(
                local_raster("ghsl", 23.85, 69.15)["rows"][0]["built_surface_m2"], 5
            )
            with self.assertRaises(NoData):
                local_raster("ghsl", 23.95, 69.05)
            with self.assertRaises(NoData):
                local_raster("ghsl", 0, 0)

    def test_ais_date_radius_and_privacy(self):
        raw = b"MMSI,BaseDateTime,LAT,LON\n123,2024-03-02T00:00:00Z,23.9,69.7\n123,2024-03-03,23.9,69.7\n234,2024-03-03,0,0\n345,2024-04-01,23.9,69.7\n456,bad,0,0\n"
        data = aggregate_ais(raw, 23.9, 69.7, START, END)
        self.assertEqual(
            data["rows"][0],
            {"vessels": 1, "reports": 2, "invalid_rows": 1, "radius_km": 25},
        )
        self.assertNotIn("123", json.dumps(data))

    def test_workspace(self):
        CACHE.clear()
        with (
            tempfile.TemporaryDirectory() as folder,
            TestClient(create_app(Path(folder) / "reviews.db")) as c,
        ):
            self.assertEqual(set(c.get("/api/sources").json()), set(SOURCES))
            route = (
                "/api/observations/power?lat=24&lon=70&start=2024-03-01&end=2024-03-05"
            )
            with patch(
                "observations.fetch_source",
                side_effect=httpx.ConnectError("provider unreachable"),
            ):
                self.assertEqual(c.get(route).json()["status"], "unavailable")
            self.assertEqual(c.get(route.replace("lat=24", "lat=99")).status_code, 422)
            self.assertEqual(c.get(route.replace("03-05", "02-05")).status_code, 422)
            self.assertIn("Renewables atlas", c.get("/").text)
            self.assertIn('data-mode="connected"', c.get("/pilot.html").text)
        data = json.loads(
            (ROOT / "docs/assets/geo/kutch.geojson").read_text(encoding="utf-8")
        )
        self.assertEqual(len(data["features"]), 2440)
