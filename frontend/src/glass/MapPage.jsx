/**
 * The map page (`/` and `/map`) of the glass UI: a full-bleed Leaflet map
 * with two basemaps -- True Color (default when the run stored its RGB
 * composite) and NDCI -- the station pins, the left card, the bottom
 * controls (basemap switch + "Sentinel-2 acquisition <date>"), the NDCI
 * colour bar and the right detail panel.
 *
 * Data source: GET /raster-scan (overlay, true-colour image, legend, scene
 * dates) and GET /risk-map (stations), both fetched by the shell; the
 * station's own MODIS series and images are fetched by the detail panel.
 * No sample data. `?site=<id>&layer=<true_color|ndci>` restores a view.
 *
 * Limitations: detection is at satellite pixel resolution (Sentinel-2 ~10 m,
 * MODIS ~4.6 km); small or dispersed blooms may be missed; alert levels
 * are provisional statistics, not a validated detector or forecast.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import RiskMap from '../components/RiskMap.jsx'
import CleanOverlay from './CleanOverlay.jsx'
import MapViewport from '../components/MapViewport.jsx'
import StationPins from './StationPins.jsx'
import LeftCard from './LeftCard.jsx'
import DetailPanel from './DetailPanel.jsx'
import NdciCard from './NdciCard.jsx'
import { Seg } from './ui.jsx'
import useStations from './useStations.js'
import { defaultLayer } from '../lib/mapListModel.js'
import { formatValue } from '../lib/format.js'

const MOBILE = '(max-width: 720px)'
const plain = (t) => (t === undefined ? null : t)

function useMobile() {
  const [m, setM] = useState(() => { try { return window.matchMedia(MOBILE).matches } catch { return false } })
  useEffect(() => {
    const mql = window.matchMedia(MOBILE)
    const on = (e) => setM(e.matches)
    mql.addEventListener?.('change', on)
    return () => mql.removeEventListener?.('change', on)
  }, [])
  return m
}

function initialParams() {
  try {
    const p = new URLSearchParams(window.location.search)
    return { site: p.get('site'), layer: ['true_color', 'ndci'].includes(p.get('layer')) ? p.get('layer') : null }
  } catch {
    return { site: null, layer: null }
  }
}

export default function MapPage() {
  const { scan, risk, setView, openGuide } = useOutletContext()
  const data = scan.data
  const stations = useStations()
  const mobile = useMobile()
  const [init] = useState(initialParams)
  const [layerPick, setLayerPick] = useState(init.layer)
  const layer = layerPick ?? defaultLayer(data)
  const [selId, setSelId] = useState(init.site)
  const [railOpen, setRailOpen] = useState(() => !mobile)
  const [refit, setRefit] = useState(0)
  const mounted = useRef(false)
  const [detail, setDetail] = useState(null)

  const selected = useMemo(() => (stations && selId ? stations.find((s) => s.id === selId) ?? null : null), [stations, selId])
  const hasSel = selected !== null
  // Fit the stations (the content that must stay readable); the raster's own
  // bounds when there are none. At the map's minimum zoom the whole raster
  // can be taller than the free area, the stations are not.
  const fitBounds = useMemo(() => {
    const pts = (stations ?? []).filter((s) => s.pinLat !== null && s.pinLng !== null).map((s) => ({ lat: s.pinLat, lng: s.pinLng }))
    if (pts.length < 2) return data?.bounds
    const lats = pts.map((s) => s.lat)
    const lngs = pts.map((s) => s.lng)
    return [[Math.min(...lats) - 0.04, Math.min(...lngs) - 0.04], [Math.max(...lats) + 0.04, Math.max(...lngs) + 0.04]]
  }, [stations, data?.bounds])

  useEffect(() => {
    setView({ basemap: layer, selected: hasSel })
    return () => setView({ basemap: 'true_color', selected: false })
  }, [layer, hasSel, setView])

  // Keep the address bar in step (no history entries).
  useEffect(() => {
    if (!mounted.current) { mounted.current = true; if (!layerPick && !selId) return }
    try {
      const q = new URLSearchParams()
      if (selId) q.set('site', selId)
      if (layerPick) q.set('layer', layerPick)
      const s = q.toString()
      window.history.replaceState(window.history.state, '', `${window.location.pathname}${s ? `?${s}` : ''}`)
    } catch { /* a refused write leaves the URL as it was */ }
  }, [selId, layerPick])

  const select = useCallback((id) => { setSelId(id); if (mobile) setRailOpen(false) }, [mobile])
  const close = useCallback(() => { setSelId(null); setRefit((n) => n + 1) }, [])
  useEffect(() => {
    if (!hasSel) return undefined
    const onKey = (e) => { if (e.key === 'Escape') close() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [hasSel, close])

  const state = risk.error && !stations ? 'error' : !stations ? 'loading' : stations.length === 0 ? 'empty' : 'ready'
  const newest = typeof data?.newest_scene_date === 'string' ? data.newest_scene_date : null
  const fmtDate = (d) => (d ? formatValue(d, { kind: 'date' }).text : null)
  const trueColorAvailable = Boolean(data?.true_color_url)
  const bm = [['true_color', 'True colour'], ['ndci', 'NDCI']]
  const selPoint = selected && selected.pinLat !== null ? { key: `site:${selected.id}`, lat: selected.pinLat, lng: selected.pinLng, hasLabel: true } : null
  const showLeft = !hasSel && (!mobile || railOpen)

  return (
    <>
      <div className="gl-map">
        <RiskMap mode={layer === 'true_color' ? 'true_color' : 'raster'}>
          {layer === 'ndci' && <CleanOverlay data={data} onDetail={setDetail} />}
          <StationPins stations={stations} selectedId={selected?.id ?? null} onSelect={select} />
          <MapViewport bounds={fitBounds} fitEnabled={!init.site} refit={refit} selected={selPoint} />
        </RiskMap>
      </div>

      {showLeft && (
        <LeftCard
          stations={stations}
          state={state}
          selectedId={selected?.id ?? null}
          onSelect={select}
          onOpenGuide={openGuide}
          showLegend={layer !== 'ndci'}
          sceneDate={fmtDate(newest)}
          onRetry={risk.refetch}
          onClose={mobile ? () => setRailOpen(false) : null}
        />
      )}
      {mobile && !hasSel && !railOpen && (
        <button type="button" className="gl-btn gl-btn--sm gl-show-panel" onClick={() => setRailOpen(true)}>Show panel</button>
      )}

      {layer === 'ndci' && data?.legend && <NdciCard legend={data.legend} detail={detail} />}

      <div className="gl-controls">
        <Seg className="gl-seg--bm" options={bm.filter(([v]) => v !== 'true_color' || trueColorAvailable)} value={layer} onChange={setLayerPick} label="Basemap" />
      </div>
      {newest && (
        <div className="gl-acq gl-acq--br gl-glass">
          <span>Sentinel-2 acquisition</span>
          <span className="gl-mono" style={{ fontWeight: 500 }}>{plain(fmtDate(newest))}</span>
        </div>
      )}

      {selected && <DetailPanel key={selected.id} station={selected} raster={data} onClose={close} />}
    </>
  )
}
