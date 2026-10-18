"""Fig: precision / recall / F1 of the orphaned RF+XGBoost experiment (NOT part of the shipped pipeline).

Data source: data/analysis/ml_experimental_metrics.csv (backend/models/ensemble_metadata.json).
Limitations: the training file and its label source are not in this repository, so these
numbers are not evidence of bloom detection; the models are not used by the API or dashboard.
"""
import numpy as np, pandas as pd
from common import DATA, G1, G2, G3, SIZE, plt, save, style

style()
d = pd.read_csv(DATA / "ml_experimental_metrics.csv")
short = ["XGBoost", "Random Forest", "Ensemble"]
fig, ax = plt.subplots(figsize=SIZE)
x = np.arange(len(d)); w = 0.26
for i, (col, c) in enumerate((("precision", G1), ("recall", G2), ("f1", G3))):
    ax.bar(x + (i - 1) * w, d[col], w, color=c, label=col.upper() if col == "f1" else col.capitalize())
ax.set_xticks(x, short)
ax.set_ylim(0, 1.05)
ax.set_xlabel("Model (experimental, unused)")
ax.set_ylabel("Score (unitless)")
ax.set_title("Experimental RF/XGBoost scores, unverified labels")
ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.22), frameon=True)
ax.grid(axis="x", visible=False)
save(fig, "fig_ml_experimental_metrics")
