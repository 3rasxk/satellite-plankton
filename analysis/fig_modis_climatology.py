"""Fig: MODIS chlor_a of the last 365 days against its own day-of-year climatology, ONE location.

Usage: python fig_modis_climatology.py [site_key]   (default thachin_mouth)
Data source: data/analysis/modis_<site>.csv (MODIS-Aqua chlor_a, ~4.6 km grid, 2002-present).
Limitations: coarse grid, clouds leave gaps (line broken where observations are > 45 days apart);
a reading against its own history, not a bloom detection.
"""
import sys
import numpy as np, pandas as pd
from common import DATA, G1, G2, LW, SITES, SIZE, plt, save, style

style()
k = sys.argv[1] if len(sys.argv) > 1 else "thachin_mouth"
label, c = SITES[k]
d = pd.read_csv(DATA / f"modis_{k}.csv", parse_dates=["date"])
d["doy"] = d["date"].dt.dayofyear
fig, ax = plt.subplots(figsize=SIZE)
q = d.groupby(d["doy"].clip(upper=364) // 15 * 15)["chlor_a"].median()
ax.plot(q.index + 7, q.values, "-.", color=G1, lw=LW, label="Median 2002–present")
last = d[d["date"] >= d["date"].max() - pd.Timedelta(days=365)].sort_values("doy")
xs, ys = [], []
for i, (x, y) in enumerate(zip(last["doy"], last["chlor_a"])):
    if i and x - xs[-1] > 45:
        xs.append(np.nan); ys.append(np.nan)
    xs.append(x); ys.append(y)
ax.plot(xs, ys, "-", color=G2, lw=LW, label="Last 365 days")
top = last.loc[last["chlor_a"].idxmax()]
ax.set_yscale("log")
ax.set_xlabel("Day of year (d)")
ax.set_ylabel("MODIS chlor_a (mg m$^{-3}$)")
ax.set_title(f"chlor_a at {label}: last 365 days vs median")
ax.legend(loc="upper left", frameon=True)
save(fig, "fig_modis_chlor_a_climatology")
