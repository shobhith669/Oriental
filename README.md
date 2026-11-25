# OrbitWorks

An interactive observation atlas for renewable siting, construction history and environmental review. The default world map shows dated solar and wind detections in 1° grid cells. Zoom into Kutch to see individual installations. The Python server queries public providers for a user-selected location. The earlier Civic Brief demonstration remains available under **Illustrative portfolio**.

## Run on Windows

From an existing checkout in PowerShell, stop any running server with Ctrl+C and run:

```powershell
git pull --ff-only origin main
py -3.12 -m venv .venv312
.\.venv312\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-dev.txt
.\.venv312\Scripts\python.exe -m unittest -v
.\.venv312\Scripts\python.exe -m uvicorn server:create_app --factory --port 3000
```

Use 64-bit Python 3.12. If you already created .venv312, skip the venv command. Leave the server running and open [the local app](http://127.0.0.1:3000).

## Run on macOS or Linux

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m unittest -v
python -m uvicorn server:create_app --factory --port 3000
```

### Try the atlas

1. Use **World**, **India**, or **Kutch** to frame the map. Search the bundled Natural Earth city index or enter latitude, longitude to set the query point. Click **Kutch** for individual features. At 2024 Q2 the study rectangle intersects 88 solar footprints and 2,352 wind turbines. Move the quarter slider, toggle the technologies or pan the map. Counts use feature bounding boxes and area sums use whole solar footprints. Dates are model estimates of first detection; the first quarter includes existing installations.
2. Select a point, choose dates and click **Fetch observations**. Open **Choose datasets** to change the requests. The local Global Renewables Watch adapter summarizes archived detections within 25 km in Kutch and in the selected 1° cell elsewhere, by completed quarter, even offline. The default 31-day window ends five days ago to allow for publication delays. Modeled current weather, dated imagery and reference layers have independent time bases. Optional refresh runs every five minutes while the tab is visible.
3. Inspect acquisition times and quality, open a scene or show its tiles where supplied. Choose the VIIRS map layer and change its acquisition date to review night lights. A missed acquisition, cloud, absent grid mapping or blocked provider leaves a gap in the evidence.
4. Save two complete points for the same dates. Compare solar and wind resources and adjust the grid weight. Screening requires resource, land cover, terrain slope and grid distance. For eligible points the resource, slope and distance factors scale linearly between the group's minimum and maximum (constant factors score 0.5). The land proxy is 1 for bare ground, 0.7 for shrub/grassland, 0.4 for cropland, 0.3 for moss/lichen and 0.2 for tree cover. The screen excludes water, wetland, mangrove, snow and built-up classes. Solar defaults to weights of 40/25/20/15% for resource/slope/land/grid; wind uses 45/15/20/20%. A grid-weight change rescales the other weights proportionally. These are point-level survey assumptions. Grid capacity, rights, parcel area and protected boundaries require separate verification.
5. For a coastal case, import AIS CSV and inspect counts for the selected date range within 25 km. The server processes up to 4 MiB per request and returns aggregate results. It accepts latitude/longitude or LAT/LON, MMSI and timestamp or BaseDateTime. Timestamps without an offset use UTC. Input rows are discarded after the request.
6. **Export GeoJSON** downloads the visible historical features, selected quarter and extent, the query point with provider results and timestamps, and saved comparisons with score settings. Saved comparisons use browser local storage.

### Dataset coverage and limits

| Source | Actual operation and output |
|---|---|
| Sentinel-1, Sentinel-2 and Landsat | Query Microsoft Planetary Computer STAC by point and date. Inspect up to 12 recent matching scenes per collection, acquisition times, cloud metadata and provider imagery. For Landsat 8/9, sample the oldest and newest displayed pixel via the Data API. Scale Collection 2 surface reflectance, apply pixel QA/saturation and calculate NDVI. Water-classified pixels also get a red–green index. Colour change supports field follow-up; chemical identification requires sampling. |
| NASA POWER | Fetch daily solar irradiation and 50 m wind. Means use dates with valid paired observations. |
| ESA WorldCover | Read the 2021 10 m land-cover class at the point from Planetary Computer or a locally installed reference raster. |
| GHSL | Discover JRC settlement layers advertised by the public WMS. Select one for display. Use a local GHS-BUILT-S GeoTIFF for a numerical built-up surface per cell. |
| VIIRS | Query NASA CMR for VNP46A2 granules and view dated gap-filled Black Marble night lights via NASA GIBS. Brightness alone cannot establish a pollution event. |
| ISRO Bhuvan | For locations in India, inspect layer names advertised by Bhuvan WMS and overlay a selected layer. An installed thematic raster supplies a pixel value with its own legend. Layer availability and access vary. |
| OpenStreetMap | Request mapped substation nodes, ways and relations within 20 km using Overpass. Show up to 100 returned centres with distances. The nearest returned centre is a proximity measure. © OpenStreetMap contributors, ODbL. |
| AIS | Query Fintraffic Digitraffic's marine locations in Finnish waters (CC BY 4.0), aggregated within 25 km over the last 30 minutes. For India and other regions use an authorized AIS CSV. The application does not dispatch vehicles. |
| Public debris catalog | Summarize CelesTrak COSMOS 2251 debris element counts and epoch range. This global context is independent of the ground location and provides no collision prediction. |
| Supporting weather and elevation | Open-Meteo provides current modeled irradiance and 10 m wind, and Copernicus GLO-90 elevation for approximate slope from two 500 m baselines. A local projected DEM takes precedence. Open-Meteo public API use is subject to its terms. |

Local reference rasters go in `.local/rasters/` or a directory specified by `ORBITWORKS_RASTERS`. Use trusted, georeferenced single-band GeoTIFFs. Supported filenames are `worldcover.tif` (ESA 2021 class codes), `ghsl.tif` (GHS-BUILT-S, m² of built-up surface per cell), `bhuvan.tif` (thematic product with metadata tags TITLE, UNITS and EPOCH as available), and `dem.tif` (elevation in metres, north-up metric projected CRS). Sampling respects NoData and raster bounds. Include an EPOCH tag for dated GHSL measurements.

### Provenance and reproducibility

Construction history comes from Global Renewables Watch v1.0, Robinson et al., covering 2017 Q4–2024 Q2. The worldwide overview includes the spatially indexed records (86,340 solar footprints and 375,197 turbines) and aggregates bounding-box centres into 1° cells by first-detection quarter. Visible totals include each whole intersecting cell. Detailed feature bounds for Kutch are 68.0–71.5° E and 22.6–24.6° N. The importer transforms original Web Mercator polygons and turbine points into WGS84 and retains source feature IDs. Download both GeoPackages and run `python scripts/import_history.py solar_all_2024q2_v1.gpkg wind_all_2024q2_v1.gpkg` to rebuild the bundled asset layer. [Dataset and paper](https://github.com/microsoft/global-renewables-watch/releases/tag/v1.0)

The offline basemap uses Natural Earth public-domain land, roads, rivers and populated places. Leaflet 1.9.4 is bundled with its BSD license so working with the construction inventory does not require tile or JavaScript CDN access. [Natural Earth source](https://github.com/nvkelso/natural-earth-vector)

### API, persistence and access

- Interactive API reference at `/api/docs`. List integrations at `GET /api/sources`. Query `GET /api/observations/{source}?lat=23.99&lon=69.72&start=2024-03-01&end=2024-03-07`. Each result includes provider, time basis, check time, status and query. Empty coverage and provider failures have explicit states. Successful queries cache for five minutes; global debris results cache for two hours.
- Submit AIS CSV bytes with `POST /api/ais-summary` using the same query parameters. The historical portfolio demo, review log and API remain at `/pilot.html`, `/api/portfolio` and `/api/reviews/{record}`. SQLite defaults to `.local/reviews.sqlite3`; use `ORBITWORKS_DB` to override. The shared review pilot defaults to localhost. Public writable deployments need authentication and persistent storage.
- GitHub Pages can serve `main/docs` as a static atlas with the dated inventory, time slider, map layers and exports. Live backend queries, CSV analysis and review persistence require the Python process. The seven cases in the illustrative portfolio remain explicitly simulated.
- Restricted networks need outbound HTTPS to planetarycomputer.microsoft.com, power.larc.nasa.gov, api.open-meteo.com, overpass-api.de, cmr.earthdata.nasa.gov, gibs.earthdata.nasa.gov, bhuvan-vec1.nrsc.gov.in, jeodpp.jrc.ec.europa.eu, meri.digitraffic.fi, celestrak.org and tile.openstreetmap.org for the enabled sources. Each provider can rate-limit, restrict access, delay publication or return no data. The app reports these outcomes without substituting demo measurements.
