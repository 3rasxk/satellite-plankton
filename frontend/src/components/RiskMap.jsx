import { useMemo } from 'react'
import { MapContainer, TileLayer, CircleMarker, useMap } from 'react-leaflet'
import { RISK_COLOR_HEX, NO_DATA_HEX, NO_DATA_LINE_HEX, STATUS_LABEL, NO_DATA_STATUS } from '../constants.js'

const UPPER_GULF_CENTER = [12.9, 100.75]
const UPPER_GULF_ZOOM = 9

// CartoDB Dark Matter — muted dark basemap so the ramp stays legible
// (docs/FRONTEND_PLAN.md §5).
const TILE_URL = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'

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

export default function RiskMap({ featureCollection, onSelectSite }) {
  const features = featureCollection?.features || []

  return (
    <MapContainer
      className="leaflet-map"
      center={UPPER_GULF_CENTER}
      zoom={UPPER_GULF_ZOOM}
      scrollWheelZoom
      attributionControl
    >
      <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} />
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
