import { useEffect } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer, ZoomControl, useMap } from 'react-leaflet'
import { MAP_BOUNDS, syncMinimumBoundsZoom } from '../utils/mapBounds.js'
import NdciRasterOverlay from './NdciRasterOverlay.jsx'
import WatchSitePopup from './WatchSitePopup.jsx'
import { canRenderWatchTiles, getVisibleSiteAlerts } from '../utils/watchOverlay.js'

// CartoDB Positron — light, muted basemap for the Apple-style light theme
// (docs/FRONTEND_PLAN.md §4). Same tile scheme/attribution as the old
// dark_all basemap, just the light_all variant.
const TILE_URL = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'

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

function ScanBoundsView() {
  const map = useMap()

  useEffect(() => {
    const fitScanBounds = () => map.fitBounds(MAP_BOUNDS, {
      padding: [12, 12],
      animate: false,
    })
    fitScanBounds()
    map.on('resize', fitScanBounds)

    return () => map.off('resize', fitScanBounds)
  }, [map])

  return null
}

export default function RiskMap({ mode = 'true_color', watchOverlay = null }) {
  const usesTrueColorBase = mode === 'true_color' || mode === 'watch'
  const siteAlerts = getVisibleSiteAlerts(mode, watchOverlay)

  return (
    <MapContainer
      className="leaflet-map"
      bounds={MAP_BOUNDS}
      boundsOptions={{ padding: [12, 12] }}
      maxZoom={12}
      maxBounds={MAP_BOUNDS}
      maxBoundsViscosity={1}
      scrollWheelZoom
      attributionControl
      zoomControl={false}
    >
      <BoundsZoomLock />
      <ScanBoundsView />
      <ZoomControl position="topright" />
      <TileLayer
        url={usesTrueColorBase ? TRUE_COLOR_TILE_URL : TILE_URL}
        attribution={usesTrueColorBase ? TRUE_COLOR_ATTRIBUTION : TILE_ATTRIBUTION}
      />
      {mode === 'ndci' && <NdciRasterOverlay />}
      {canRenderWatchTiles(mode, watchOverlay) && <TileLayer key={watchOverlay.tile_url} url={watchOverlay.tile_url} opacity={0.9} zIndex={450} />}
      {siteAlerts.map((alert) => (
        <CircleMarker
          key={alert.site_id}
          center={[alert.lat, alert.lng]}
          radius={9}
          pathOptions={{ color: '#FFFFFF', weight: 2, fillColor: alert.color, fillOpacity: 0.92 }}
        >
          <Popup><WatchSitePopup alert={alert} /></Popup>
        </CircleMarker>
      ))}
    </MapContainer>
  )
}
