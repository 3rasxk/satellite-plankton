"""Fig: NDCI distribution of 200 m sea cells around ONE location, by distance zone.

Usage: python fig_ndci_hist_zone.py [site_key]   (default thachin_mouth)
Data source: data/analysis/ndci_cells_run6.csv (Sentinel-2 composite, run 6, newest scene 2026-10-07).
Zones: distance from the station, 0-5 km, 5-15 km, 15-30 km.
Limitations: optical index, not a concentration or risk level; cells with no valid pixel are absent;
river-mouth sediment can raise NDCI with no bloom.
"""
import sys
import numpy as np, pandas as pd
from common import DATA, G1, G2, G3, LW, SIZE, SITES, SITE_XY, plt, save, style

style()
k = sys.argv[1] if len(sys.argv) > 1 else "thachin_mouth"
la0, lo0 = SITE_XY[k]
d = pd.read_csv(DATA / "ndci_cells_run6.csv")
dist = np.hypot((d.lat - la0) * 111.2, (d.lng - lo0) * 111.2 * np.cos(np.radians(la0)))
zones = [("0–5 km", dist < 5, G1), ("5–15 km", (dist >= 5) & (dist < 15), G2), ("15–30 km", (dist >= 15) & (dist < 30), G3)]
fig, ax = plt.subplots(figsize=SIZE)
bins = np.linspace(-0.1, 0.25, 50); mid = (bins[:-1] + bins[1:]) / 2
for n, m, c in zones:
    v = d.ndci[m]
    h, _ = np.histogram(v, bins=bins, density=True)
    h = np.where(h > 0, h, np.nan)
    ax.plot(mid, h, "-", color=c, lw=LW, label=f"{n} (n={v.size:,}), median {v.median():.3f}")
ax.set_yscale("log")
ax.set_ylim(top=ax.get_ylim()[1] * 12)  # headroom so the legend (upper left) covers no data
ax.set_xlabel("NDCI (unitless)")
ax.set_ylabel("Probability density (1/NDCI)")
ax.set_title(f"NDCI of sea cells by distance from {SITES[k][0]}")
ax.legend(loc="upper left", frameon=True)
save(fig, "fig_ndci_hist_by_zone")
