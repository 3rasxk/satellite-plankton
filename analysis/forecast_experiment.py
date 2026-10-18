"""EXPERIMENT (outside the shipped pipeline, not wired to the API): next-scene NDCI forecast at ONE location, no currents.

Usage: python forecast_experiment.py [site_key]   (default thachin_mouth; needs data/analysis/forcing_<site>.csv)
Data source: data/analysis/forcing_<site>.csv (Sentinel-2 NDCI, CHIRPS rain, CFSv2 wind; collect_forcing.py).
Task: from the NDCI at scene t_i and the rain/wind observed between t_i and t_{i+1} (a perfect-forcing
hindcast; a real forecast would use forecast weather), predict NDCI at the next scene t_{i+1}.
Models, all trained on scenes before 2025-01-01 and tested on 2025-01-01 onward:
  M0 persistence       x_hat = x_i
  M1 climatology       x_hat = seasonal median of the training NDCI (+-15 days of the target day of year)
  M2 physics (step 1)  anomaly = mean reversion + rain nutrient pulse + wind mixing, fitted by least squares
                       (no advection term: no currents available; a 1-D point cannot advect anyway)
  M3 hybrid (step 2)   M2 plus gradient boosting on M2's residual
Quality screen: NDCI scenes with |NDCI| > 0.35 (4 of 289, implausible on open water) are excluded; pairs more than
15 days apart are excluded. Limitations: ~100 train / ~50 test pairs from one point, cloud-limited, so any
difference between models is within noise unless the bootstrap interval says otherwise; NDCI is an optical index,
so this forecasts water colour, not a bloom; not a validated forecast.
"""
import sys
import numpy as np, pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from common import DATA

k = sys.argv[1] if len(sys.argv) > 1 else "thachin_mouth"
d = pd.read_csv(DATA / f"forcing_{k}.csv", parse_dates=["date"]).set_index("date")
wind = np.hypot(d.wind_u, d.wind_v)
sc = d.ndci.dropna(); sc = sc[sc.abs() <= 0.35]
dates = list(sc.index)
SPLIT = pd.Timestamp("2025-01-01")

rows = []
for a, b in zip(dates[:-1], dates[1:]):
    gap = (b - a).days
    if not 2 <= gap <= 15:
        continue
    win = slice(a + pd.Timedelta(days=1), b)
    r = d.rain_mm.loc[win]; w = wind.loc[win]
    if r.notna().sum() < gap * 0.6 or w.notna().sum() < gap * 0.6:
        continue
    rows.append(dict(t0=a, t1=b, gap=gap, x0=sc[a], y=sc[b], rain=r.sum(), wind=w.mean()))
P = pd.DataFrame(rows)
tr, te = P[P.t1 < SPLIT].copy(), P[P.t1 >= SPLIT].copy()
train_scenes = sc[sc.index < SPLIT]


def clim(day):  # seasonal median of training scenes within +-15 days of the day of year
    doy = train_scenes.index.dayofyear.values
    out = []
    for dd in np.atleast_1d(day):
        diff = np.abs((doy - dd + 183) % 365 - 183)
        out.append(np.median(train_scenes.values[diff <= 15]))
    return np.array(out)


for D in (tr, te):
    D["c0"] = clim(D.t0.dt.dayofyear.values); D["c1"] = clim(D.t1.dt.dayofyear.values)
wclim = tr.wind.mean()
Xp = lambda D: np.c_[D.x0 - D.c0, D.rain / 100.0, D.wind - wclim]  # physical anomaly features
beta, *_ = np.linalg.lstsq(Xp(tr), (tr.y - tr.c1).values, rcond=None)
phi, b_rain, b_wind = beta
for D in (tr, te):
    D["m0"] = D.x0
    D["m1"] = D.c1
    D["m2"] = D.c1 + Xp(D) @ beta
feat = lambda D: np.c_[D.x0, D.c1, D.rain, D.wind, D.gap, np.sin(2 * np.pi * D.t1.dt.dayofyear / 365), np.cos(2 * np.pi * D.t1.dt.dayofyear / 365)]
gb = GradientBoostingRegressor(n_estimators=100, max_depth=2, learning_rate=0.05, subsample=0.8, random_state=0)
gb.fit(feat(tr), (tr.y - tr.m2).values)
for D in (tr, te):
    D["m3"] = D.m2 + gb.predict(feat(D))

rng = np.random.default_rng(0)
res = []
for m, name in (("m0", "Persistence"), ("m1", "Climatology"), ("m2", "Physics (step 1)"), ("m3", "Hybrid (step 2)")):
    e = (te[m] - te.y).values
    boots = [np.sqrt(np.mean(e[i] ** 2)) for i in (rng.integers(0, len(e), len(e)) for _ in range(2000))]
    res.append(dict(model=name, key=m, rmse=np.sqrt(np.mean(e ** 2)), mae=np.mean(np.abs(e)), lo=np.percentile(boots, 2.5), hi=np.percentile(boots, 97.5), n_test=len(e)))
R = pd.DataFrame(res)
R["skill_vs_persistence"] = 1 - R.rmse / R.rmse[0]
R.to_csv(DATA / f"forecast_results_{k}.csv", index=False)
te.to_csv(DATA / f"forecast_test_predictions_{k}.csv", index=False)
print(f"pairs train/test: {len(tr)}/{len(te)}")
print(f"physics coefficients: mean-reversion phi={phi:.3f}, rain beta={b_rain:.4f} per 100 mm, wind beta={b_wind:.4f} per m/s")
print(R.round(4).to_string(index=False))
