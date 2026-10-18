"""Shared paper-figure style (matches the example figure): 6x4 in, matplotlib default colours, full frame, no grid, framed legend.

Data source: the CSVs in data/analysis/ (written by analysis/export_data.py).
Limitations: every figure is an optical-index / chlor_a reading at satellite
pixel resolution; none is a validated bloom detection or forecast.
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "analysis"
OUT = ROOT / "data" / "figures" / "paper"
SIZE = (6, 4)

# matplotlib default tab10 palette (the example-figure style); one colour per line within a figure.
G1, G2, G3, G4, REF = "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#7f7f7f"
LW = 1.5
# line style separates sub-groups (solid = observed data, dashed = estimate, dash-dot = climatology median)
SITES = {  # key: (label, colour)
    "thachin_mouth": ("Tha Chin", G1),
    "chaophraya_mouth": ("Chao Phraya", G2),
    "chaam": ("Cha-am", G3),
}
SITE_XY = {"thachin_mouth": (13.42, 100.27), "chaophraya_mouth": (13.4, 100.58), "chaam": (12.78, 100.04)}  # (lat, lng)
REGIONS = {  # station group -> (label, colour, member keys)
    "river": ("River mouths", G1, ("thachin_mouth", "chaophraya_mouth", "bangpakong_mouth")),
    "east": ("East coast", G2, ("bangsaen", "siracha", "pattaya")),
    "west": ("West coast", G3, ("chaam",)),
}


def style():
    """Example-figure style: matplotlib defaults, full box frame, no grid, framed legend (placed by each script)."""
    plt.rcdefaults()
    plt.rcParams.update({"font.size": 10, "axes.grid": False, "lines.linewidth": LW, "savefig.bbox": "tight", "figure.dpi": 100})


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=300)
    fig.savefig(OUT / f"{name}.pdf")
    plt.close(fig)
