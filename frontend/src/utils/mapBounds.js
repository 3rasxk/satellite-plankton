// Rectangular extent supplied in DMS by the project owner. Leaflet uses
// [latitude, longitude] pairs ordered southwest then northeast.
export const MAP_BOUNDS = [
  [12.06813056, 99.29500833],
  [13.92548889, 102.57761667],
]

/** Prevent zooming farther out than the full MAP_BOUNDS scan area. */
export function syncMinimumBoundsZoom(map, bounds = MAP_BOUNDS) {
  const minZoom = map.getBoundsZoom(bounds, false)
  map.setMinZoom(minZoom)

  if (map.getZoom() < minZoom) {
    map.setZoom(minZoom)
  }

  return minZoom
}
