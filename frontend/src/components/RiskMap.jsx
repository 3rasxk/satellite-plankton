import { useEffect, useRef } from 'react'
import { MapContainer, Pane, TileLayer, ZoomControl, useMap } from 'react-leaflet'
import { MAP_BOUNDS, syncMinimumBoundsZoom } from '../utils/mapBounds.js'

const UPPER_GULF_CENTER = [13.1, 100.6]
const UPPER_GULF_ZOOM = 9

// OpenStreetMap — free, no API key, no watermark. Used for standard map
// and styled to pure-white monochrome in Risk Alert Map mode.
const TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

// Esri World Light Gray Canvas is the raster page's neutral reference
// map. Esri publishes the canvas as a base plus a reference-label service;
// both are one logical Light Map mode in the UI. The label pane stays above
// the scientific overlay so place names and administrative context remain
// legible in NDCI mode.
const LIGHT_MAP_BASE_URL =
  'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}'
const LIGHT_MAP_REFERENCE_URL =
  'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}'
const LIGHT_MAP_ATTRIBUTION =
  'Tiles &copy; <a href="https://www.esri.com/">Esri</a> &mdash; Sources: Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>, and the GIS User Community'

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
      map.setView(bounds[0], UPPER_GULF_ZOOM)
    } else {
      map.fitBounds(bounds, { padding: [60, 60] })
    }
    fitted.current = boundsKey
  }, [map, points])
  return null
}

export function LightMapLayers() {
  return (
    <>
      <TileLayer
        url={LIGHT_MAP_BASE_URL}
        attribution={LIGHT_MAP_ATTRIBUTION}
        maxNativeZoom={16}
        maxZoom={18}
      />
      <Pane name="light-map-reference" style={{ zIndex: 450, pointerEvents: 'none' }}>
        <TileLayer
          url={LIGHT_MAP_REFERENCE_URL}
          maxNativeZoom={16}
          maxZoom={18}
          pane="light-map-reference"
        />
      </Pane>
    </>
  )
}

export default function RiskMap({ fitPoints, mode = 'risk', children }) {
  return (
    <MapContainer
      className={`leaflet-map map-mode-${mode}`}
      center={UPPER_GULF_CENTER}
      zoom={UPPER_GULF_ZOOM}
      maxZoom={18}
      maxBounds={MAP_BOUNDS}
      maxBoundsViscosity={1}
      scrollWheelZoom
      attributionControl
      zoomControl={false}
    >
      <BoundsZoomLock />
      <ZoomControl position="topright" />
      {mode === 'raster' ? (
        <LightMapLayers />
      ) : (
        <TileLayer
          key={mode}
          url={mode === 'true_color' ? TRUE_COLOR_TILE_URL : TILE_URL}
          attribution={mode === 'true_color' ? TRUE_COLOR_ATTRIBUTION : TILE_ATTRIBUTION}
          maxNativeZoom={19}
          maxZoom={18}
        />
      )}
      <FitToPoints points={fitPoints} />
      {children}
    </MapContainer>
  )
}
