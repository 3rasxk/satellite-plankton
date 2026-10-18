/**
 * The raster map page (`/map`, dashboard spec §4.2, §4.6; test-baseline spec
 * §6, §7) -- the served raster over a neutral basemap, a left rail, highlight
 * pins, a provenance-rich inspector and a permalink.
 *
 * Data source (all read-only; no Earth Engine call from here):
 *   - `GET /raster-scan`: the served run -- overlay, legend, coverage, scene
 *     dates, provenance, latest scene, poll (rail and banner);
 *   - `GET /raster-scan/highlights?n=<3-10>&run_id=<served run>`: the pins,
 *     in the mode the API picks (no `mode` is sent);
 *   - `GET /raster-scan/pixel?lat=&lng=&run_id=`: one cell, only for a click
 *     on the map (or "Read this cell" on a pin) -- never for a control;
 *   - `GET /risk-map`: the seven monitoring stations (list, markers, panel);
 *   - `GET /timeseries?lat=&lng=`: the MODIS series, only on a Trend tab;
 *   - useBaseline() (`/methods`): TEST mode for the wording, settle hours.
 * All view logic is in src/lib/mapModel.js; this file wires state to it.
 *
 * One raster at a time: a different `run_id` remounts the view, so an old
 * reading, pin or pending response cannot outlive its picture.
 *
 * Layout (2026-10 glass restyle; stylesheets dashboard.css "Raster map
 * page" and glass.css "Map page"): a full-bleed map under the shell's
 * floating glass top bar, with floating glass panels -- the left card
 * (RasterRail: headline, count chips, stations, pins, scan details; hidden
 * while a station or pin is open; a drawer under 1024 px), a top line with
 * the newest-acquisition pill and the truth bar ("Truth boundary",
 * expanding to the three points and the server disclaimer -- the footer is
 * below the fold on this page), the bottom-left dock (NDCI colour bar in
 * the NDCI layer, else the no-data caption, and the layer switch: True
 * Color | NDCI), and the right detail panel (MapDetailPanel; a
 * bottom sheet under 720 px). Over the True Color layer the panels are
 * solid white. Every panel is a sibling of the Leaflet container, never
 * inside it, so no click on a control can reach the map's click handler
 * (the only control left inside the map, Leaflet's own zoom buttons, stops
 * its own clicks; pin and station markers do not bubble).
 *
 * Stations: `GET /risk-map` (the scheduler's cached readings) drawn as
 * white-ringed circles with a "Name · status" chip; selecting one opens its
 * Trend | Measurements | Imagery panel. A station selection is not written
 * to the permalink (the permalink names cells, pins, run, layer, zoom).
 *
 * Permalink: `decodeView(location.search)` once on load (lat/lng select and
 * fly to the cell; `pin` selects that pin; `layer`, `zoom`, `run`), and
 * `encodeView` written with `history.replaceState` after an interaction. A
 * link to a run that is no longer served says so and shows the latest.
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { useMap } from 'react-leaflet'
import { useApi } from '../hooks/useApi.js'
import { useBaseline } from '../hooks/useBaseline.js'
import { getHighlights, getRasterPixel, getRasterScan, getRiskMap } from '../api/client.js'
import Icon from '../components/Icon.jsx'
import RiskMap from '../components/RiskMap.jsx'
import RasterLayerSwitcher, { RasterMapLayers } from '../components/RasterLayerSwitcher.jsx'
import { NdciScaleBar, RasterLegendDock } from '../components/RasterLegend.jsx'
import RasterPixelProbe from '../components/RasterPixelProbe.jsx'
import RasterPixelPanel from '../components/RasterPixelPanel.jsx'
import RasterRail from '../components/RasterRail.jsx'
import HighlightPins from '../components/HighlightPins.jsx'
import MapSiteMarkers from '../components/MapSiteMarkers.jsx'
import MapViewport from '../components/MapViewport.jsx'
import { CellDetailFrame, PinDetailPanel, SiteDetailPanel } from '../components/MapDetailPanel.jsx'
import {
  applyPermalink, buildPinView, buildPinsModel, buildRailModel, clampPinCount, readPermalink, serializeView,
  PIN_N_DEFAULT,
} from '../lib/mapModel.js'
import { buildCountChips, buildMapHeadline, buildSiteListModel, defaultLayer } from '../lib/mapListModel.js'
import { formatValue } from '../lib/format.js'
import { useLang } from '../i18n/useLang.js'

const MINUTE_MS = 60000
const FOCUS_ZOOM = 12
const DRAWER_QUERY = '(max-width: 1023px)'

function currentSearch() {
  try {
    return typeof window !== 'undefined' ? window.location.search : ''
  } catch {
    return ''
  }
}

/** The `?lang=` currently in the address bar (kept when the view is written). */
function urlLang() {
  try {
    return new URLSearchParams(currentSearch()).get('lang') ?? undefined
  } catch {
    return undefined
  }
}

/** Replace the query in place (no navigation, no history entry). Keeps the
 * router's own history state so back/forward still work. */
function writeQuery(query) {
  if (typeof window === 'undefined') return
  try {
    const { pathname, hash, search } = window.location
    const next = query ? `?${query}` : ''
    if (next === search) return
    window.history.replaceState(window.history.state, '', `${pathname}${next}${hash}`)
  } catch {
    // A refused history write leaves the URL as it was; the view still works.
  }
}

function absoluteUrl(query) {
  try {
    const { origin, pathname } = window.location
    return `${origin}${pathname}${query ? `?${query}` : ''}`
  } catch {
    return ''
  }
}

function prefersReducedMotion() {
  try {
    return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  } catch {
    return false
  }
}

function drawerMatches() {
  try {
    return typeof window !== 'undefined' && window.matchMedia?.(DRAWER_QUERY).matches === true
  } catch {
    return false
  }
}

/** True below 1024 px, where the rail is a drawer. */
function useDrawerMode() {
  const [drawer, setDrawer] = useState(drawerMatches)
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined
    const mql = window.matchMedia(DRAWER_QUERY)
    const onChange = (event) => setDrawer(event.matches)
    mql.addEventListener?.('change', onChange)
    return () => mql.removeEventListener?.('change', onChange)
  }, [])
  return drawer
}

/** Wall-clock time, re-read every `intervalMs`, so poll ages stay true. */
function useNow(intervalMs) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

/**
 * Map-side effects that need the Leaflet instance: fly to a target, apply
 * the permalink's zoom once, report zoom changes, notice user interaction
 * (for the permalink) and keep Leaflet's size in step with its container
 * (the rail and the truth bar change it). Renders nothing.
 */
function MapController({ target, initialZoom, onZoom, onUserInteraction }) {
  const map = useMap()

  useEffect(() => {
    if (!map || typeof map.on !== 'function') return undefined
    const handleZoom = () => onZoom?.(map.getZoom())
    map.on('zoomend', handleZoom)
    const el = typeof map.getContainer === 'function' ? map.getContainer() : null
    const mark = () => onUserInteraction?.()
    el?.addEventListener('pointerdown', mark)
    el?.addEventListener('wheel', mark, { passive: true })
    el?.addEventListener('keydown', mark)
    let observer = null
    if (el && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => map.invalidateSize())
      observer.observe(el)
    }
    return () => {
      map.off('zoomend', handleZoom)
      el?.removeEventListener('pointerdown', mark)
      el?.removeEventListener('wheel', mark)
      el?.removeEventListener('keydown', mark)
      observer?.disconnect()
    }
  }, [map, onZoom, onUserInteraction])

  const appliedZoom = useRef(false)
  useEffect(() => {
    if (appliedZoom.current || !map || typeof map.setZoom !== 'function') return
    appliedZoom.current = true
    if (Number.isFinite(initialZoom) && !target) map.setZoom(initialZoom)
  }, [map, initialZoom, target])

  useEffect(() => {
    if (!target || !map || typeof map.flyTo !== 'function') return
    const zoom = Number.isFinite(target.zoom) ? target.zoom : Math.max(map.getZoom(), FOCUS_ZOOM)
    if (prefersReducedMotion()) map.setView([target.lat, target.lng], zoom)
    else map.flyTo([target.lat, target.lng], zoom, { duration: 0.6 })
  }, [map, target])

  return null
}

/** The one-line truth bar inside the map column. */
function MapTruthBar({ disclaimer, endpoint, isTest }) {
  const { t } = useLang()
  return (
    <details className="pw-map-truth">
      <summary>
        <Icon name="alert" size={14} strokeWidth={2} />
        <span className="pw-map-truth-label">{t('map.truthbar.label')}</span>
        <span className="pw-map-truth-summary">{t('map.truthbar.summary')}</span>
      </summary>
      <div className="pw-map-truth-body">
        <ol className="pw-truth-list" role="list">
          <li>{t('truth.point_1')}</li>
          <li>{t('truth.point_2')}</li>
          <li>{t(isTest ? 'truth.point_3_test' : 'truth.point_3')}</li>
        </ol>
        <p className="pw-truth-null">{t('truth.null_rule')}</p>
        <p className="pw-label">{t('truth.server_disclaimer')}</p>
        {disclaimer ? (
          <>
            <blockquote className="pw-server-text" lang="en">{disclaimer}</blockquote>
            {endpoint && <p className="pw-footer-note">{t('truth.disclaimer_source', { endpoint: `GET ${endpoint}` })}</p>}
          </>
        ) : (
          <p className="pw-footer-note">{t('truth.no_server_disclaimer')}</p>
        )}
      </div>
    </details>
  )
}

/** "Newest Sentinel-2 acquisition <date>" -- the raster's newest cell date;
 * the title gives the span, since every cell keeps its own date. */
function AcquisitionPill({ raster }) {
  const { t } = useLang()
  const newest = typeof raster?.newest_scene_date === 'string' ? raster.newest_scene_date : null
  if (!newest) return null
  const date = formatValue(newest, { kind: 'date' }).text
  const oldest = typeof raster?.oldest_scene_date === 'string' ? formatValue(raster.oldest_scene_date, { kind: 'date' }).text : null
  return (
    <p className="pw-map-acq" title={oldest ? t('glass.acquisition_span', { oldest, newest: date }) : undefined}>
      <Icon name="satellite" size={14} strokeWidth={1.9} />
      <span>{t('glass.acquisition', { date })}</span>
    </p>
  )
}

export default function RasterPage() {
  const { data, loading, error, refetch } = useApi(getRasterScan, [])
  // Read once: later writes to the address bar are this page's own.
  const [initialView] = useState(() => readPermalink(currentSearch()))
  const drawer = useDrawerMode()
  const [railOpen, setRailOpen] = useState(() => !drawerMatches())
  const firstDrawer = useRef(true)
  useEffect(() => {
    if (firstDrawer.current) {
      firstDrawer.current = false
      return
    }
    setRailOpen(!drawer)
  }, [drawer])

  // A different scan replaces the picture and all inspector state in one
  // render. An old reading or pending response must not outlive its image.
  return (
    <RasterView
      key={data?.run_id ?? 'no-raster'}
      data={data}
      loading={loading}
      error={error}
      refetch={refetch}
      initialView={initialView}
      drawer={drawer}
      railOpen={railOpen}
      setRailOpen={setRailOpen}
    />
  )
}

function RasterView({ data, loading, error, refetch, initialView, drawer, railOpen, setRailOpen }) {
  const { t, lang } = useLang()
  const baseline = useBaseline()
  const { reportDisclaimer } = useOutletContext() ?? {}
  const runId = Number.isInteger(data?.run_id) ? data.run_id : null
  const hasRaster = runId !== null
  const railId = useId()
  const toggleRef = useRef(null)
  const inspectorRef = useRef(null)
  const now = useNow(MINUTE_MS)

  // The permalink, applied to the raster this view was mounted for.
  const [applied] = useState(() => applyPermalink(initialView, { raster: data }))
  // `lang` alone is the language toggle's, not a view to restore.
  const hadPermalink = Object.keys(initialView ?? {}).some((key) => key !== 'lang')
  const [selection, setSelection] = useState(applied.selection)
  // A link's layer wins; a fresh visit opens on the run's own true-colour
  // composite when it stored one, else the NDCI raster.
  const [layerMode, setLayerMode] = useState(() => (typeof initialView?.layer === 'string' ? applied.layer : defaultLayer(data)))
  const [zoom, setZoom] = useState(applied.zoom)
  const [flyTarget, setFlyTarget] = useState(applied.fly)
  const [notes] = useState(applied.notes)
  const [pinCount, setPinCount] = useState(() => clampPinCount(Math.max(PIN_N_DEFAULT, applied.selection?.kind === 'pin' ? applied.selection.rank : 0)))
  const [showPins, setShowPins] = useState(true)
  const [interacted, setInteracted] = useState(false)
  const [refit, setRefit] = useState(0)
  const markInteraction = useCallback(() => setInteracted(true), [])
  const onZoom = useCallback((z) => setZoom(z), [])

  // --- the clicked cell: asked only for a map click (or "Read this cell").
  const pickedLat = selection?.kind === 'cell' ? selection.lat : null
  const pickedLng = selection?.kind === 'cell' ? selection.lng : null
  // Named functions: the test fixture for useApi keys responses by name.
  const fetchPixel = useCallback(
    function fetchPixel() {
      return pickedLat !== null ? getRasterPixel(pickedLat, pickedLng, runId) : Promise.resolve(null)
    },
    [pickedLat, pickedLng, runId],
  )
  const {
    data: pixel,
    loading: pixelLoading,
    error: pixelError,
  } = useApi(fetchPixel, [pickedLat, pickedLng], { enabled: pickedLat !== null && hasRaster })

  // --- the pins of this run, in the API's chosen mode.
  const fetchHighlights = useCallback(
    function fetchHighlights() {
      return getHighlights({ n: pinCount, run_id: runId })
    },
    [pinCount, runId],
  )
  const highlights = useApi(fetchHighlights, [pinCount, runId], { enabled: hasRaster })
  const highlightsLoading = hasRaster && (highlights.loading || (!highlights.data && !highlights.error))
  const highlightsData = highlightsLoading ? null : highlights.data
  const pins = useMemo(() => buildPinsModel({
    highlights: highlightsData,
    request: { loading: highlightsLoading, error: highlights.error },
    runId,
    n: pinCount,
    show: showPins,
  }), [highlightsData, highlightsLoading, highlights.error, runId, pinCount, showPins])

  // --- the monitoring stations (scheduler cache; no Earth Engine call).
  const riskMap = useApi(getRiskMap, [])
  const riskMapRequest = useMemo(() => ({ loading: riskMap.loading, error: riskMap.error }), [riskMap.loading, riskMap.error])
  const sites = useMemo(
    () => buildSiteListModel({ riskMap: riskMap.data, request: riskMapRequest }),
    [riskMap.data, riskMapRequest],
  )
  const headline = useMemo(() => buildMapHeadline({ sites, pins }), [sites, pins])
  const countChips = useMemo(
    () => buildCountChips({ sites, pins, highlights: highlightsData }),
    [sites, pins, highlightsData],
  )

  // A selected pin that is not among the loaded pins (a link's rank this
  // run does not have, or N lowered below it) is no selection.
  const pinsSettled = pins.state !== 'loading'
  const pinFound = (rank) => pins.state === 'ready' && pins.items.some((p) => p.rank === rank)
  const effective = selection?.kind === 'pin' && pinsSettled && !pinFound(selection.rank) ? null : selection
  const selectedRank = effective?.kind === 'pin' ? effective.rank : null
  const selectedSiteId = effective?.kind === 'site' ? effective.id : null
  // The left card steps aside while a station or pin is open (desktop); in
  // drawer mode selecting already closes the drawer.
  const railHidden = !drawer && (effective?.kind === 'pin' || effective?.kind === 'site')
  const railShown = railOpen && !railHidden
  const railTitleId = `${railId}-title`
  // Where the open station or pin sits, so the map can keep it (and a
  // station's label) visible beside the detail panel.
  const selectedPoint = useMemo(() => {
    if (selectedSiteId !== null && sites.state === 'ready') {
      const s = sites.items.find((i) => i.id === selectedSiteId)
      return s?.onMap ? { key: `site:${s.id}`, lat: s.lat, lng: s.lng, hasLabel: true } : null
    }
    if (selectedRank !== null && pins.state === 'ready') {
      const p = pins.items.find((i) => i.rank === selectedRank)
      return p?.onMap ? { key: `pin:${p.rank}`, lat: p.lat, lng: p.lng, hasLabel: false } : null
    }
    return null
  }, [selectedSiteId, selectedRank, sites, pins])
  const fitEnabled = applied.zoom == null && !applied.fly && !applied.selection
  const pinView = useMemo(
    () => (selectedRank !== null && pins.state === 'ready' ? buildPinView(highlightsData, selectedRank) : null),
    [selectedRank, pins.state, highlightsData],
  )

  // A pin named by the permalink: the map flies to it once the pins are
  // here (unless the reader has moved on), or the rail says it is not
  // among them.
  const linkRank = applied.selection?.kind === 'pin' ? applied.selection.rank : null
  const linkPin = linkRank !== null && selectedRank === linkRank ? pins.items.find((p) => p.rank === linkRank) : null
  const linkLat = linkPin?.onMap ? linkPin.lat : null
  const linkLng = linkPin?.onMap ? linkPin.lng : null
  const linkPinTarget = useMemo(
    () => (linkLat !== null ? { lat: linkLat, lng: linkLng, zoom: applied.zoom } : null),
    [linkLat, linkLng, applied.zoom],
  )
  const allNotes = linkRank !== null && pinsSettled && !pinFound(linkRank)
    ? [...notes, { key: 'map.permalink.pin_missing', params: { pin: String(linkRank) }, tone: 'attention' }]
    : notes

  const rail = useMemo(
    () => buildRailModel({ raster: data, request: { loading, error }, methods: baseline.methods, now }),
    [data, loading, error, baseline.methods, now],
  )

  // --- permalink: written after an interaction (or to normalise a link).
  useEffect(() => {
    if (!interacted && !hadPermalink) return
    writeQuery(serializeView({ selection: effective, layer: layerMode, zoom, runId, lang: urlLang() }))
  }, [interacted, hadPermalink, effective, layerMode, zoom, runId, lang])

  const permalink = useCallback(
    () => absoluteUrl(serializeView({ selection: effective, layer: layerMode, zoom, runId, lang })),
    [effective, layerMode, zoom, runId, lang],
  )
  const citation = useMemo(() => ({
    runId,
    oldestScene: data?.oldest_scene_date,
    newestScene: data?.newest_scene_date,
    baselineVersion: baseline.isTest ? baseline.version : null,
  }), [runId, data?.oldest_scene_date, data?.newest_scene_date, baseline.isTest, baseline.version])

  // --- the server disclaimer of the response being shown, for the footer
  // and the truth bar (verbatim).
  const shown = (pixel && effective?.kind === 'cell' && typeof pixel.disclaimer === 'string' && pixel.disclaimer)
    ? { text: pixel.disclaimer, endpoint: '/raster-scan/pixel' }
    : (effective?.kind === 'site' && typeof riskMap.data?.disclaimer === 'string' && riskMap.data.disclaimer)
      ? { text: riskMap.data.disclaimer, endpoint: '/risk-map' }
    : (pins.state === 'ready' && typeof highlightsData?.disclaimer === 'string' && highlightsData.disclaimer)
      ? { text: highlightsData.disclaimer, endpoint: '/raster-scan/highlights' }
      : (typeof data?.disclaimer === 'string' && data.disclaimer)
        ? { text: data.disclaimer, endpoint: '/raster-scan' }
        : (baseline.disclaimer ? { text: baseline.disclaimer, endpoint: '/methods' } : null)
  const disclaimerText = shown?.text ?? null
  const disclaimerEndpoint = shown?.endpoint ?? null
  useEffect(() => {
    reportDisclaimer?.(disclaimerText, disclaimerEndpoint)
  }, [reportDisclaimer, disclaimerText, disclaimerEndpoint])

  // --- actions.
  const onPick = useCallback((point) => {
    setSelection({ kind: 'cell', lat: point.lat, lng: point.lng })
    markInteraction()
    if (drawer) setRailOpen(false) // the drawer would cover the inspector
  }, [markInteraction, drawer, setRailOpen])
  const selectPin = useCallback((rank, { fly = false } = {}) => {
    setSelection({ kind: 'pin', rank })
    markInteraction()
    if (fly) {
      const item = pins.items.find((p) => p.rank === rank)
      if (item?.onMap) setFlyTarget({ lat: item.lat, lng: item.lng, zoom: null })
    }
    // The drawer covers the map, and on desktop the card steps aside: move
    // focus to the inspector so it is not lost with the list.
    if (drawer) setRailOpen(false)
    setTimeout(() => inspectorRef.current?.focus(), 0)
  }, [pins.items, markInteraction, drawer, setRailOpen])
  const selectSite = useCallback((id, { fly = false } = {}) => {
    setSelection({ kind: 'site', id })
    markInteraction()
    if (fly) {
      const item = sites.state === 'ready' ? sites.items.find((s) => s.id === id) : null
      if (item?.onMap) setFlyTarget({ lat: item.lat, lng: item.lng, zoom: null })
    }
    if (drawer) setRailOpen(false)
    setTimeout(() => inspectorRef.current?.focus(), 0)
  }, [sites, markInteraction, drawer, setRailOpen])
  const onLayerChange = useCallback((mode) => {
    setLayerMode(mode)
    markInteraction()
  }, [markInteraction])
  const onPinCount = useCallback((n) => {
    setPinCount(clampPinCount(n))
  }, [])
  const clearSelection = useCallback(() => {
    const hadPanel = selection?.kind === 'pin' || selection?.kind === 'site'
    setSelection(null)
    markInteraction()
    // The card comes back: return focus to its headline, not to <body>.
    if (hadPanel) setRefit((n) => n + 1)
    if (hadPanel && !drawer) setTimeout(() => document.getElementById(railTitleId)?.focus(), 0)
  }, [markInteraction, selection, drawer, railTitleId])

  const openRail = () => setRailOpen(true)
  const closeRail = () => {
    setRailOpen(false)
    // Back to the control that opened it (it renders once the rail is closed).
    setTimeout(() => toggleRef.current?.focus(), 0)
  }

  // In drawer mode, move focus into the drawer when it opens.
  const railWasOpen = useRef(railOpen)
  useEffect(() => {
    if (drawer && railOpen && !railWasOpen.current && typeof document !== 'undefined') {
      document.getElementById(railId)?.querySelector('.pw-map-rail-close')?.focus()
    }
    railWasOpen.current = railOpen
  }, [drawer, railOpen, railId])

  // Esc inside a source popover closes only the popover (SourceChip).
  const inPopover = (event) => event.target instanceof Element && event.target.closest('.pw-source') !== null
  const onPageKeyDown = (event) => {
    if (event.key !== 'Escape' || inPopover(event)) return
    if (drawer && railOpen && event.target instanceof Node && document.getElementById(railId)?.contains(event.target)) {
      event.stopPropagation()
      closeRail()
    }
  }
  const onInspectorKeyDown = (event) => {
    if (event.key === 'Escape' && effective && !inPopover(event)) {
      event.stopPropagation()
      clearSelection()
    }
  }

  return (
    <div
      className="overview-page pw-map-page"
      data-rail={railShown ? 'open' : 'closed'}
      data-drawer={drawer ? 'true' : 'false'}
      data-basemap={layerMode}
      data-selection={effective?.kind ?? 'none'}
      onKeyDown={onPageKeyDown}
    >
      <h1 className="pw-sr-only">{t('map.title')}</h1>

      <div className="overview-map-area pw-map-canvas">
        <RiskMap mode="raster">
          <RasterMapLayers mode={layerMode} data={data} t={t} />
          <MapSiteMarkers sites={sites} selectedId={selectedSiteId} onSelect={(id) => selectSite(id)} />
          <HighlightPins pins={pins} selectedRank={selectedRank} onSelect={(rank) => selectPin(rank)} />
          <MapViewport bounds={data?.bounds} fitEnabled={fitEnabled} refit={refit} selected={selectedPoint} />
          <MapController target={flyTarget ?? linkPinTarget} initialZoom={applied.zoom} onZoom={onZoom} onUserInteraction={markInteraction} />
          {hasRaster && <RasterPixelProbe onPick={onPick} />}
        </RiskMap>
      </div>

      <RasterRail
        id={railId}
        titleId={railTitleId}
        open={railShown}
        drawer={drawer}
        onClose={closeRail}
        raster={data}
        rasterLoading={loading}
        rasterError={error}
        onRefresh={refetch}
        isTest={baseline.isTest}
        rail={rail}
        pins={pins}
        pinCount={pinCount}
        onPinCount={onPinCount}
        showPins={showPins}
        onShowPins={setShowPins}
        selectedRank={selectedRank}
        onSelectPin={(rank) => selectPin(rank, { fly: true })}
        onRetryPins={highlights.refetch}
        notes={allNotes}
        sites={sites}
        headline={headline}
        countChips={countChips}
        selectedSiteId={selectedSiteId}
        onSelectSite={(id) => selectSite(id, { fly: true })}
        onRetrySites={riskMap.refetch}
      />

      {!railOpen && !railHidden && (
        <button
          type="button"
          ref={toggleRef}
          className="pw-btn pw-map-rail-toggle"
          aria-controls={railId}
          aria-expanded={false}
          onClick={openRail}
        >
          <Icon name="menu" size={16} strokeWidth={2} />
          {t('map.rail.show')}
        </button>
      )}

      <div className="pw-map-topline">
        <AcquisitionPill raster={data} />
        <MapTruthBar disclaimer={disclaimerText} endpoint={disclaimerEndpoint} isTest={baseline.isTest} />
      </div>

      <div className="pw-map-dock" data-stack={effective ? 'true' : 'false'}>
        <div className="pw-map-dock-legend">
          {layerMode === 'ndci' && data?.legend
            ? <NdciScaleBar legend={data.legend} />
            : <RasterLegendDock layerMode={layerMode} legend={data?.legend} hasRaster={hasRaster} />}
        </div>
        <div className="pw-map-dock-layers">
          <RasterLayerSwitcher
            mode={layerMode}
            onModeChange={onLayerChange}
            trueColorAvailable={Boolean(data?.true_color_url)}
            t={t}
          />
        </div>
      </div>

      <div
        className="pw-map-inspector"
        ref={inspectorRef}
        tabIndex={-1}
        aria-live="polite"
        aria-label={t('map.inspector.label')}
        role="region"
        onKeyDown={onInspectorKeyDown}
      >
        {effective?.kind === 'site' && (
          <SiteDetailPanel
            key={effective.id}
            riskMap={riskMap.data}
            riskMapRequest={riskMapRequest}
            siteId={effective.id}
            methods={baseline.methods}
            onClose={clearSelection}
          />
        )}
        {effective?.kind === 'pin' && (
          <PinDetailPanel
            key={effective.rank}
            view={pinView}
            methods={baseline.methods}
            onClose={clearSelection}
            onZoom={pinView?.target ? () => setFlyTarget({ ...pinView.target, zoom: Math.max(zoom ?? 0, FOCUS_ZOOM) }) : undefined}
            onInspect={pinView?.cellQuery ? () => {
              setSelection({ kind: 'cell', lat: pinView.cellQuery.lat, lng: pinView.cellQuery.lng })
              markInteraction()
            } : undefined}
            citation={citation}
            permalink={permalink}
          />
        )}
        {effective?.kind === 'cell' && (
          <CellDetailFrame>
            <RasterPixelPanel
              pixel={pixel}
              loading={pixelLoading}
              error={pixelError}
              onClose={clearSelection}
              citation={citation}
              permalink={permalink}
            />
          </CellDetailFrame>
        )}
      </div>
    </div>
  )
}
