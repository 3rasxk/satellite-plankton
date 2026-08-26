import { useMemo } from 'react'
import { MapContainer, TileLayer, CircleMarker, ZoomControl, useMap } from 'react-leaflet'
import { RISK_COLOR_HEX, NO_DATA_HEX, NO_DATA_LINE_HEX, STATUS_LABEL, NO_DATA_STATUS } from '../constants.js'
import NdciRasterOverlay from './NdciRasterOverlay.jsx'

const UPPER_GULF_CENTER = [12.9, 100.75]
const UPPER_GULF_ZOOM = 9

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

function FitToFeatures({ features }) {
  const map = useMap()
  useMemo(() => {
    if (!features || features.length === 0) return
    const bounds = features.map((f) => [f.geometry.coordinates[1], f.geometry.coordinates[0]])
    if (bounds.length === 1) {
      map.setView(bounds[0], UPPER_GULF_ZOOM)
    } else {
      map.fitBounds(bounds, { padding: [60, 60] })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [features])
  return null
}

/**
 * Makes a Leaflet vector layer keyboard-reachable: Leaflet renders
 * CircleMarker as an SVG <path>, which isn't in the tab order or
 * keypress-able by default. Setting tabindex + a keydown listener on the
 * rendered element is the standard workaround (react-leaflet doesn't
 * expose this itself) — see .claude/agents/frontend-dashboard.md
 * acceptance criteria: "cells clickable and keyboard-reachable."
 */
function makeAccessible(layer, label, onActivate) {
  const el = layer.getElement?.()
  if (!el) return
  el.setAttribute('tabindex', '0')
  el.setAttribute('role', 'button')
  el.setAttribute('aria-label', label)
  el.classList.add('risk-marker')
  el.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onActivate()
    }
  })
}

export default function RiskMap({ featureCollection, onSelectSite, mode = 'risk' }) {
  const features = featureCollection?.features || []

  return (
    <MapContainer
      className="leaflet-map"
      center={UPPER_GULF_CENTER}
      zoom={UPPER_GULF_ZOOM}
      scrollWheelZoom
      attributionControl
      zoomControl={false}
    >
      <ZoomControl position="topright" />
      <TileLayer
        url={mode === 'true_color' ? TRUE_COLOR_TILE_URL : TILE_URL}
        attribution={mode === 'true_color' ? TRUE_COLOR_ATTRIBUTION : TILE_ATTRIBUTION}
      />
      {mode === 'ndci' && <NdciRasterOverlay />}
      <FitToFeatures features={features} />
      {features.map((feature) => {
        const [lng, lat] = feature.geometry.coordinates
        const props = feature.properties
        const isNoData = NO_DATA_STATUS.has(props.status)
        const colorHex = !isNoData ? RISK_COLOR_HEX[props.risk_level] : null
        const label = `${props.name}: ${isNoData ? STATUS_LABEL[props.status] || 'no reading' : props.risk_level}`

        return (
          <CircleMarker
            key={props.site_id}
            center={[lat, lng]}
            radius={12}
            pathOptions={
              isNoData
                ? {
                    color: NO_DATA_LINE_HEX,
                    weight: 1.5,
                    dashArray: '3,3',
                    fillColor: NO_DATA_HEX,
                    fillOpacity: 0.55,
                  }
                : {
                    color: colorHex,
                    weight: 1.5,
                    fillColor: colorHex,
                    fillOpacity: 0.75,
                  }
            }
            eventHandlers={{
              add: (e) => makeAccessible(e.target, label, () => onSelectSite({ lat, lng, ...props })),
              click: () => onSelectSite({ lat, lng, ...props }),
            }}
          />
        )
      })}
    </MapContainer>
  )
}
