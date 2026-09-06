import { useEffect, useRef } from 'react'
import { MapContainer, TileLayer, ZoomControl, useMap } from 'react-leaflet'
import { MAP_BOUNDS, syncMinimumBoundsZoom } from '../utils/mapBounds.js'

// Centre and zoom for the whole Thai-side Gulf scan area (widened from
// the upper Gulf's [13.1, 100.6] / zoom 9 on 2026-09-06).
const GULF_CENTER = [10.05, 101.1]
const GULF_ZOOM = 7

// OpenStreetMap — free, no API key, no watermark. Used for standard map
// and styled to pure-white monochrome in Risk Alert Map mode.
const TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

// True-color satellite basemap for the "True Color (RGB)" view mode — this
// is a general-purpose Esri imagery basemap, NOT the app's own Sentinel-2
// pipeline output (that stays scoped to SatelliteImage.jsx's per-site
// buffer renders); it exists to give the map view mode a plausible
// satellite backdrop.
const TRUE_COLOR_TILE_URL =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
const TRUE_COLOR_ATTRIBUTION =
  'Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community'

function BoundsZoomLock() {
  const map = useMap()

  useEffect(() => {
    const syncZoom = () => syncMinimumBoundsZoom(map)
    syncZoom()
    map.on('resize', syncZoom)

    return () => map.off('resize', syncZoom)
  }, [map])

  return null
}

function FitToPoints({ points }) {
  const map = useMap()
  const fitted = useRef(null)
  useEffect(() => {
    const bounds = points?.length ? points.map((point) => [point.lat, point.lng]) : []
    if (bounds.length === 0) return
    // A newly completed scan can replace the old grid with a larger one.
    // Fit changed coordinates, but preserve the user's view during polling
    // when only readings/statuses changed on the same grid.
    const boundsKey = JSON.stringify(bounds)
    if (fitted.current === boundsKey) return
    if (bounds.length === 1) {
      map.setView(bounds[0], GULF_ZOOM)
    } else {
      map.fitBounds(bounds, { padding: [60, 60] })
    }
    fitted.current = boundsKey
  }, [map, points])
  return null
}

export default function RiskMap({ fitPoints, mode = 'risk', children }) {
  return (
    <MapContainer
      className={`leaflet-map map-mode-${mode}`}
      center={GULF_CENTER}
      zoom={GULF_ZOOM}
      maxZoom={18}
      maxBounds={MAP_BOUNDS}
      maxBoundsViscosity={1}
      scrollWheelZoom
      attributionControl
      zoomControl={false}
    >
      <BoundsZoomLock />
      <ZoomControl position="topright" />
      <TileLayer
        key={mode}
        url={mode === 'true_color' ? TRUE_COLOR_TILE_URL : TILE_URL}
        attribution={mode === 'true_color' ? TRUE_COLOR_ATTRIBUTION : TILE_ATTRIBUTION}
        maxNativeZoom={19}
        maxZoom={18}
      />
      <FitToPoints points={fitPoints} />
      {children}
    </MapContainer>
  )
}
