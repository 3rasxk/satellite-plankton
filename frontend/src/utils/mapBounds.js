// Bounding box of the scan area (data-pipeline/src/study_area.py's
// STUDY_AREA_POLYGON_LATLNG), plus a small margin so the outermost grid
// pins are not flush against the viewport edge. Leaflet uses
// [latitude, longitude] pairs ordered southwest then northeast.
//
// Widened 2026-09-06 with the study area itself, from the upper-Gulf
// rectangle the project owner originally supplied in DMS
// ([[12.06813056, 99.29500833], [13.92548889, 102.57761667]]) to the
// whole Thai side of the Gulf. Keep this in step with the polygon: a
// tighter box would put scanned points outside the pannable area.
export const MAP_BOUNDS = [
  [6.30, 99.00],
  [13.80, 103.20],
]

/** Allow the whole study area to fit on both wide and narrow screens. */
export function syncMinimumBoundsZoom(map, bounds = MAP_BOUNDS) {
  // Leaflet clamps getBoundsZoom to the existing minimum. Clear it first
  // so a resize can permit a wider view than the previous viewport did.
  map.setMinZoom(0)
  const minZoom = map.getBoundsZoom(bounds, false)
  map.setMinZoom(minZoom)

  if (map.getZoom() < minZoom) {
    map.setZoom(minZoom)
  }

  return minZoom
}
