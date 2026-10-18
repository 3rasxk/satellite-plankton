"""Fig: preliminary daily data collected at ONE location (inputs for a forecasting experiment).

Usage: python fig_forcing_overview.py [site_key]   (default thachin_mouth)
Data source: data/analysis/forcing_<site>.csv (collect_forcing.py): Sentinel-2 NDCI, MODIS-Aqua sst,
CHIRPS rain (12 km buffer, 7-day sum), CFSv2 10 m wind speed (7-day mean).
Limitations: gaps are real (cloud) and stay gaps; lines break where observations are > 45 days apart;
grids are far coarser than the 10 m NDCI pixel; no currents collected. Exploratory, not a forecast.
"""
import sys
import numpy as np, pandas as pd
from matplotlib.ticker import FuncFormatter
from common import DATA, G1, G2, G3, G4, LW, SITES, plt, save, style

style()
k = sys.argv[1] if len(sys.argv) > 1 else "thachin_mouth"
d = pd.read_csv(DATA / f"forcing_{k}.csv", parse_dates=["date"]).set_index("date")
full = d.reindex(pd.date_range(d.index.min(), d.index.max()))
full["rain7"] = full["rain_mm"].rolling(7, min_periods=5).sum()
full["wind7"] = np.hypot(full["wind_u"], full["wind_v"]).rolling(7, min_periods=5).mean()


def broken(s, gap=45):
    s = s.dropna(); x, y = [], []
    for t, v in s.items():
        if x and (t - x[-1]).days > gap:
            x.append(pd.NaT); y.append(np.nan)
        x.append(t); y.append(v)
    return x, y


panels = [("ndci", "NDCI", G1), ("sst", "SST (°C)", G2), ("rain7", "Rain (mm)", G3), ("wind7", "Wind (m/s)", G4)]
fig, axs = plt.subplots(4, 1, figsize=(6, 6), sharex=True)
for ax, (col, yl, c), cap in zip(axs, panels, "abcd"):
    ax.text(0.5, -0.2 if cap != "d" else -0.55, f"({cap})", transform=ax.transAxes, ha="center", va="top")
    x, y = broken(full[col])
    ax.plot(pd.DatetimeIndex(x), y, "-", color=c, lw=LW)
    ax.set_ylabel(yl, fontsize=9)
    if col in ("ndci", "rain7"):  # can be <= 0: symlog (linear near zero, log beyond)
        ax.set_yscale("symlog", linthresh=0.1 if col == "ndci" else 1)
    else:
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        ax.yaxis.set_minor_formatter(FuncFormatter(lambda v, _: ""))
        ax.set_yticks([26, 28, 30, 32, 34, 36] if col == "sst" else [2, 3, 4, 6, 8])
axs[0].set_title(f"Preliminary daily data at {SITES[k][0]} (NDCI, rain: symlog; SST, wind: log; 7-day rain sum / wind mean)", fontsize=8)
axs[-1].set_xlabel("Date (UTC)")
fig.subplots_adjust(hspace=0.6, left=0.17)
fig.align_ylabels(axs)
save(fig, "fig_forcing_overview")
