import { Fragment, useEffect, useMemo } from 'react'
import { MapContainer, TileLayer, CircleMarker, ZoomControl, useMap, Tooltip } from 'react-leaflet'
import { 
  RISK_COLOR_HEX, 
  NO_DATA_HEX, 
  NO_DATA_LINE_HEX, 
  STATUS_LABEL, 
  NO_DATA_STATUS, 
  RISK_LABEL_TH,
  RISK_MEANING_TH,
  formatSiteName,
} from '../constants.js'
import { MAP_BOUNDS, syncMinimumBoundsZoom } from '../utils/mapBounds.js'

const UPPER_GULF_CENTER = [13.1, 100.6]
const UPPER_GULF_ZOOM = 9

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

export default function RiskMap({ featureCollection, onSelectSite = () => {}, mode = 'risk', children }) {
  // Render strictly active alert tiers: เริ่มผิดปกติ (elevated), เฝ้าระวัง (watch), and เตือนภัย (warning)
  const features = useMemo(
    () =>
      (featureCollection?.features || []).filter(
        (f) =>
          f.properties.risk_level === 'elevated' ||
          f.properties.risk_level === 'watch' ||
          f.properties.risk_level === 'warning',
      ),
    [featureCollection],
  )

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
      <TileLayer
        key={mode}
        url={mode === 'true_color' ? TRUE_COLOR_TILE_URL : TILE_URL}
        attribution={mode === 'true_color' ? TRUE_COLOR_ATTRIBUTION : TILE_ATTRIBUTION}
        maxNativeZoom={19}
        maxZoom={18}
      />
      <FitToFeatures features={features} />
      {features.map((feature) => {
        const [lng, lat] = feature.geometry.coordinates
        const props = feature.properties
        const isNoData = NO_DATA_STATUS.has(props.status)
        const colorHex = !isNoData ? RISK_COLOR_HEX[props.risk_level] || NO_DATA_LINE_HEX : null
        const label = `${props.name}: ${isNoData ? STATUS_LABEL[props.status] || 'no reading' : props.risk_level || 'Risk not evaluated — no valid baseline exists'}`

        return (
          <Fragment key={props.site_id}>
            {!isNoData && props.risk_level != null && (
              <CircleMarker
                center={[lat, lng]}
                radius={22}
                pathOptions={{
                  color: colorHex,
                  weight: 1.5,
                  fillColor: colorHex,
                  fillOpacity: 0.18,
                  className: 'marker-pulsing-circle',
                }}
                interactive={false}
              />
            )}
            <CircleMarker
              center={[lat, lng]}
              radius={14}
              pathOptions={
                isNoData
                  ? {
                      color: NO_DATA_LINE_HEX,
                      weight: 2,
                      dashArray: '3,3',
                      fillColor: NO_DATA_HEX,
                      fillOpacity: 0.7,
                      className: 'clickable-marker',
                    }
                  : {
                      color: colorHex,
                      weight: 2,
                      fillColor: colorHex,
                      fillOpacity: 0.85,
                      className: 'clickable-marker',
                    }
              }
              eventHandlers={{
                add: (e) => makeAccessible(e.target, label, () => onSelectSite({ lat, lng, ...props })),
                click: () => onSelectSite({ lat, lng, ...props }),
              }}
            >
              <Tooltip direction="top" offset={[0, -10]} opacity={0.95}>
                <div style={{ fontWeight: 600, fontSize: '13px' }}>{formatSiteName(props)}</div>
                <div style={{ fontSize: '11.5px', marginTop: '2px', color: '#1d1d1f' }}>
                  {isNoData ? (
                    'ไม่มีค่าอ่าน'
                  ) : (
                    <>
                      <span style={{ fontWeight: 600 }}>{RISK_LABEL_TH[props.risk_level] || 'ยังประเมินไม่ได้ — ยังไม่มีค่าฐานที่ถูกต้อง'}</span>
                      {RISK_MEANING_TH[props.risk_level] ? (
                        <span style={{ color: '#6e6e73' }}> · {RISK_MEANING_TH[props.risk_level]}</span>
                      ) : null}
                    </>
                  )}
                </div>
              </Tooltip>
            </CircleMarker>
          </Fragment>
        )
      })}
      {children}
    </MapContainer>
  )
}
