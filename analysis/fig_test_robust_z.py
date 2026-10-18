"""Fig: TEST baseline seasonal robust z of NDCI at ONE station (latest 120 scene dates).

Usage: python fig_test_robust_z.py [site_key]   (default thachin_mouth)
Data source: data/analysis/test_robust_z.csv (TEST baseline artifact + detection assess_site).
Limitations: TEST = provisional, uncalibrated, not a validated detector; no risk_level.
Sediment or shallow bottom can raise NDCI with no bloom. Line broken where scenes are > 45 days apart.
"""
import sys
import numpy as np, pandas as pd
from common import DATA, LW, REF, SITES, SIZE, plt, save, style

style()
k = sys.argv[1] if len(sys.argv) > 1 else "thachin_mouth"
label, c = SITES[k]
d = pd.read_csv(DATA / "test_robust_z.csv", parse_dates=["date"])
s = d[d.site == k].sort_values("date").reset_index(drop=True)
xs, ys = [], []
for i, r in s.iterrows():
    if i and (r.date - xs[-1]).days > 45:
        xs.append(pd.NaT); ys.append(np.nan)
    xs.append(r.date); ys.append(r.robust_z)
fig, ax = plt.subplots(figsize=SIZE)
ax.plot(pd.DatetimeIndex(xs), ys, "-", color=c, lw=LW, label=f"{label}, robust z of NDCI")
top = s.loc[s.robust_z.idxmax()]
ax.set_yscale("symlog", linthresh=1)  # linear within |z| < 1 (z can be negative), log beyond
ax.set_yticks([-10, -3, -1, 0, 1, 3, 10, 30]); ax.set_yticklabels(["−10", "−3", "−1", "0", "1", "3", "10", "30"])
for v in (2, 3):
    ax.axhline(v, ls="--", color=REF, lw=1.0)
ax.annotate("z = 3 (provisional)", (s.date.min(), 3), xytext=(2, 3), textcoords="offset points", color=REF, fontsize=9)
ax.set_xlabel("Scene date (UTC)")
ax.set_ylabel("Robust z of NDCI (σ, symlog)")
ax.set_title(f"TEST baseline z at {label}: provisional, uncalibrated")
ax.legend(loc="upper left", frameon=True)
ax.tick_params(axis="x", rotation=20)
save(fig, "fig_test_baseline_robust_z")
