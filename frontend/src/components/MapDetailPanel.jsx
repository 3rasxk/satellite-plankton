/**
 * MapDetailPanel: the right-hand glass panel of the raster map (400 px; a
 * bottom sheet under 720 px) for the selected monitoring station, pin or
 * raster cell -- header (name, coordinates in mono, close), status chips,
 * a plain headline, then an iOS segmented tab row.
 *
 *   Station  Trend | Measurements | Imagery
 *   Pin      Trend | Measurements
 *   Cell     the cell inspector (RasterPixelPanel) inside the same glass
 *
 * Data source (read-only; nothing computed that the API did not send):
 *   - station: `GET /risk-map` through src/lib/sitesModel.js
 *     `buildSiteDetailModel` -- the same model as `/sites/:id`, so the two
 *     can never disagree -- and `GET /timeseries?lat=&lng=` (MODIS-Aqua
 *     `chlor_a` with its same-quantity day-of-year climatology), asked only
 *     once the Trend tab is opened;
 *   - pin: `GET /raster-scan/highlights` (`buildPinView`), and the MODIS
 *     series at the pin's observed pixel on the Trend tab;
 *   - the server `disclaimer` of each response, verbatim.
 *
 * Rules: index readings only. No risk gauge, no "recommended action", no
 * risk tier; an unknown value is "—" with its reason (src/components/ui/
 * Value.jsx), never 0; the TEST anomaly is always labelled TEST; the MODIS
 * quantity never shares an axis with the Sentinel-2 indices.
 */
import { useCallback, useId, useMemo, useState } from 'react'
import Icon from './Icon.jsx'
import ModisSeries from './ModisSeries.jsx'
import SiteImages from './SiteImages.jsx'
import { PinDetails } from './HighlightPins.jsx'
import Segmented from './ui/Segmented.jsx'
import RouteLink from './ui/RouteLink.jsx'
import SourceChip from './ui/SourceChip.jsx'
import StatusChip from './ui/StatusChip.jsx'
import Value from './ui/Value.jsx'
import { getTimeseries } from '../api/client.js'
import { useApi } from '../hooks/useApi.js'
import { reasonKey } from '../lib/format.js'
import { panelId, tabId } from '../lib/segmentIds.js'
import { buildModisModel, buildSiteDetailModel, TIMESERIES_TIMEOUT_MS } from '../lib/sitesModel.js'
import { renderMessage } from '../lib/overviewModel.js'
import { useLang } from '../i18n/useLang.js'

/** The MODIS series at one point, asked only while `enabled`. A series
 * kept from another point while this one loads is not returned. */
function useModisSeries(lat, lng, enabled) {
  const fetchModisSeries = useCallback(
    function fetchModisSeries() {
      return getTimeseries(lat, lng, { timeout: TIMESERIES_TIMEOUT_MS })
    },
    [lat, lng],
  )
  const series = useApi(fetchModisSeries, [lat, lng], { enabled: enabled && lat !== null && lng !== null })
  const data = !series.loading && series.data && series.data.lat === lat && series.data.lng === lng ? series.data : null
  return { data, loading: series.loading, error: series.error, refetch: series.refetch }
}

/** Tab state that remembers whether Trend was ever opened (its series is
 * then kept, not re-asked on every switch). */
function useTabs(initial) {
  const [tab, setTab] = useState(initial)
  const [trendSeen, setTrendSeen] = useState(initial === 'trend')
  const choose = useCallback((next) => {
    setTab(next)
    if (next === 'trend') setTrendSeen(true)
  }, [])
  return { tab, choose, trendWanted: tab === 'trend' || trendSeen }
}

function Coords({ lat, lng, latSource, lngSource }) {
  const { t } = useLang()
  return (
    <p className="pw-detail-coords">
      <span className="pw-sr-only">{`${t('glass.detail.coords')}: `}</span>
      <Value value={lat.raw} spec={lat.spec} source={latSource} />
      {', '}
      <Value value={lng.raw} spec={lng.spec} source={lngSource} />
    </p>
  )
}

/** The panel frame shared by station, pin and cell views. */
function DetailShell({
  kind, kicker, title, coords, chips, headline, tabs, tab, onTab, idBase, onClose, footer, children,
}) {
  const { t } = useLang()
  const tabbed = Array.isArray(tabs) && tabs.length > 1
  return (
    <div className="pw-detail pw-glass" data-kind={kind}>
      <div className="pw-detail-head">
        <div className="pw-detail-titles">
          {kicker && <p className="pw-detail-kicker">{kicker}</p>}
          <h2 className="pw-detail-title">{title}</h2>
          {coords}
        </div>
        {onClose && (
          <button type="button" className="pw-icon-btn pw-detail-close" onClick={() => onClose()} aria-label={t('glass.detail.close')}>
            <Icon name="close" size={16} strokeWidth={2} />
          </button>
        )}
      </div>
      {chips}
      {headline && <p className="pw-detail-headline">{headline}</p>}
      {tabbed && (
        <Segmented
          kind="tabs"
          idBase={idBase}
          label={t('glass.detail.tabs_label')}
          options={tabs}
          value={tab}
          onChange={onTab}
          className="pw-detail-tabs"
        />
      )}
      <div
        className="pw-detail-body"
        role={tabbed ? 'tabpanel' : undefined}
        id={tabbed ? panelId(idBase, tab) : undefined}
        aria-labelledby={tabbed ? tabId(idBase, tab) : undefined}
        tabIndex={tabbed ? 0 : undefined}
      >
        {children}
      </div>
      {footer && <div className="pw-detail-foot">{footer}</div>}
    </div>
  )
}

function Footer({ endpoints, disclaimer, children }) {
  const { t } = useLang()
  return (
    <>
      <p className="pw-detail-sources">
        {t('glass.detail.footer_sources', { sources: endpoints.map((e) => `GET ${e}`).join(' · ') })}
      </p>
      <p className="pw-detail-note">{t('glass.detail.footer_note')}</p>
      {disclaimer && (
        <details className="pw-detail-disclaimer">
          <summary>{t('truth.server_disclaimer')}</summary>
          <blockquote className="pw-server-text" lang="en">{disclaimer}</blockquote>
        </details>
      )}
      {children}
    </>
  )
}

/** One grouped inset list (iOS "inset grouped" table). */
function Inset({ title, children }) {
  const headingId = useId()
  return (
    <section className="pw-inset" aria-labelledby={headingId}>
      <h3 className="pw-inset-title" id={headingId}>{title}</h3>
      <div className="pw-inset-card">{children}</div>
    </section>
  )
}

function Row({ label, children }) {
  return (
    <div className="pw-inset-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

function SiteMeasurements({ model }) {
  const { t } = useLang()
  const a = model.anomaly
  const reasonCode = model.statusNote?.reasonCode
  return (
    <>
      {model.statusNote && (
        <div className="pw-detail-status" role="note">
          <p><span className="pw-label">{t('site.reading.why_none')}</span> {reasonCode ? t(reasonKey(reasonCode)) : '—'}</p>
          {model.statusNote.serverText && (
            <>
              <p className="pw-label">{t('site.reading.server_error')}</p>
              <blockquote className="pw-server-text" lang="en">{model.statusNote.serverText}</blockquote>
            </>
          )}
        </div>
      )}
      {model.isStale && <p className="pw-detail-stale" data-tone="attention">{t('site.reading.stale_note')}</p>}

      <Inset title={t('glass.detail.group_indices')}>
        <dl className="pw-inset-list">
          {model.indices.map((ix) => (
            <Row
              key={ix.key}
              label={(
                <>
                  <RouteLink to={ix.href} className="pw-map-index-link">{ix.label}</RouteLink>
                  {ix.used && <span className="pw-inset-tag">{t('site.indices.primary')}</span>}
                </>
              )}
            >
              <Value value={ix.value.raw} spec={ix.value.spec} source={ix.source} reasonText={ix.reasonText ?? undefined} showReason={ix.value.isNull && !model.statusNote} />
            </Row>
          ))}
        </dl>
      </Inset>

      <Inset title={t('glass.detail.group_scene')}>
        <dl className="pw-inset-list">
          {model.reading.map((r) => (
            <Row key={r.id} label={t(r.labelKey)}>
              <Value value={r.value.raw} spec={r.value.spec} source={r.source} showReason={r.value.isNull && !model.statusNote} />
            </Row>
          ))}
          <Row label={t('site.reading.stale')}>
            <span className="pw-value">
              <span>{t(model.isStale ? 'common.yes' : 'common.no')}</span>
              <SourceChip source={model.staleSource} />
            </span>
          </Row>
        </dl>
      </Inset>

      <Inset title={t('glass.detail.group_anomaly')}>
        {a.state === 'off' && <p className="pw-inset-note">{t('glass.detail.anomaly_off')}</p>}
        {a.state === 'invalid' && <p className="pw-inset-note">{t('site.anomaly.invalid', { reason: a.reason ?? '—' })}</p>}
        {a.state === 'test' && (
          <dl className="pw-inset-list">
            <Row label={t('site.anomaly.level')}>
              {a.chip
                ? <span className="pw-value"><StatusChip chip={a.chip} /><SourceChip source={a.levelSource} /></span>
                : <Value value={null} spec={a.z.spec} source={a.levelSource} showReason />}
            </Row>
            <Row label={t('site.anomaly.robust_z')}>
              <Value value={a.z.raw} spec={a.z.spec} source={a.zSource} showReason={a.z.isNull} />
            </Row>
            <Row label={t('site.anomaly.version')}>
              <code className="pw-mono">{a.version}</code>
            </Row>
          </dl>
        )}
        {a.state === 'test' && <p className="pw-inset-note">{t('site.anomaly.note')}</p>}
      </Inset>

      <Inset title={t('glass.detail.group_bands')}>
        <dl className="pw-inset-list">
          <Row label={t('map.pin.bands')}>
            <Value value={null} spec={{}} reasonText={t('glass.detail.bands_none')} showReason />
          </Row>
        </dl>
      </Inset>

      <p className="pw-inset-note">{t('site.reading.note')}</p>
    </>
  )
}

function SiteImagery({ model }) {
  const { t } = useLang()
  const [which, setWhich] = useState(model.images[0]?.id ?? 'true_color')
  const image = model.images.find((i) => i.id === which) ?? model.images[0]
  if (!image) return null
  return (
    <>
      <p className="pw-inset-note">{t('glass.detail.imagery_lede')}</p>
      <Segmented
        label={t('glass.detail.imagery_choice')}
        options={model.images.map((i) => ({ value: i.id, label: t(i.titleKey) }))}
        value={image.id}
        onChange={setWhich}
        className="pw-detail-imagery-seg"
      />
      <div className="pw-detail-imagery">
        <SiteImages images={[image]} siteName={model.name} firstFigure={1} />
      </div>
      {image.id === 'ndci_heatmap' && <p className="pw-inset-note">{t('site.image.ndci_note')}</p>}
    </>
  )
}

/**
 * The station view.
 * @param {{riskMap, riskMapRequest, siteId, methods, onClose}} props
 */
export function SiteDetailPanel({ riskMap, riskMapRequest, siteId, methods, onClose, initialTab = 'trend' }) {
  const { t } = useLang()
  const idBase = useId().replace(/:/g, '')
  const { tab, choose, trendWanted } = useTabs(initialTab)
  const base = useMemo(() => buildSiteDetailModel({ riskMap, siteId, request: riskMapRequest, methods }), [riskMap, siteId, riskMapRequest, methods])
  const lat = base.state === 'ready' ? base.lat : null
  const lng = base.state === 'ready' ? base.lng : null
  const series = useModisSeries(lat, lng, trendWanted)
  const modis = useMemo(() => buildModisModel({
    timeseries: series.data,
    request: { loading: series.loading, error: series.error },
    methods,
    lat,
    lng,
    siteId: base.siteId,
  }), [series.data, series.loading, series.error, methods, lat, lng, base.siteId])

  if (base.state !== 'ready') return null
  const model = base
  const tabs = [
    { value: 'trend', label: t('glass.detail.tab_trend') },
    { value: 'measurements', label: t('glass.detail.tab_measurements') },
    { value: 'imagery', label: t('glass.detail.tab_imagery') },
  ]
  const date = model.reading.find((r) => r.id === 'actual_date')?.value.text
  const headline = model.status === 'ok'
    ? t('glass.detail.headline_reading', { date })
    : model.status === 'no_data_yet' ? t('glass.detail.headline_not_checked') : t('glass.detail.headline_none')

  return (
    <DetailShell
      kind="site"
      kicker={t('glass.detail.label')}
      title={model.name}
      coords={<Coords lat={model.coords.lat} lng={model.coords.lng} latSource={model.coords.latSource} lngSource={model.coords.lngSource} />}
      chips={<p className="pw-detail-chips">{model.chips.map((c) => <StatusChip key={c.key} chip={c} />)}</p>}
      headline={headline}
      tabs={tabs}
      tab={tab}
      onTab={choose}
      idBase={idBase}
      onClose={onClose}
      footer={(
        <Footer endpoints={tab === 'trend' ? ['/risk-map', '/timeseries'] : ['/risk-map']} disclaimer={tab === 'trend' && modis.disclaimer ? modis.disclaimer.text : model.disclaimer?.text}>
          <RouteLink to={`/sites/${encodeURIComponent(model.siteId)}`} className="pw-detail-more">
            {t('glass.detail.open_page')}
            <Icon name="arrow-right" size={14} strokeWidth={2} />
          </RouteLink>
        </Footer>
      )}
    >
      {tab === 'measurements' && <SiteMeasurements model={model} />}
      {tab === 'trend' && (
        <>
          <p className="pw-inset-note">{t('glass.detail.trend_lede')}</p>
          <ModisSeries modis={modis} figureNumber={1} onRetry={series.refetch} />
        </>
      )}
      {tab === 'imagery' && <SiteImagery model={model} />}
    </DetailShell>
  )
}

/**
 * The pin view: the existing pin inspector (PinDetails) on Measurements,
 * and the MODIS series at the pin's observed pixel on Trend.
 */
export function PinDetailPanel({ view, methods, onClose, onZoom, onInspect, citation, permalink, initialTab = 'trend' }) {
  const { t } = useLang()
  const idBase = useId().replace(/:/g, '')
  const { tab, choose, trendWanted } = useTabs(initialTab)
  const lat = view?.cellQuery?.lat ?? null
  const lng = view?.cellQuery?.lng ?? null
  const series = useModisSeries(lat, lng, trendWanted && view !== null)
  const modis = useMemo(() => buildModisModel({
    timeseries: series.data,
    request: { loading: series.loading, error: series.error },
    methods,
    lat,
    lng,
    siteId: view ? `pin-run-${view.runId}` : null,
  }), [series.data, series.loading, series.error, methods, lat, lng, view])

  if (!view) return null
  const tabs = [
    { value: 'trend', label: t('glass.detail.tab_trend') },
    { value: 'measurements', label: t('glass.detail.tab_measurements') },
  ]
  return (
    <DetailShell
      kind="pin"
      kicker={t(view.headingKey)}
      title={renderMessage(t, view.title)}
      coords={<Coords lat={view.cell.lat} lng={view.cell.lng} latSource={null} lngSource={view.cell.source} />}
      chips={view.anomaly?.chip ? <p className="pw-detail-chips"><StatusChip chip={view.anomaly.chip} /></p> : null}
      tabs={tabs}
      tab={tab}
      onTab={choose}
      idBase={idBase}
      onClose={onClose}
      footer={<Footer endpoints={tab === 'trend' ? ['/raster-scan/highlights', '/timeseries'] : ['/raster-scan/highlights']} disclaimer={tab === 'trend' && modis.disclaimer ? modis.disclaimer.text : null} />}
    >
      {tab === 'measurements' && (
        <PinDetails view={view} onZoom={onZoom} onInspect={onInspect} citation={citation} permalink={permalink} />
      )}
      {tab === 'trend' && (
        lat === null || lng === null
          ? <p className="pw-inset-note">{t('site.modis.no_coords')}</p>
          : (
            <>
              <p className="pw-inset-note">{t('glass.detail.pin_trend_lede')}</p>
              <ModisSeries modis={modis} figureNumber={1} onRetry={series.refetch} />
            </>
          )
      )}
    </DetailShell>
  )
}

/** The cell view: the existing cell inspector in the same glass frame. */
export function CellDetailFrame({ children }) {
  return <div className="pw-detail pw-glass" data-kind="cell"><div className="pw-detail-body">{children}</div></div>
}
