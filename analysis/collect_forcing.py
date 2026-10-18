"""Collect preliminary daily data for ONE location (default Tha Chin river mouth) into data/analysis/forcing_<site>.csv.

Data sources (Google Earth Engine, point extraction; raw sources untouched):
  - NDCI: Sentinel-2 point history from the TEST baseline artifact (backend/data/baselines/*/sites.json)
  - sst: MODIS-Aqua L3SMI sst (4.6 km)            - chlor_a: MODIS-Aqua L3SMI chlor_a (4.6 km)
  - rain_mm: CHIRPS daily precipitation (0.05 deg) - wind_u/v (m/s): NOAA CFSv2 (harmonized) 6-hourly 10 m wind, daily mean
Not collected: surface currents (HYCOM/CMEMS need credentials not set up here).
Quality screen: 6-hourly wind samples with |u| or |v| > 60 m/s are dropped (data glitch), not filled.
Limitations: coarse grids vs the 10 m NDCI pixel; cloud leaves gaps (empty cells, never filled);
this is exploratory input data for a forecasting experiment, not a validated forecast.
Run with backend/venv/bin/python (GEE authenticated).
"""
import csv, glob, json, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from src import _detection as b  # noqa: E402  (loads GEE config; first call below initializes Earth Engine)
import ee  # noqa: E402

SITE, LAT, LNG = "thachin_mouth", 13.42, 100.27
START = "2017-12-01"
today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

b.get_modis_chlorophyll_history(LAT, LNG)  # initializes Earth Engine
pt = ee.Geometry.Point([LNG, LAT])


def region(coll, bands, scale, start, end):
    rows = ee.ImageCollection(coll).select(bands).filterDate(start, end).getRegion(pt, scale).getInfo()
    head = rows[0]
    return [dict(zip(head, r)) for r in rows[1:]]


daily = defaultdict(dict)
for r in region(b.MODIS_COLLECTION_ID, [b.MODIS_SST_BAND, b.MODIS_CHLOR_A_BAND], b.MODIS_GRID_SCALE_M, START, today):
    d = datetime.fromtimestamp(r["time"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    for k, o in ((b.MODIS_SST_BAND, "sst"), (b.MODIS_CHLOR_A_BAND, "chlor_a")):
        if r.get(k) is not None:
            daily[d][o] = r[k]
# CHIRPS has no sea pixels: mean over a 12 km buffer (the project's own rainfall-proxy buffer), land pixels only.
buf = pt.buffer(12000)
for y0 in range(2017, datetime.now().year + 1):
    s0, e0 = (START if y0 == 2017 else f"{y0}-01-01"), min(f"{y0 + 1}-01-01", today)
    fc = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").select("precipitation").filterDate(s0, e0).map(
        lambda im: ee.Feature(None, {"t": im.date().format("YYYY-MM-dd"), "p": im.reduceRegion(ee.Reducer.mean(), buf, 5566).get("precipitation")}))
    for ft in ee.FeatureCollection(fc).getInfo()["features"]:
        if ft["properties"].get("p") is not None:
            daily[ft["properties"]["t"]]["rain_mm"] = ft["properties"]["p"]
U, V = "u-component_of_wind_height_above_ground", "v-component_of_wind_height_above_ground"
MAX_WIND_MS = 60.0
dropped = 0
acc = defaultdict(lambda: [[], []])
for y in range(2017, datetime.now().year + 1):
    s, e = f"{max(y, 2017)}-01-01" if y > 2017 else START, f"{y + 1}-01-01"
    for r in region("NOAA/CFSV2/FOR6H_HARMONIZED", [U, V], 20000, s, min(e, today)):
        d = datetime.fromtimestamp(r["time"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        # CFSv2 harmonized has glitch values (100-300 m/s) in some 6-hourly images; a surface wind above
        # MAX_WIND_MS is physically implausible here, so that 6-hourly sample is dropped (counted below), not repaired.
        if r.get(U) is not None and r.get(V) is not None:
            if abs(r[U]) > MAX_WIND_MS or abs(r[V]) > MAX_WIND_MS:
                dropped += 1
                continue
            acc[d][0].append(r[U]); acc[d][1].append(r[V])
for d, (u, v) in acc.items():
    daily[d]["wind_u"] = sum(u) / len(u); daily[d]["wind_v"] = sum(v) / len(v)
rows = json.load(open(glob.glob(str(ROOT / "backend/data/baselines/*/sites.json"))[0]))["rows"][SITE]
nd = defaultdict(list)
for r in rows:
    if r.get("ndci") is not None:
        nd[r["acquisition_date"]].append(r["ndci"])
for d, v in nd.items():
    daily[d]["ndci"] = sum(v) / len(v)

cols = ["ndci", "sst", "chlor_a", "rain_mm", "wind_u", "wind_v"]
out = ROOT / "data" / "analysis" / f"forcing_{SITE}.csv"
with open(out, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["date"] + cols)
    for d in sorted(daily):
        w.writerow([d] + [("%.5g" % daily[d][c]) if c in daily[d] else "" for c in cols])
print("wind samples dropped as implausible:", dropped)
print(out, {c: sum(1 for d in daily.values() if c in d) for c in cols}, len(daily))
