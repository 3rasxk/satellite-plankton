"""Fig: NDCI map of the upper Gulf of Thailand (Sentinel-2, newest clear pixel within 180 days).

Zoom: study-area bounding box 12.50-13.61 N, 99.91-101.03 E.
Data source: backend/data/rasters/6/ndci_hires_full.png (Earth Engine render with the dashboard's NDCI ramp,
read only). Limitations: ~80 m pixels, mixed scene dates, grey = land / no valid pixel; optical index only.
"""
import numpy as np
from PIL import Image
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.cm import ScalarMappable
from common import ROOT, SIZE, plt, save, style

style()
S, W, N, E = 12.06813056, 99.29500833, 13.92548889, 102.57761667
im = np.array(Image.open(ROOT / "backend/data/rasters/6/ndci_hires_full.png").convert("RGBA"))
cmap = LinearSegmentedColormap.from_list("ndci", ["#0A1929", "#2E86AB", "#48C9A9", "#E8C547", "#D64545"])
fig, ax = plt.subplots(figsize=SIZE)
ax.set_facecolor("#e6e6e8"); ax.grid(False)
ax.imshow(im, extent=[W, E, S, N], aspect=1 / np.cos(np.radians(13)), interpolation="nearest")
# zoom to the study-area bounding box (data-pipeline/src/study_area.py polygon extent), not the whole map extent
BS, BW, BN, BE = 12.5047, 99.9136, 13.6148, 101.0260
ax.set_xlim(BW, BE); ax.set_ylim(BS, BN)
ax.set_xlabel("Longitude (°E)"); ax.set_ylabel("Latitude (°N)")
ax.set_title("Sentinel-2 NDCI, upper Gulf of Thailand")
cb = fig.colorbar(ScalarMappable(Normalize(-0.05, 0.15), cmap), ax=ax, fraction=0.03, pad=0.02)
cb.set_label("NDCI (unitless)")
save(fig, "fig_ndci_map")
