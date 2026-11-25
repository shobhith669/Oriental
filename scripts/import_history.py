"""Extract Kutch-area detections from the two Global Renewables Watch v1.0 GeoPackages."""

import argparse
import json
import math
import sqlite3
import struct
from pathlib import Path

R = 6378137
BOUNDS = (68.0, 22.6, 71.5, 24.6)


def xy(lon, lat):
    return R * math.radians(lon), R * math.asinh(math.tan(math.radians(lat)))


def coordinates(x, y):
    return [
        round(math.degrees(x / R), 6),
        round(math.degrees(math.atan(math.sinh(y / R))), 6),
    ]


def geometry(blob):
    envelope = (blob[3] >> 1) & 7
    offset = 8 + (0, 32, 48, 48, 64)[envelope]
    order = "<" if blob[offset] == 1 else ">"
    (kind,) = struct.unpack_from(order + "I", blob, offset + 1)
    offset += 5
    if kind == 1:
        return {
            "type": "Point",
            "coordinates": coordinates(*struct.unpack_from(order + "dd", blob, offset)),
        }
    if kind != 3:
        raise ValueError(f"Unsupported geometry {kind}")
    (rings,) = struct.unpack_from(order + "I", blob, offset)
    offset += 4
    paths = []
    for _ in range(rings):
        (count,) = struct.unpack_from(order + "I", blob, offset)
        offset += 4
        paths.append(
            [
                coordinates(*pt)
                for pt in struct.iter_unpack(
                    order + "dd", blob[offset : offset + 16 * count]
                )
            ]
        )
        offset += 16 * count
    return {"type": "Polygon", "coordinates": paths}


def extract(path, kind):
    table = kind + "_all_2024q2"
    x0, y0 = xy(*BOUNDS[:2])
    x1, y1 = xy(*BOUNDS[2:])
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        for row in db.execute(
            f"SELECT t.* FROM {table} t JOIN rtree_{table}_geom r ON r.id=t.fid "
            "WHERE r.maxx>=? AND r.minx<=? AND r.maxy>=? AND r.miny<=? ORDER BY t.fid",
            (x0, x1, y0, y1),
        ):
            year, quarter = row["construction_year"], row["construction_quarter"]
            period = (
                f"{int(year)} Q{int(quarter)}"
                if year and quarter in (1, 2, 3, 4)
                else None
            )
            yield {
                "type": "Feature",
                "id": f"{kind}-{row['fid']}",
                "geometry": geometry(row["geom"]),
                "properties": {
                    "kind": kind,
                    "period": period,
                    "area_ha": round(row["area"] / 10000, 2)
                    if kind == "solar" and row["area"]
                    else None,
                },
            }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("solar", type=Path)
    p.add_argument("wind", type=Path)
    args = p.parse_args()
    features = [*extract(args.solar, "solar"), *extract(args.wind, "wind")]
    output = Path(__file__).resolve().parents[1] / "docs/assets/geo/kutch.geojson"
    output.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": features}, separators=(",", ":")
        ),
        encoding="utf-8",
    )
