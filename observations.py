"""Provider adapters for the map workspace. Every result carries its source and time basis."""

import asyncio
import math
import json
import csv
import io
import os
import time
from calendar import monthrange
from functools import lru_cache
from collections import OrderedDict
from datetime import date, datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from rasterio import open as open_raster
from rasterio.warp import transform
from rasterio.windows import Window

router = APIRouter()
PC = "https://planetarycomputer.microsoft.com/api/stac/v1"
BUV = "https://bhuvan-vec1.nrsc.gov.in/bhuvan/wms"
JRC = "https://jeodpp.jrc.ec.europa.eu/services/shared/ows"
COLLECTIONS = {
    "sentinel1": "sentinel-1-grd",
    "sentinel2": "sentinel-2-l2a",
    "landsat": "landsat-c2-l2",
}
SOURCES = {
    "history": (
        "Global Renewables Watch",
        "https://github.com/microsoft/global-renewables-watch/releases/tag/v1.0",
        "Worldwide quarterly detections through 2024 Q2 · individual features in Kutch",
    ),
    "power": (
        "NASA POWER",
        "https://power.larc.nasa.gov/",
        "Daily historical model estimates",
    ),
    "weather": ("Open-Meteo", "https://open-meteo.com/", "Latest modeled conditions"),
    "osm": (
        "OpenStreetMap contributors",
        "https://www.openstreetmap.org/copyright",
        "Current mapped substations within 20 km",
    ),
    **{
        k: (
            name,
            PC + "/collections/" + COLLECTIONS[k],
            "Acquisitions in selected dates",
        )
        for k, name in [
            ("sentinel1", "Sentinel-1 radar"),
            ("sentinel2", "Sentinel-2 optical"),
            ("landsat", "Landsat Collection 2"),
        ]
    },
    "viirs": (
        "NASA VIIRS Black Marble",
        "https://blackmarble.gsfc.nasa.gov/",
        "VNP46A2 granules in selected dates",
    ),
    "worldcover": (
        "ESA WorldCover",
        "https://esa-worldcover.org/en",
        "2021 land cover at the selected point",
    ),
    "ghsl": (
        "JRC Global Human Settlement Layer",
        "https://human-settlement.emergency.copernicus.eu/",
        "Reference raster or available GHSL map layers",
    ),
    "bhuvan": (
        "ISRO Bhuvan",
        "https://bhuvan.nrsc.gov.in/",
        "Available regional WMS layers",
    ),
    "dem": (
        "Terrain slope",
        "https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM",
        "Local DEM or Copernicus GLO-90 via Open-Meteo Elevation · approximate slope",
    ),
    "ais": (
        "Fintraffic Digitraffic AIS",
        "https://www.digitraffic.fi/en/marine-traffic/",
        "Recent aggregate vessel reports · Finnish waters",
    ),
    "debris": (
        "CelesTrak debris catalog",
        "https://celestrak.org/NORAD/elements/",
        "Global COSMOS 2251 debris catalog snapshot",
    ),
}
CLASSES = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare / sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss / lichen",
}
CACHE = OrderedDict()
TTL = 300


class NoData(Exception):
    pass


async def request(client, url, params, xml=False):
    async with client.stream("GET", url, params=params) as res:
        res.raise_for_status()
        buf = bytearray()
        async for chunk in res.aiter_bytes():
            buf.extend(chunk)
            if len(buf) > 12_000_000:
                raise ValueError("Response exceeds size limit")
    if xml:
        return ElementTree.fromstring(buf)
    return json.loads(buf)


def result(summary, rows=(), points=(), **extra):
    return {"summary": summary, "rows": list(rows), "points": list(points), **extra}


def number(value):
    return type(value) in (float, int) and math.isfinite(value)


def distance(lat, lon, y, x):
    a = (
        math.sin(math.radians(y - lat) / 2) ** 2
        + math.cos(math.radians(lat))
        * math.cos(math.radians(y))
        * math.sin(math.radians(x - lon) / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(min(1, a)))


def local_raster(source, lat, lon):
    folder = Path(
        os.environ.get(
            "ORBITWORKS_RASTERS", Path(__file__).resolve().parent / ".local/rasters"
        )
    )
    path = folder / (source + ".tif")
    if not path.is_file():
        return None
    with open_raster(path, driver="GTiff") as ds:
        x, y = transform("EPSG:4326", ds.crs, [lon], [lat])
        row, col = ds.index(x[0], y[0])
        if not (0 <= row < ds.height and 0 <= col < ds.width):
            raise NoData("Point is outside the installed raster.")
        if source == "dem":
            if not (
                ds.crs.is_projected
                and ds.crs.linear_units in ("metre", "meter")
                and ds.transform.b == ds.transform.d == 0
            ):
                raise NoData("Slope needs a north-up projected DEM with metre units.")
            patch = ds.read(
                1, window=Window(col - 1, row - 1, 3, 3), masked=True
            ).astype(float)
            import numpy as np

            if (
                patch.shape != (3, 3)
                or np.ma.getmaskarray(patch).any()
                or not np.isfinite(patch).all()
            ):
                raise NoData("A complete 3 × 3 elevation window is required.")
            gx = (patch[1, 2] - patch[1, 0]) / (2 * ds.res[0])
            gy = (patch[2, 1] - patch[0, 1]) / (2 * ds.res[1])
            val = round(math.degrees(math.atan(math.hypot(gx, gy))), 2)
            return result(
                f"{val}° terrain slope", [{"slope_deg": val, "resolution_m": ds.res[0]}]
            )
        pixel = ds.read(1, window=Window(col, row, 1, 1), masked=True)[0, 0]
        if getattr(pixel, "mask", False) or not math.isfinite(float(pixel)):
            raise NoData("No valid pixel at this point.")
        if source == "bhuvan":
            tags = ds.tags()
            return result(
                f"Regional raster value {float(pixel):g}",
                [
                    {
                        "pixel_value": float(pixel),
                        "layer": tags.get("TITLE", path.name),
                        "units": tags.get("UNITS", "See product legend"),
                        "epoch": tags.get("EPOCH", "See input file"),
                    }
                ],
            )
        if source == "ghsl":
            return result(
                f"{float(pixel):g} m² built-up surface in the reference cell",
                [
                    {
                        "built_surface_m2": float(pixel),
                        "dataset": "GHS-BUILT-S · installed raster",
                        "epoch": ds.tags().get("EPOCH", "See input file"),
                    }
                ],
            )
        return cover(int(pixel))


def cover(code):
    if code not in CLASSES:
        raise NoData("WorldCover class unavailable.")
    return result(
        CLASSES[code], [{"class": code, "land_cover": CLASSES[code], "epoch": 2021}]
    )


async def landsat_indices(client, row, lon, lat):
    """Quality-filter a single OLI surface reflectance pixel. Preserve catalog results on outages."""
    if not row["scene"].startswith(("LC08", "LC09")):
        return
    bands = ["red", "green", "nir08", "qa_pixel", "qa_radsat"]
    args = [("collection", COLLECTIONS["landsat"]), ("item", row["scene"])]
    args.extend(("assets", b) for b in bands)
    try:
        sample = await asyncio.wait_for(
            request(
                client,
                f"https://planetarycomputer.microsoft.com/api/data/v1/item/point/{lon},{lat}",
                args,
            ),
            6,
        )
        values = {
            name.removesuffix("_b1"): val
            for name, val in zip(sample["band_names"], sample["values"])
        }
        if any(not number(values.get(b)) for b in bands):
            row["pixel_status"] = "Missing point data"
            return
        qa = int(values["qa_pixel"])
        if qa & 0b111111 or values["qa_radsat"] != 0:
            row["pixel_status"] = (
                "Masked by cloud, shadow, snow, fill or saturation quality flags"
            )
            return
        red, green, nir = [values[b] * 0.0000275 - 0.2 for b in bands[:3]]
        row["pixel_status"] = "Quality-screened surface reflectance"
        if min(red, nir) >= 0 and red + nir > 0:
            row["ndvi"] = round((nir - red) / (nir + red), 4)
        if qa & (1 << 7) and min(red, green) >= 0 and red + green > 0:
            row["water_red_green_index"] = round((red - green) / (red + green), 4)
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError, IndexError):
        row["pixel_status"] = "Point sample unavailable"


@lru_cache(maxsize=1)
def historical_points():
    path = Path(__file__).resolve().parent / "docs/assets/geo/kutch.geojson"
    data = json.loads(path.read_text(encoding="utf-8"))
    records = []
    for feature in data["features"]:
        geometry, props = feature["geometry"], feature["properties"]
        if geometry["type"] == "Point":
            lon, lat = geometry["coordinates"]
        else:
            xs, ys = zip(*geometry["coordinates"][0])
            lon, lat = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        year, quarter = props["period"].split(" Q")
        month = 3 * int(quarter)
        quarter_end = date(int(year), month, monthrange(int(year), month)[1])
        records.append((lat, lon, quarter_end, props["kind"], props["area_ha"] or 0))
    return records


@lru_cache(maxsize=1)
def worldwide_inventory():
    path = Path(__file__).resolve().parent / "docs/assets/geo/global-cells.json"
    return {
        (x, y): series for x, y, series in json.loads(path.read_text(encoding="utf-8"))
    }


def history_summary(lat, lon, start, end):
    if end < date(2017, 12, 31):
        raise NoData("The first inventory is the 2017 Q4 baseline.")
    if not (68 <= lon <= 71.5 and 22.6 <= lat <= 24.6):
        x, y = math.floor((lon + 180) % 360 - 180), math.floor(lat)
        series = worldwide_inventory().get((x, y), [])
        rows = []
        for index, solar, wind in series:
            year, q = divmod(2017 * 4 + 3 + index, 4)
            month = 3 * (q + 1)
            detected = date(year, month, monthrange(year, month)[1])
            if detected <= end:
                rows.append(
                    {
                        "quarter_end": detected.isoformat(),
                        "solar_footprints": solar,
                        "wind_turbines": wind,
                    }
                )
        count = sum(r["solar_footprints"] + r["wind_turbines"] for r in rows)
        in_window = sum(
            r["solar_footprints"] + r["wind_turbines"]
            for r in rows
            if start.isoformat() <= r["quarter_end"] and r["quarter_end"] > "2017-12-31"
        )
        note = (
            "No coverage after June 2024."
            if start > date(2024, 6, 30)
            else f"{in_window} first detections in completed non-baseline quarters ending in the window."
        )
        return result(
            f"{count} archived assets in the selected 1° cell by {min(end, date(2024, 6, 30))}. {note}",
            rows,
            spatial_basis=f"Whole grid cell from ({y}, {x}) to ({y + 1}, {x + 1}).",
        )
    quarters = {}
    for y, x, detected, kind, area in historical_points():
        if detected > end or distance(lat, lon, y, x) > 25:
            continue
        key = detected.isoformat()
        row = quarters.setdefault(
            key,
            {
                "quarter_end": key,
                "solar_footprints": 0,
                "wind_turbines": 0,
                "solar_ha": 0.0,
            },
        )
        row["solar_footprints" if kind == "solar" else "wind_turbines"] += 1
        row["solar_ha"] += area
    rows = [quarters[k] for k in sorted(quarters)]
    for row in rows:
        row["solar_ha"] = round(row["solar_ha"], 2)
    count = sum(r["solar_footprints"] + r["wind_turbines"] for r in rows)
    cutoff = min(end, date(2024, 6, 30))
    note = (
        "No coverage after June 2024."
        if start > cutoff
        else "Only completed inventory quarters count."
    )
    if start <= cutoff:
        added = sum(
            r["solar_footprints"] + r["wind_turbines"]
            for r in rows
            if start.isoformat() <= r["quarter_end"] and r["quarter_end"] > "2017-12-31"
        )
        note += f" {added} first detections in completed non-baseline quarters ending in the window."
    return result(
        f"{count} archived assets within 25 km by {cutoff}. {note}",
        rows,
        spatial_basis="Turbine coordinates and solar bounding-box centres in the Kutch extract.",
    )


async def fetch_source(src, lat, lon, start, end, client):
    if src == "history":
        return await asyncio.to_thread(history_summary, lat, lon, start, end)
    if src in {"worldcover", "ghsl", "dem", "bhuvan"}:
        local = await asyncio.to_thread(local_raster, src, lat, lon)
        if local:
            return local
        if src == "dem":
            # Elevation API accepts multiple points. Use a 500 m horizontal baseline.
            dy = math.degrees(250 / 6371000)
            dx = dy / math.cos(math.radians(lat))
            xs = [(lon - dx + 180) % 360 - 180, (lon + dx + 180) % 360 - 180, lon, lon]
            ys = [lat, lat, lat - dy, lat + dy]
            data = await request(
                client,
                "https://api.open-meteo.com/v1/elevation",
                {
                    "latitude": ",".join(f"{v:.6f}" for v in ys),
                    "longitude": ",".join(f"{v:.6f}" for v in xs),
                },
            )
            heights = data["elevation"]
            if len(heights) != 4 or not all(number(v) for v in heights):
                raise NoData("Incomplete terrain samples at this point.")
            west, east, south, north = heights
            angle = round(
                math.degrees(math.atan(math.hypot(east - west, north - south) / 500)), 2
            )
            return result(
                f"{angle}° approximate terrain slope",
                [
                    {
                        "slope_deg": angle,
                        "baseline_m": 500,
                        "source": "Open-Meteo Elevation / Copernicus DEM",
                    }
                ],
            )
    if src == "power":
        data = await request(
            client,
            "https://power.larc.nasa.gov/api/temporal/daily/point",
            {
                "parameters": "ALLSKY_SFC_SW_DWN,WS50M",
                "community": "RE",
                "latitude": lat,
                "longitude": lon,
                "start": start.strftime("%Y%m%d"),
                "end": end.strftime("%Y%m%d"),
                "format": "JSON",
            },
        )
        params = data["properties"]["parameter"]
        solar, wind = params["ALLSKY_SFC_SW_DWN"], params["WS50M"]
        rows = [
            {"date": d, "solar_kwh_m2_day": solar[d], "wind_50m_ms": wind[d]}
            for d in sorted(solar)
            if number(solar[d])
            and solar[d] >= 0
            and number(wind.get(d))
            and wind[d] >= 0
        ]
        if not rows:
            raise NoData("No paired valid days were published for this window.")
        s = sum(r["solar_kwh_m2_day"] for r in rows) / len(rows)
        w = sum(r["wind_50m_ms"] for r in rows) / len(rows)
        return result(
            f"{s:.2f} kWh/m²/day · {w:.2f} m/s at 50 m · {len(rows)} paired days",
            rows,
            metrics={
                "mean_solar_kwh_m2_day": round(s, 3),
                "mean_wind_50m_ms": round(w, 3),
            },
        )
    if src == "weather":
        data = await request(
            client,
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": lat,
                "longitude": lon,
                "current": "wind_speed_10m,shortwave_radiation",
                "wind_speed_unit": "ms",
                "timezone": "GMT",
            },
        )
        row = data["current"]
        if not all(number(row[k]) for k in ("wind_speed_10m", "shortwave_radiation")):
            raise NoData("No current modeled values.")
        return result(
            f"{row['wind_speed_10m']} m/s at 10 m · {row['shortwave_radiation']} W/m² · {row['time']} UTC",
            [row],
        )
    if src in COLLECTIONS or src == "worldcover":
        coll = COLLECTIONS.get(src, "esa-worldcover")
        args = {
            "collections": coll,
            "intersects": '{"type":"Point","coordinates":[%s,%s]}' % (lon, lat),
            "limit": 12,
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "sortby": "-properties.datetime",
        }
        if src == "worldcover":
            args["datetime"] = "2021-01-01T00:00:00Z/2021-12-31T23:59:59Z"
        data = await request(client, PC + "/search", args)
        features = data["features"]
        if not features:
            raise NoData("No matching acquisitions for this point and period.")
        if src == "worldcover":
            sample = await request(
                client,
                f"https://planetarycomputer.microsoft.com/api/data/v1/item/point/{lon},{lat}",
                {"collection": coll, "item": features[0]["id"], "assets": "map"},
            )
            value = sample["values"][0]
            return cover(int(value[0] if isinstance(value, list) else value))
        rows = []
        for f in features:
            props = f["properties"]
            row = {
                "scene": f["id"],
                "acquired": props.get("datetime") or props.get("start_datetime"),
            }
            if props.get("eo:cloud_cover") is not None:
                row["scene_cloud_percent"] = round(props["eo:cloud_cover"], 1)
            row["catalog_url"] = f"{PC}/collections/{coll}/items/{f['id']}"
            thumb = (
                f.get("assets", {}).get("rendered_preview")
                or f.get("assets", {}).get("thumbnail")
                or {}
            )
            if thumb.get("href", "").startswith("https://"):
                row["preview_url"] = thumb["href"]
            tilejson = f.get("assets", {}).get("tilejson", {}).get("href", "")
            if tilejson.startswith("https://planetarycomputer.microsoft.com/api/data/"):
                row["tilejson_url"] = tilejson
            rows.append(row)
        summary = (
            f"{len(rows)} recent matching scenes shown · newest {rows[0]['acquired']}"
        )
        if src == "landsat":
            endpoints = rows[:1] if len(rows) == 1 else [rows[0], rows[-1]]
            await asyncio.gather(
                *(landsat_indices(client, r, lon, lat) for r in endpoints)
            )
            if len(endpoints) == 2 and all("ndvi" in r for r in endpoints):
                delta = endpoints[0]["ndvi"] - endpoints[1]["ndvi"]
                summary += f" · NDVI change {delta:+.3f} between displayed endpoints"
        return result(summary, rows)
    if src == "viirs":
        data = await request(
            client,
            "https://cmr.earthdata.nasa.gov/search/granules.json",
            {
                "short_name": "VNP46A2",
                "point": f"{lon},{lat}",
                "temporal": f"{start}T00:00:00Z,{end}T23:59:59Z",
                "sort_key": "-start_date",
                "page_size": 12,
            },
        )
        rows = [
            {"granule": e["title"], "observed": e["time_start"]}
            for e in data["feed"]["entry"]
        ]
        if not rows:
            raise NoData("No Black Marble granules for the search window.")
        return result(f"{len(rows)} matching night-light granules shown", rows)
    if src == "osm":
        q = f'[out:json][timeout:12];nwr(around:20000,{lat},{lon})["power"="substation"];out center 1000;'
        data = await request(
            client, "https://overpass-api.de/api/interpreter", {"data": q}
        )
        if data.get("remark"):
            raise NoData("Overpass returned an incomplete query. Try again.")
        points = []
        for e in data["elements"]:
            c = e.get("center", e)
            if "lat" in c and "lon" in c:
                points.append(
                    {
                        "lat": c["lat"],
                        "lon": c["lon"],
                        "distance_km": round(distance(lat, lon, c["lat"], c["lon"]), 3),
                        "label": e.get("tags", {}).get("name", "Mapped substation"),
                        "osm_id": f"{e['type']}/{e['id']}",
                    }
                )
        points.sort(key=lambda p: p["distance_km"])
        if not points:
            raise NoData(
                "No mapped substations returned within 20 km. Grid access is unknown."
            )
        return result(
            f"{points[0]['distance_km']} km to closest returned substation centre · {len(points)} features",
            points[:12],
            points[:100],
        )
    if src in {"bhuvan", "ghsl"}:
        if src == "bhuvan" and not (5 <= lat <= 38 and 66 <= lon <= 99):
            raise NoData("Bhuvan coverage is regional to India.")
        url = BUV if src == "bhuvan" else JRC
        root = await request(
            client,
            url,
            {"service": "WMS", "request": "GetCapabilities", "version": "1.1.1"},
            xml=True,
        )
        layers = []
        for layer in root.findall(".//{*}Layer"):
            name, title = layer.findtext("{*}Name"), layer.findtext("{*}Title")
            if not name or (
                src == "ghsl"
                and not any(
                    k in (name + " " + (title or "")).lower()
                    for k in ("ghsl", "ghs_built", "ghs-built", "human settlement")
                )
            ):
                continue
            layers.append({"layer": name, "title": title or name})
        if not layers:
            raise NoData(
                "No compatible map layers advertised. For GHSL, install ghsl.tif for quantitative sampling."
            )
        return result(
            f"{len(layers)} advertised layers · select a layer to overlay",
            layers[:150],
            wms=url,
        )
    if src == "ais":
        if not (58 <= lat <= 66.5 and 18 <= lon <= 32):
            raise NoData(
                "Fintraffic covers Finnish waters. Import a local AIS CSV for another coast."
            )
        timestamp = int(time.time()) - 1800
        data = await request(
            client,
            "https://meri.digitraffic.fi/api/ais/v1/locations",
            {"from": timestamp},
        )
        count = 0
        for f in data["features"]:
            x, y = f["geometry"]["coordinates"][:2]
            if distance(lat, lon, y, x) <= 25:
                count += 1
        return result(
            f"{count} vessel positions within 25 km · last 30 minutes",
            [{"count": count, "radius_km": 25, "window_minutes": 30}],
        )
    if src == "debris":
        data = await request(
            client,
            "https://celestrak.org/NORAD/elements/gp.php",
            {"GROUP": "cosmos-2251-debris", "FORMAT": "JSON"},
        )
        epochs = [r["EPOCH"] for r in data if r.get("EPOCH")]
        if not epochs:
            raise NoData("No orbital elements available.")
        return result(
            f"{len(epochs)} debris element sets · latest epoch {max(epochs)} UTC",
            [
                {
                    "catalog": "COSMOS 2251 debris",
                    "count": len(epochs),
                    "oldest_epoch_utc": min(epochs),
                    "newest_epoch_utc": max(epochs),
                }
            ],
        )
    raise ValueError("Unknown source")


@router.get("/api/sources")
def sources():
    return {k: {"name": v[0], "url": v[1], "basis": v[2]} for k, v in SOURCES.items()}


@router.get("/api/observations/{source}")
async def observation(
    source: str,
    start: date,
    end: date,
    lat: float = Query(ge=-85, le=85),
    lon: float = Query(ge=-180, le=180),
):
    if source not in SOURCES:
        raise HTTPException(404, "Unknown dataset")
    if (
        end < start
        or (end - start).days > 91
        or end > datetime.now(timezone.utc).date()
    ):
        raise HTTPException(422, "Choose a past or current window of 1–92 days.")
    query = {"lat": lat, "lon": lon, "start": start, "end": end}
    # Reuse the global catalog across points and date windows.
    key = (source,) if source == "debris" else (source, lat, lon, start, end)
    ttl = 7200 if source == "debris" else TTL
    cached = CACHE.get(key)
    if cached and time.monotonic() - cached[0] < ttl:
        return {**cached[1], "query": query}
    try:
        async with httpx.AsyncClient(
            timeout=14,
            headers={
                "User-Agent": "OrbitWorks/1.0",
                "Digitraffic-User": "OrbitWorks/local-pilot",
            },
        ) as client:
            data = await asyncio.wait_for(
                fetch_source(source, lat, lon, start, end, client), 25
            )
        status = "available"
    except NoData as exc:
        data = result(str(exc))
        status = "no_data"
    except (
        httpx.HTTPError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        ElementTree.ParseError,
    ) as exc:
        reason = (
            f"HTTP {exc.response.status_code}"
            if isinstance(exc, httpx.HTTPStatusError)
            else type(exc).__name__
        )
        data = result(f"Provider or raster unavailable ({reason}).")
        status = "unavailable"
    response = {
        "source": source,
        "provider": SOURCES[source][0],
        "source_url": SOURCES[source][1],
        "time_basis": SOURCES[source][2],
        "checked_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "query": query,
        **data,
    }
    if status != "unavailable":
        CACHE[key] = (time.monotonic(), response)
        if len(CACHE) > 256:
            CACHE.popitem(last=False)
    return response


def aggregate_ais(raw, lat, lon, start, end):
    """Accept UTC AIS positions and retain only aggregates for the selected coastal area."""
    with io.StringIO(raw.decode("utf-8-sig"), newline="") as stream:
        reader = csv.DictReader(stream)
        columns = {key.strip().lower(): key for key in reader.fieldnames or []}
        stamp = columns.get("timestamp") or columns.get("basedatetime")
        ykey = columns.get("lat") or columns.get("latitude")
        xkey = columns.get("lon") or columns.get("longitude")
        vessel = columns.get("mmsi")
        if not all([stamp, ykey, xkey, vessel]):
            raise ValueError(
                "Include timestamp (or BaseDateTime), lat, lon and MMSI columns."
            )
        vessels = set()
        matched = invalid = 0
        for row in reader:
            try:
                observed = datetime.fromisoformat(row[stamp].replace("Z", "+00:00"))
                day = (
                    observed.replace(tzinfo=observed.tzinfo or timezone.utc)
                    .astimezone(timezone.utc)
                    .date()
                )
                y, x = float(row[ykey]), float(row[xkey])
                if not (-90 <= y <= 90 and -180 <= x <= 180 and row[vessel].strip()):
                    raise ValueError()
                if start <= day <= end and distance(lat, lon, y, x) <= 25:
                    matched += 1
                    vessels.add(row[vessel].strip())
            except (TypeError, ValueError, AttributeError):
                invalid += 1
        return result(
            f"{len(vessels)} distinct vessels · {matched} matching reports within 25 km",
            [
                {
                    "vessels": len(vessels),
                    "reports": matched,
                    "invalid_rows": invalid,
                    "radius_km": 25,
                }
            ],
        )


@router.post("/api/ais-summary")
async def ais_summary(
    request: Request,
    start: date,
    end: date,
    lat: float = Query(ge=-85, le=85),
    lon: float = Query(ge=-180, le=180),
):
    if end < start or (end - start).days > 91:
        raise HTTPException(422, "Use a 1–92 day time window.")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 4 * 1024 * 1024:
            raise HTTPException(413, "CSV limit is 4 MiB.")
        data.extend(chunk)
    try:
        summary = await asyncio.to_thread(aggregate_ais, data, lat, lon, start, end)
    except (ValueError, csv.Error) as exc:
        raise HTTPException(
            422, "Invalid UTF-8 AIS CSV. Include timestamp, lat, lon and MMSI."
        ) from exc
    return {
        "source": "ais_import",
        "provider": "User-supplied AIS CSV",
        "status": "available",
        "time_basis": "UTC timestamps within the selected dates",
        "query": {"lat": lat, "lon": lon, "start": start, "end": end},
        "checked_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **summary,
    }
