"use strict";
const el = (id) => document.getElementById(id);
const form = el("query"),
  fields = form.elements;
const connected = document.documentElement.dataset.mode === "connected";
const day = (offset) =>
  new Date(Date.now() + offset * 86400000).toISOString().slice(0, 10);
fields.start.value = day(-35);
fields.end.value = day(-5);
fields.start.max = fields.end.max = el("imageryDate").max = day(0);
el("imageryDate").value = day(-3);
const map = L.map("atlasmap", {
  preferCanvas: true,
  minZoom: 2,
  maxZoom: 18,
}).setView([23.65, 69.75], 8);
map.attributionControl.setPrefix("Leaflet");
map.createPane("baseTiles").style.zIndex = 250;
map.createPane("coast").style.zIndex = 210;
map.createPane("regional").style.zIndex = 220;
const assets = L.layerGroup().addTo(map),
  substations = L.layerGroup().addTo(map);
const locationDot = L.circleMarker([+fields.lat.value, +fields.lon.value], {
  radius: 8,
  color: "#fff",
  weight: 3,
  fillColor: "#b63847",
  fillOpacity: 1,
}).addTo(map);
let inventory = [],
  visible = [],
  sources = {},
  answers = {},
  active = null,
  revision = 0,
  base = null,
  extra = null,
  timer;
let saved = [];
try {
  saved = JSON.parse(
    localStorage.getItem("orbitworks-observations-v1") || "[]",
  );
  if (!Array.isArray(saved)) saved = [];
} catch {}
function node(tag, txt, cls) {
  const n = document.createElement(tag);
  n.textContent = txt ?? "";
  if (cls) n.className = cls;
  return n;
}
function link(label, url) {
  const a = node("a", label);
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "https:") {
      a.href = parsed.href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    }
  } catch {}
  return a;
}
async function json(url, options = {}) {
  const r = await fetch(url, {
    ...options,
    signal: AbortSignal.timeout(35000),
  });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}
function period(index) {
  const n = 2017 * 4 + 3 + Number(index);
  return Math.floor(n / 4) + " Q" + ((n % 4) + 1);
}
function updateExtent() {
  const bounds = map.getBounds();
  visible = [];
  let solar = 0,
    wind = 0,
    area = 0;
  for (const asset of inventory) {
    if (!assets.hasLayer(asset.layer) || !bounds.intersects(asset.bounds))
      continue;
    visible.push(asset.feature);
    if (asset.feature.properties.kind === "solar") {
      solar++;
      area += asset.feature.properties.area_ha || 0;
    } else wind++;
  }
  el("scount").textContent = solar.toLocaleString();
  el("wcount").textContent = wind.toLocaleString();
  el("footprint").textContent =
    area.toLocaleString(undefined, { maximumFractionDigits: 1 }) +
    " ha across intersecting solar footprints (whole feature areas).";
}
function history() {
  const cutoff = period(el("quarter").value);
  el("period").textContent = cutoff;
  for (const entry of inventory) {
    const p = entry.feature.properties;
    if (el(p.kind).checked && p.period && p.period <= cutoff) {
      if (!assets.hasLayer(entry.layer)) assets.addLayer(entry.layer);
    } else assets.removeLayer(entry.layer);
  }
  locationDot.bringToFront();
  updateExtent();
}
function setBase() {
  if (base) map.removeLayer(base);
  el("mapstatus").textContent = "";
  const key = el("basemap").value;
  if (key === "offline") {
    base = null;
    return;
  }
  if (key === "osm")
    base = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      pane: "baseTiles",
      attribution: "© OpenStreetMap contributors",
      maxZoom: 19,
    });
  else
    base = L.tileLayer.wms(
      "https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi",
      {
        pane: "baseTiles",
        layers: "VIIRS_SNPP_GapFilled_BRDF_Corrected_DayNightBand_Radiance",
        format: "image/png",
        transparent: true,
        time: el("imageryDate").value,
        attribution: "NASA GIBS / VIIRS",
      },
    );
  base.on("tileerror", () => {
    el("mapstatus").textContent =
      "Some imagery tiles are unavailable. The observation vectors remain visible.";
  });
  base.addTo(map);
}
function queryValues() {
  return {
    lat: Number(fields.lat.value),
    lon: Number(fields.lon.value),
    start: fields.start.value,
    end: fields.end.value,
  };
}
function invalidate() {
  revision++;
  active = null;
  answers = {};
  substations.clearLayers();
  el("reports").replaceChildren();
  if (extra) {
    map.removeLayer(extra);
    extra = null;
  }
  el("savepoint").disabled = true;
  el("run").disabled = !connected;
  el("feedback").textContent = connected
    ? "Fetch observations for the new selection."
    : "";
}
function selectPoint(lat, lon) {
  if (Math.abs(lat) > 85) return;
  lon = ((((lon + 180) % 360) + 360) % 360) - 180;
  fields.lat.value = lat.toFixed(5);
  fields.lon.value = lon.toFixed(5);
  locationDot.setLatLng([lat, lon]).bringToFront();
  invalidate();
}
map.on("click", (e) => selectPoint(e.latlng.lat, e.latlng.lng));
map.on("moveend", updateExtent);
el("reset").onclick = () =>
  map.fitBounds([
    [22.6, 68],
    [24.6, 71.5],
  ]);
for (const id of ["solar", "wind", "quarter"]) el(id).oninput = history;
el("basemap").onchange = el("imageryDate").onchange = setBase;
form.addEventListener("input", (e) => {
  if (e.target === el("auto")) return;
  invalidate();
  if (
    fields.lat.value &&
    fields.lon.value &&
    fields.lat.validity.valid &&
    fields.lon.validity.valid
  )
    locationDot.setLatLng([+fields.lat.value, +fields.lon.value]);
});
function addFeatures(report) {
  if (report.source !== "osm") return;
  substations.clearLayers();
  for (const point of report.points || []) {
    L.circleMarker([point.lat, point.lon], {
      radius: 5,
      color: "#863888",
      fillOpacity: 0.85,
    })
      .bindPopup(node("span", point.label + " · " + point.distance_km + " km"))
      .addTo(substations);
  }
}
function reportCard(report) {
  const card = node("article", "", "report");
  card.append(
    node(
      "span",
      {
        available: "Data available",
        unavailable: "Feed unavailable",
        no_data: "No usable data",
      }[report.status] || report.status,
      "status",
    ),
    node("h3", report.provider),
    node("p", report.summary),
    node("p", report.time_basis, "caption"),
  );
  if (report.wms && report.rows.length) {
    const select = node("select");
    select.setAttribute("aria-label", "Overlay " + report.provider);
    select.add(new Option("Select a map overlay", ""));
    for (const row of report.rows) select.add(new Option(row.title, row.layer));
    select.onchange = () => {
      if (extra) map.removeLayer(extra);
      if (!select.value) return;
      extra = L.tileLayer.wms(report.wms, {
        layers: select.value,
        format: "image/png",
        transparent: true,
        opacity: 0.7,
        attribution: report.provider,
      });
      extra.on("tileerror", () => {
        el("mapstatus").textContent =
          "Selected WMS layer failed to render in this view.";
      });
      extra.addTo(map);
    };
    card.append(select);
  } else if (report.rows?.length) {
    const details = node("details"),
      list = node("ol", "", "itemrows");
    details.append(
      node("summary", "Inspect records (" + report.rows.length + ")"),
    );
    for (const row of report.rows) {
      const item = node("li");
      for (const [name, value] of Object.entries(row)) {
        if (name === "tilejson_url") {
          const button = node("button", "Show scene on map", "quiet");
          button.type = "button";
          button.onclick = async () => {
            const token = revision;
            try {
              const tiles = await json(value);
              const url = tiles.tiles?.find((t) =>
                t.startsWith("https://planetarycomputer.microsoft.com/"),
              );
              if (!url) throw new Error();
              if (token !== revision) return;
              if (extra) map.removeLayer(extra);
              extra = L.tileLayer(url, {
                attribution:
                  "Microsoft Planetary Computer · " + report.provider,
                maxZoom: 19,
              }).addTo(map);
              extra.on("tileerror", () => {
                el("mapstatus").textContent =
                  "Some scene tiles are unavailable.";
              });
              map.setView(
                [active.lat, active.lon],
                Math.max(map.getZoom(), 10),
              );
              el("mapstatus").textContent =
                report.provider + " · " + row.acquired;
            } catch {
              if (token === revision)
                el("mapstatus").textContent =
                  "Scene tiles unavailable. Open the scene metadata for the source files.";
            }
          };
          item.append(button);
        } else if (name.endsWith("_url"))
          item.append(
            link(
              name === "preview_url" ? "View image" : "Scene metadata",
              value,
            ),
          );
        else
          item.append(node("div", name.replaceAll("_", " ") + " · " + value));
      }
      list.append(item);
    }
    details.append(list);
    card.append(details);
  }
  card.append(node("p", "Checked " + report.checked_utc, "caption"));
  if (report.source_url) card.append(link("Provider ↗", report.source_url));
  return card;
}
function showResults() {
  el("reports").replaceChildren(...Object.values(answers).map(reportCard));
}
function validQuery() {
  if (!form.reportValidity()) return false;
  const days =
    (Date.parse(fields.end.value) - Date.parse(fields.start.value)) / 86400000;
  if (days < 0 || days > 91) {
    el("feedback").textContent = "Choose a range of 1–92 days.";
    return false;
  }
  return true;
}
async function refresh(event) {
  event?.preventDefault();
  if (!connected || !validQuery()) return;
  const ids = [...el("choices").querySelectorAll(":checked")].map(
    (n) => n.value,
  );
  if (!ids.length) {
    el("feedback").textContent = "Select at least one dataset.";
    return;
  }
  invalidate();
  const token = revision,
    query = queryValues();
  active = query;
  el("feedback").textContent = "Fetching observations…";
  el("run").disabled = true;
  map.panTo([query.lat, query.lon]);
  let next = 0;
  async function worker() {
    while (next < ids.length && token === revision) {
      const id = ids[next++];
      let payload;
      try {
        payload = await json(
          "api/observations/" + id + "?" + new URLSearchParams(query),
        );
      } catch (e) {
        payload = {
          source: id,
          provider: sources[id].name,
          status: "unavailable",
          summary: e.message,
          rows: [],
          time_basis: sources[id].basis,
          checked_utc: new Date().toISOString(),
        };
      }
      if (token !== revision) return;
      answers[id] = payload;
      addFeatures(payload);
      showResults();
    }
  }
  await Promise.all(Array.from({ length: Math.min(4, ids.length) }, worker));
  if (token !== revision) return;
  const count = Object.values(answers).filter(
    (r) => r.status === "available",
  ).length;
  el("feedback").textContent =
    count + " of " + ids.length + " selected feeds returned data.";
  el("run").disabled = false;
  el("savepoint").disabled = !count;
}
for (const [id, checked] of [["allfeeds", true], ["nofeeds", false]]) {
  el(id).onclick = () => {
    for (const input of el("choices").querySelectorAll("input")) input.checked = checked;
    invalidate();
  };
}
form.onsubmit = refresh;
el("auto").onchange = () => {
  clearInterval(timer);
  if (el("auto").checked)
    timer = setInterval(() => {
      if (!document.hidden && !el("run").disabled) refresh();
    }, 300000);
};
el("analyze").onclick = async () => {
  if (!connected || !validQuery()) return;
  const file = el("aisfile").files[0];
  if (!file || file.size > 4194304) {
    el("feedback").textContent = "Select a CSV of up to 4 MiB.";
    return;
  }
  const token = revision,
    query = queryValues();
  try {
    const r = await json("api/ais-summary?" + new URLSearchParams(query), {
      method: "POST",
      headers: { "Content-Type": "text/csv" },
      body: file,
    });
    if (token !== revision) return;
    active = query;
    answers.ais_import = r;
    showResults();
    el("feedback").textContent = "AIS summary added to the export.";
  } catch (e) {
    if (token === revision)
      el("feedback").textContent =
        "AIS import failed (" +
        e.message +
        "). Check the required columns and date range.";
  }
};
function scores() {
  const isWind = el("rankmode").value === "Wind";
  const resource = isWind ? "wind" : "solar";
  const weights = isWind ? [0.45, 0.15, 0.2] : [0.4, 0.25, 0.2];
  const grid = Number(el("gridweight").value) / 100;
  const scale = (1 - grid) / weights.reduce((a, b) => a + b);
  const land = { 10: 0.2, 20: 0.7, 30: 0.7, 40: 0.4, 60: 1, 100: 0.3 };
  const groups = new Map(),
    result = new Map();
  for (const s of saved) {
    if ([50, 70, 80, 90, 95].includes(s.code)) {
      result.set(s, "Excluded");
      continue;
    }
    if (![s[resource], s.grid, s.slope, land[s.code]].every(Number.isFinite)) {
      result.set(s, "Incomplete");
      continue;
    }
    if (!groups.has(s.dates)) groups.set(s.dates, []);
    groups.get(s.dates).push(s);
  }
  for (const group of groups.values()) {
    const bounds = {};
    for (const key of [resource, "slope", "grid"]) {
      const values = group.map((s) => s[key]);
      bounds[key] = [Math.min(...values), Math.max(...values)];
    }
    const normalized = (s, key) => {
      const [lo, hi] = bounds[key];
      if (lo === hi) return 0.5;
      const n = (s[key] - lo) / (hi - lo);
      return key === resource ? n : 1 - n;
    };
    for (const s of group) {
      const score =
        scale *
          (weights[0] * normalized(s, resource) +
            weights[1] * normalized(s, "slope") +
            weights[2] * land[s.code]) +
        grid * normalized(s, "grid");
      result.set(s, group.length > 1 ? Math.round(100 * score) : "Needs peer");
    }
  }
  return result;
}
function comparison() {
  el("comparison").hidden = !saved.length;
  const table = node("table"),
    head = node("tr");
  const ranks = scores();
  el("gridpct").textContent = el("gridweight").value + "%";
  for (const name of [
    "Score / 100",
    "Location",
    "Dates",
    "Solar (kWh/m²/day)",
    "50 m wind (m/s)",
    "Grid (km)",
    "Cover",
    "Slope (°)",
  ])
    head.append(node("th", name));
  table.append(head);
  for (const s of [...saved].sort(
    (a, b) =>
      a.dates.localeCompare(b.dates) ||
      (Number(ranks.get(b)) || 0) - (Number(ranks.get(a)) || 0),
  )) {
    const tr = node("tr");
    for (const v of [
      ranks.get(s),
      s.coords,
      s.dates,
      s.solar,
      s.wind,
      s.grid,
      s.cover,
      s.slope,
    ])
      tr.append(node("td", v ?? "Unavailable"));
    table.append(tr);
  }
  el("comparetable").replaceChildren(table);
}
el("rankmode").onchange = () => {
  el("gridweight").value = el("rankmode").value === "Wind" ? 20 : 15;
  comparison();
};
el("gridweight").oninput = comparison;
el("savepoint").onclick = () => {
  if (!active) return;
  const point = {
    coords: active.lat + ", " + active.lon,
    dates: active.start + " → " + active.end,
    solar: answers.power?.metrics?.mean_solar_kwh_m2_day,
    wind: answers.power?.metrics?.mean_wind_50m_ms,
    grid: answers.osm?.points?.[0]?.distance_km,
    code: answers.worldcover?.rows?.[0]?.class,
    cover: answers.worldcover?.rows?.[0]?.land_cover,
    slope: answers.dem?.rows?.[0]?.slope_deg,
  };
  saved = saved.filter(
    (s) => s.coords !== point.coords || s.dates !== point.dates,
  );
  saved.push(point);
  saved = saved.slice(-30);
  try {
    localStorage.setItem("orbitworks-observations-v1", JSON.stringify(saved));
  } catch {}
  comparison();
};
el("clear").onclick = () => {
  saved = [];
  try {
    localStorage.removeItem("orbitworks-observations-v1");
  } catch {}
  comparison();
};
el("download").onclick = () => {
  const features = [...visible];
  if (active)
    features.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: [active.lon, active.lat] },
      properties: { query: active, results: answers },
    });
  const doc = {
    type: "FeatureCollection",
    features,
    comparison: saved.map((p) => ({ ...p, screening_score: scores().get(p) })),
    ranking: {
      resource: el("rankmode").value,
      grid_weight_percent: Number(el("gridweight").value),
    },
    quarter: period(el("quarter").value),
    extent: map.getBounds().toBBoxString(),
    source:
      "Robinson et al., Global Renewables Watch v1.0; provider attribution and observation dates in point results.",
  };
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(doc)], { type: "application/geo+json" }),
  );
  const a = node("a");
  a.href = url;
  a.download = "orbitworks-observations.geojson";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
async function start() {
  el("connection").textContent = connected ? "API connected" : "Static atlas";
  el("auto").disabled = !connected;
  el("analyze").disabled = !connected;
  if (!connected)
    el("feedback").textContent =
      "Run the Python app to query external feeds and summarize AIS files.";
  const coast = json("assets/geo/land.geojson").then((data) =>
    L.geoJSON(data, {
      pane: "coast",
      interactive: false,
      style: {
        color: "#a7bab7",
        weight: 1,
        fillColor: "#e4e8d9",
        fillOpacity: 1,
      },
    }).addTo(map),
  );
  const regional = json("assets/geo/kutch-base.geojson").then((data) => {
    L.geoJSON(data, {
      pane: "regional",
      interactive: false,
      style: (f) => {
        const kind = f.properties.kind;
        if (kind === "land")
          return { stroke: false, fillColor: "#ecebdd", fillOpacity: 1 };
        return {
          color: kind === "roads" ? "#c3ab91" : "#93bfc9",
          weight: kind === "roads" ? 1.6 : 1,
          opacity: 0.9,
        };
      },
      pointToLayer: (feature, pt) =>
        L.circleMarker(pt, {
          pane: "regional",
          interactive: false,
          color: "#6b756e",
          radius: 2,
          weight: 1,
        }).bindTooltip(node("span", feature.properties.name), {
          permanent: true,
          direction: "top",
          className: "place-name",
        }),
    }).addTo(map);
  });
  const catalog = json("assets/geo/kutch.geojson").then((data) => {
    inventory = data.features.map((feature) => {
      const p = feature.properties;
      const layer = L.geoJSON(feature, {
        bubblingMouseEvents: false,
        style:
          p.kind === "wind"
            ? { color: "#2945aa", weight: 1, fillOpacity: 0.7 }
            : { color: "#b55b1b", weight: 1.6, fillOpacity: 0.45 },
        pointToLayer: (_, pt) =>
          L.circleMarker(pt, {
            radius: 3,
            color: "#2945aa",
            weight: 1,
            fillOpacity: 0.8,
            bubblingMouseEvents: false,
          }),
      });
      layer.bindPopup(
        node(
          "span",
          (p.kind === "wind" ? "Wind turbine" : "Solar footprint") +
            " · detected by " +
            p.period,
        ),
      );
      layer.on("click", (e) => selectPoint(e.latlng.lat, e.latlng.lng));
      return { feature, layer, bounds: layer.getBounds() };
    });
    history();
    el("download").disabled = false;
  });
  const registry = json(
    connected ? "api/sources" : "assets/geo/sources.json",
  ).then((data) => {
    sources = data;
    for (const [id, meta] of Object.entries(data)) {
      const input = node("input");
      input.type = "checkbox";
      input.value = id;
      input.checked = [
        "history",
        "power",
        "weather",
        "dem",
        "osm",
        "sentinel2",
        "worldcover",
      ].includes(id);
      const label = node("label");
      label.append(input, document.createTextNode(" " + meta.name));
      el("choices").append(label);
    }
    el("run").disabled = !connected;
  });
  const checks = await Promise.allSettled([coast, regional, catalog, registry]);
  if (checks.some((r) => r.status === "rejected"))
    el("mapstatus").textContent =
      "Some atlas files failed to load. Reload to retry.";
  comparison();
}
start();
