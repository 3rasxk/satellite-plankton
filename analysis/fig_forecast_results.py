"""Figs: next-scene NDCI forecast experiment at ONE location (see forecast_experiment.py), log-scaled axes.

Usage: python fig_forecast_results.py [site_key]   (default thachin_mouth)
Data source: data/analysis/forecast_test_predictions_<site>.csv and forecast_results_<site>.csv.
Limitations: ~53 test pairs from one point; differences between models are inside the bootstrap interval;
NDCI is an optical index; not a validated forecast. Experimental, outside the shipped pipeline.
"""
import sys
import numpy as np, pandas as pd
from common import DATA, G1, G2, G3, LW, REF, SITES, SIZE, plt, save, style

style()
k = sys.argv[1] if len(sys.argv) > 1 else "thachin_mouth"
label = SITES[k][0]
T = pd.read_csv(DATA / f"forecast_test_predictions_{k}.csv", parse_dates=["t0", "t1"]).sort_values("t1")
R = pd.read_csv(DATA / f"forecast_results_{k}.csv")

fig, ax = plt.subplots(figsize=SIZE)
ax.plot(T.t1, T.y, "-", color=G1, lw=LW, label="Ground truth (observed NDCI)")
ax.plot(T.t1, T.m3, "--", color=G2, lw=LW, label="Hybrid (step 2) forecast")
ax.set_yscale("symlog", linthresh=0.05)  # NDCI can be negative: linear within |NDCI| < 0.05, log beyond
ax.set_yticks([-0.2, -0.1, -0.05, 0, 0.05, 0.1, 0.2, 0.4]); ax.set_yticklabels(["−0.2", "−0.1", "−0.05", "0", "0.05", "0.1", "0.2", "0.4"])
ax.set_ylim(-0.15, 2)  # headroom so the legend (upper left) covers no data
top = T.loc[T.y.idxmax()]
ax.set_xlabel("Scene date (UTC)")
ax.set_ylabel("NDCI at next scene (unitless, symlog)")
ax.set_title(f"Next-scene NDCI at {label}, test period (hybrid, experimental)")
ax.legend(loc="upper left", frameon=True)
ax.tick_params(axis="x", rotation=20)
save(fig, "fig_forecast_test_timeseries")

fig, ax = plt.subplots(figsize=SIZE)
cols = {"m0": REF, "m1": G1, "m2": G2, "m3": G3}
x = np.arange(len(R))
for i, r in R.iterrows():
    ax.errorbar(i, r.rmse, yerr=[[r.rmse - r.lo], [r.hi - r.rmse]], fmt="o", color=cols[r.key], ms=7, lw=LW, capsize=4)
ax.set_yscale("log")
ax.set_xticks(x, ["Persistence", "Climatology", "Physics\n(step 1)", "Hybrid\n(step 2)"])
ax.set_xlim(-0.5, len(R) - 0.5)
ax.grid(axis="x", visible=False)
ax.set_xlabel("Model")
ax.set_ylabel("RMSE of next-scene NDCI (unitless)")
ax.set_title(f"Forecast error at {label}: point = RMSE, bar = 95% bootstrap")
save(fig, "fig_forecast_rmse")

# pure log axis: absolute forecast error of the hybrid against ground truth (always > 0, so log is valid)
fig, ax = plt.subplots(figsize=SIZE)
err = (T.m3 - T.y).abs().clip(lower=1e-4)
ax.plot(T.t1, err, "-", color=G2, lw=LW, label="|Hybrid − ground truth|")
ax.axhline(0.05, ls="--", color=REF, lw=1.0, label="±0.05 tolerance")
ax.set_yscale("log")
ax.set_ylim(top=err.max() * 8)
ax.set_xlabel("Scene date (UTC)")
ax.set_ylabel("Absolute error in NDCI (unitless, log)")
ax.set_title(f"Hybrid forecast error at {label} (log scale, experimental)")
ax.legend(loc="upper left")
ax.tick_params(axis="x", rotation=20)
save(fig, "fig_forecast_abs_error_log")
