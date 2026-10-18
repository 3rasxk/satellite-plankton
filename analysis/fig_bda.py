"""Figs: 2BDA and 3BDA maps and distance-zone histograms (Sentinel-2, 200 m cells, run 6, newest scene 2026-10-07).

Usage: python fig_bda.py [site_key]   (histogram zones around this station; default thachin_mouth)
Data source: data/analysis/ndci_cells_run6.csv (columns bda2, bda3; one value per 200 m cell, cloud/land cells absent).
  2BDA = B5/B4 (red-edge / red);  3BDA = (1/B4 - 1/B5) * B6.
Limitations: optical indices, not concentrations or risk levels; the colour scale is clipped to the 2nd-98th percentile
(a few cells reach 78 for 2BDA and 154 for 3BDA, likely non-water or near-zero red); no validated baseline exists, so
no value is "high" or "low" in a bloom sense; small or dispersed blooms may be missed.
Outputs: fig_bda2_map, fig_bda3_map, fig_bda2_hist_by_zone, fig_bda3_hist_by_zone (PNG 300 dpi + PDF).
"""
import sys
import numpy as np, pandas as pd
from common import DATA, G1, G2, G3, LW, SIZE, SITES, SITE_XY, plt, save, style

style()
k = sys.argv[1] if len(sys.argv) > 1 else "thachin_mouth"
la0, lo0 = SITE_XY[k]
d = pd.read_csv(DATA / "ndci_cells_run6.csv")
INDEX = {"bda2": ("2BDA (B5/B4, unitless)", "2BDA"), "bda3": ("3BDA ((1/B4 − 1/B5)·B6, unitless)", "3BDA")}
BS, BW, BN, BE = 12.5047, 99.9136, 13.6148, 101.0260  # study-area bounding box
dl = 0.0017966  # cell size (deg), from the run's overlay.json
dist = np.hypot((d.lat - la0) * 111.2, (d.lng - lo0) * 111.2 * np.cos(np.radians(la0)))
zones = [("0–5 km", dist < 5, G1), ("5–15 km", (dist >= 5) & (dist < 15), G2), ("15–30 km", (dist >= 15) & (dist < 30), G3)]

for col, (xlabel, name) in INDEX.items():
    # map: rasterise the cells onto their 200 m grid
    ny, nx = int(round((BN - BS) / dl)) + 1, int(round((BE - BW) / dl)) + 1
    grid = np.full((ny, nx), np.nan)
    iy = np.round((BN - d.lat.values) / dl).astype(int); ix = np.round((d.lng.values - BW) / dl).astype(int)
    ok = (iy >= 0) & (iy < ny) & (ix >= 0) & (ix < nx)
    grid[iy[ok], ix[ok]] = d[col].values[ok]
    lo, hi = np.nanpercentile(d[col], [2, 98])
    cmap = plt.get_cmap("viridis").with_extremes(bad="#e6e6e8")
    fig, ax = plt.subplots(figsize=SIZE)
    ax.grid(False)
    im = ax.imshow(np.ma.masked_invalid(grid), extent=[BW, BE, BS, BN], aspect=1 / np.cos(np.radians(13)), cmap=cmap, vmin=lo, vmax=hi, interpolation="nearest")
    ax.set_xlabel("Longitude (°E)"); ax.set_ylabel("Latitude (°N)")
    ax.set_title(f"Sentinel-2 {name}, upper Gulf of Thailand")
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02); cb.set_label(f"{name} (unitless, 2–98th percentile)")
    save(fig, f"fig_{col}_map")

    # histogram by distance zone (log y)
    fig, ax = plt.subplots(figsize=SIZE)
    bins = np.linspace(lo, hi, 50); mid = (bins[:-1] + bins[1:]) / 2
    for n, m, c in zones:
        v = d[col][m]
        h, _ = np.histogram(v, bins=bins, density=True)
        h = np.where(h > 0, h, np.nan)
        ax.plot(mid, h, "-", color=c, lw=LW, label=f"{n} (n={v.size:,}), median {v.median():.3f}")
    ax.set_yscale("log")
    ax.set_ylim(top=ax.get_ylim()[1] * 12)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(f"Probability density (1/{name})")
    ax.set_title(f"{name} of sea cells by distance from {SITES[k][0]}")
    ax.legend(loc="upper left", frameon=True)
    save(fig, f"fig_{col}_hist_by_zone")
