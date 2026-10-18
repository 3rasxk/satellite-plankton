"""Snapshot the data the paper figures use into data/analysis/*.csv (raw sources untouched).

Data source: GET /timeseries on the running backend (MODIS-Aqua chlor_a), the
stored raster run's cells.npz, and the TEST baseline artifact scored with the
project's own assess_site. Run with backend/venv/bin/python, backend on :8000.
Limitations: satellite readings only; the TEST z is provisional and uncalibrated.
"""
import glob, json, sys, urllib.request
from pathlib import Path
import csv
import numpy as np


def write(path, header, rows):
    with open(path, 'w', newline='') as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "analysis"; OUT.mkdir(parents=True, exist_ok=True)
RUN = 6
MODIS = {"thachin_mouth": (13.42, 100.27), "chaophraya_mouth": (13.4, 100.58), "chaam": (12.78, 100.04)}

for k, (la, lo) in MODIS.items():
    with urllib.request.urlopen(f"http://localhost:8000/timeseries?lat={la}&lng={lo}", timeout=300) as r:
        pts = json.load(r)["points"]
    write(OUT / f"modis_{k}.csv", ["date", "chlor_a"], [(p["date"], p["chlor_a"]) for p in pts if p.get("chlor_a") is not None])

z = np.load(ROOT / f"backend/data/rasters/{RUN}/cells.npz")
ok = np.isfinite(z["ndci"])
write(OUT / f"ndci_cells_run{RUN}.csv", ["lat", "lng", "ndci", "bda2", "bda3"], zip(np.round(z["lat"][ok], 5), np.round(z["lng"][ok], 5), np.round(z["ndci"][ok], 5), np.round(z["bda2"][ok], 5), np.round(z["bda3"][ok], 5)))

sys.path.insert(0, str(ROOT / "backend"))
from src import _detection as b  # noqa: E402
man = json.load(open(glob.glob(str(ROOT / "backend/data/baselines/*/manifest.json"))[0]))
rows = json.load(open(glob.glob(str(ROOT / "backend/data/baselines/*/sites.json"))[0]))["rows"]
out = []
for loc, rs in rows.items():
    byd = {}
    for r in rs:
        if r.get("ndci") is not None:
            byd.setdefault(r["acquisition_date"], []).append(r["ndci"])
    for dt in sorted(byd)[-120:]:
        v = sum(byd[dt]) / len(byd[dt])
        a = b.baseline_logic.assess_site(rs, location_id=loc, current_ndci=v, actual_date=dt, target_date=dt,
                                         preprocessing_signature=man["preprocessing_signature"])
        out.append({"site": loc, "date": dt, "ndci": v, "robust_z": a.get("signal_robust_z", a.get("robust_z"))})
write(OUT / "test_robust_z.csv", ["site", "date", "ndci", "robust_z"], [(o["site"], o["date"], o["ndci"], o["robust_z"]) for o in out])

meta = json.load(open(ROOT / "backend/models/ensemble_metadata.json"))["performance"]
write(OUT / "ml_experimental_metrics.csv", ["model", "precision", "recall", "f1"], [(v["model_name"], v["precision_class_1"], v["recall_class_1"], v["f1_class_1"]) for v in meta.values()])
print("ok")
