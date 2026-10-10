/**
 * SiteDetailPage (`/sites/:siteId`): one monitoring site's latest cached
 * reading, its images, its index values, the TEST anomaly block and the
 * separate MODIS-Aqua `chlor_a` series (dashboard spec §4.3, §10;
 * test-baseline spec §5).
 *
 * Data source (each block degrades on its own):
 *   - `GET /risk-map` (RiskMapResponse): the site's feature (status, scene
 *     date, cloud fraction, the four indices, `index_used`, `fetched_at`,
 *     `stale`, image URLs, the TEST anomaly fields) and the response's
 *     `baseline` block (version, per-site support
 *     `min_season_dates_by_location[site_id]`). An id not in the response
 *     renders the not-found page;
 *   - `GET /risk-map/{site_id}/image?image_type=...`: the cached PNGs;
 *   - `GET /timeseries?lat=&lng=` at the site's own coordinates: the MODIS
 *     series (asked once the site is known; a longer timeout because the
 *     multi-year archive can be slow). Its failure affects that block only;
 *   - `GET /methods` (useBaseline, shared): `modis.grid_resolution_m`.
 * All view logic is in src/lib/sitesModel.js; this file renders it.
 *
 * Rules: index readings only -- the status chip says risk is not
 * evaluated, and no risk tier is shown; the anomaly block is TEST-labelled
 * and appears only while the response has a baseline block; the MODIS
 * quantity is never put on an axis with the Sentinel-2 indices.
 *
 * Footer: the `/risk-map` server `disclaimer`, reported verbatim.
 */
import { useCallback, useEffect, useMemo } from 'react'
import { useOutletContext, useParams } from 'react-router-dom'
import Icon from '../components/Icon.jsx'
import ModisSeries from '../components/ModisSeries.jsx'
import SiteImages from '../components/SiteImages.jsx'
import ErrorState from '../components/ui/ErrorState.jsx'
import PageHeader from '../components/ui/PageHeader.jsx'
import RouteLink from '../components/ui/RouteLink.jsx'
import SourceChip from '../components/ui/SourceChip.jsx'
import StatusChip from '../components/ui/StatusChip.jsx'
import Value from '../components/ui/Value.jsx'
import NotFoundPage from './NotFoundPage.jsx'
import { getRiskMap, getTimeseries } from '../api/client.js'
import { useApi } from '../hooks/useApi.js'
import { useBaseline } from '../hooks/useBaseline.js'
import { reasonKey } from '../lib/format.js'
import { buildSiteDetailModel, TIMESERIES_TIMEOUT_MS } from '../lib/sitesModel.js'
import { useLang } from '../i18n/useLang.js'

function BackLink() {
  const { t } = useLang()
  return (
    <RouteLink to="/sites" className="pw-btn">
      <Icon name="arrow-left" size={16} strokeWidth={1.9} />
      {t('site.back')}
    </RouteLink>
  )
}

function Reading({ model }) {
  const { t } = useLang()
  const reasonCode = model.statusNote?.reasonCode
  const reasonI18n = reasonCode ? reasonKey(reasonCode) : null
  return (
    <section className="pw-section" aria-labelledby="site-reading">
      <h2 className="pw-section-title" id="site-reading">{t('site.reading.heading')}</h2>
      <div className="pw-card pw-site-reading">
        <div className="pw-card-head">
          <span className="pw-chips">{model.chips.map((c) => <StatusChip key={c.key} chip={c} />)}</span>
        </div>
        {model.statusNote && (
          <div className="pw-site-status-note" role="note">
            <p><span className="pw-label">{t('site.reading.why_none')}</span> {reasonI18n ? t(reasonI18n) : reasonCode}</p>
            {model.statusNote.serverText && (
              <>
                <p className="pw-label">{t('site.reading.server_error')}</p>
                <blockquote className="pw-server-text" lang="en">{model.statusNote.serverText}</blockquote>
              </>
            )}
          </div>
        )}
        {model.isStale && <p className="pw-site-stale" data-tone="attention">{t('site.reading.stale_note')}</p>}
        <dl className="pw-kv">
          {model.reading.map((r) => (
            <div key={r.id} data-row={r.id}>
              <dt>{t(r.labelKey)}</dt>
              <dd><Value value={r.value.raw} spec={r.value.spec} source={r.source} /></dd>
            </div>
          ))}
          <div data-row="index_used">
            <dt>{t('site.reading.index_used')}</dt>
            <dd>
              {model.indexUsed.text
                ? <span className="pw-value"><code className="pw-mono">{model.indexUsed.text}</code><SourceChip source={model.indexUsed.source} /></span>
                : <Value value={null} spec={{}} source={model.indexUsed.source} />}
            </dd>
          </div>
          <div data-row="stale">
            <dt>{t('site.reading.stale')}</dt>
            <dd>
              <span className="pw-value">
                <span>{t(model.isStale ? 'common.yes' : 'common.no')}</span>
                <SourceChip source={model.staleSource} />
              </span>
            </dd>
          </div>
        </dl>
        <p className="pw-site-reading-note">{t('site.reading.note')}</p>
      </div>
    </section>
  )
}

function Indices({ model }) {
  const { t } = useLang()
  return (
    <section className="pw-section" aria-labelledby="site-indices">
      <h2 className="pw-section-title" id="site-indices">{t('site.indices.heading')}</h2>
      <p className="pw-ov-section-lede">{t('site.indices.lede')}</p>
      <div className="pw-table-wrap">
        <table className="pw-table pw-table--stack pw-site-indices">
          <thead>
            <tr>
              <th scope="col">{t('site.indices.index')}</th>
              <th scope="col" className="num">{t('site.indices.value')}</th>
              <th scope="col">{t('site.indices.role')}</th>
              <th scope="col">{t('site.indices.definition')}</th>
            </tr>
          </thead>
          <tbody>
            {model.indices.map((ix) => (
              <tr key={ix.key} data-index={ix.key}>
                <th scope="row" data-label={t('site.indices.index')}>{ix.label}</th>
                <td className="num" data-label={t('site.indices.value')}>
                  <Value value={ix.value.raw} spec={ix.value.spec} source={ix.source} reasonText={ix.reasonText ?? undefined} />
                </td>
                <td data-label={t('site.indices.role')}>{ix.used ? t('site.indices.primary') : <span className="pw-label">{t('site.indices.secondary')}</span>}</td>
                <td data-label={t('site.indices.definition')}>
                  <RouteLink to={ix.href}>{t('site.indices.definition_link', { index: ix.label })}</RouteLink>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Anomaly({ anomaly }) {
  const { t } = useLang()
  let body
  if (anomaly.state === 'off') {
    body = <p>{t('site.anomaly.off')}</p>
  } else if (anomaly.state === 'invalid') {
    body = <p>{t('site.anomaly.invalid', { reason: anomaly.reason ?? '—' })}</p>
  } else {
    body = (
      <>
        <dl className="pw-kv">
          <div data-row="level">
            <dt>{t('site.anomaly.level')}</dt>
            <dd>
              {anomaly.chip
                ? <span className="pw-value"><StatusChip chip={anomaly.chip} /><SourceChip source={anomaly.levelSource} /></span>
                : <Value value={null} spec={anomaly.z.spec} source={anomaly.levelSource} showReason />}
            </dd>
          </div>
          <div data-row="robust_z">
            <dt>{t('site.anomaly.robust_z')}</dt>
            <dd><Value value={anomaly.z.raw} spec={anomaly.z.spec} source={anomaly.zSource} /></dd>
          </div>
          <div data-row="version">
            <dt>{t('site.anomaly.version')}</dt>
            <dd><code className="pw-mono">{anomaly.version}</code></dd>
          </div>
          <div data-row="support">
            <dt>{t('site.anomaly.support')}</dt>
            <dd><Value value={anomaly.support.raw} spec={anomaly.support.spec} source={anomaly.supportSource} showReason={anomaly.support.isNull} /></dd>
          </div>
          <div data-row="declared_min">
            <dt>{t('site.anomaly.declared_min')}</dt>
            <dd><Value value={anomaly.declaredMin.raw} spec={anomaly.declaredMin.spec} source={anomaly.declaredMinSource} /></dd>
          </div>
          {anomaly.seasonRule && (
            <div data-row="season_rule">
              <dt>{t('site.anomaly.season_rule')}</dt>
              <dd lang="en">{anomaly.seasonRule}</dd>
            </div>
          )}
          <div data-row="history">
            <dt>{t('site.anomaly.history')}</dt>
            <dd className="pw-mono">{anomaly.history}</dd>
          </div>
        </dl>
        <p className="pw-site-anomaly-note">{t('site.anomaly.support_note')}</p>
      </>
    )
  }
  return (
    <section className="pw-section" aria-labelledby="site-anomaly">
      <h2 className="pw-section-title" id="site-anomaly">{t('site.anomaly.heading')}</h2>
      <div className="pw-card pw-site-anomaly" data-state={anomaly.state}>
        {body}
        <p className="pw-site-anomaly-note">
          {t('site.anomaly.note')}{' '}
          <RouteLink to="/methods#baseline">{t('baseline.methods_link')}</RouteLink>
        </p>
      </div>
    </section>
  )
}

/** The page body for a model (no fetching), so it renders under test. */
export function SiteDetailView({ model, onRetry = {} }) {
  const { t } = useLang()
  if (model.state === 'not_found') return <NotFoundPage />
  if (model.state === 'loading' || model.state === 'error') {
    return (
      <div className="pw-page pw-site-page" aria-busy={model.state === 'loading' || undefined}>
        <PageHeader eyebrow={t('site.eyebrow', { id: model.siteId })} title={t('nav.sites')} actions={<BackLink />} />
        {model.state === 'loading'
          ? <p className="pw-ov-loading">{t('site.loading')}</p>
          : <ErrorState error={model.error?.error} endpoint={model.error?.endpoint} onRetry={onRetry.riskMap} title={t('site.error')} />}
      </div>
    )
  }

  return (
    <div className="pw-page pw-site-page" data-site={model.siteId}>
      <PageHeader
        eyebrow={t('site.eyebrow', { id: model.siteId })}
        title={model.name}
        actions={(
          <>
            <BackLink />
            <a className="pw-btn pw-btn--quiet" href={model.rawUrl} target="_blank" rel="noopener noreferrer">
              {t('action.open_raw_json')}
              <Icon name="external" size={14} strokeWidth={2} />
            </a>
          </>
        )}
      >
        <p className="pw-site-coords">
          <span className="pw-label">{t('site.coords')}</span>{' '}
          <Value value={model.coords.lat.raw} spec={model.coords.lat.spec} source={model.coords.latSource} />
          {' , '}
          <Value value={model.coords.lng.raw} spec={model.coords.lng.spec} source={model.coords.lngSource} />
          <span className="pw-site-coords-note">{` ${t('site.coords_note')}`}</span>
        </p>
      </PageHeader>

      <Reading model={model} />

      <section className="pw-section" aria-labelledby="site-images">
        <h2 className="pw-section-title" id="site-images">{t('site.image.heading')}</h2>
        <SiteImages images={model.images} siteName={model.name} firstFigure={1} />
      </section>

      <Indices model={model} />

      <Anomaly anomaly={model.anomaly} />

      <section className="pw-section" aria-labelledby="site-modis">
        <h2 className="pw-section-title" id="site-modis">{t('site.modis.heading')}</h2>
        <p className="pw-ov-section-lede">{t('site.modis.lede')}</p>
        <ModisSeries modis={model.modis} figureNumber={3} onRetry={onRetry.timeseries} />
      </section>
    </div>
  )
}

export default function SiteDetailPage() {
  const { siteId } = useParams()
  const { reportDisclaimer } = useOutletContext() ?? {}
  const baseline = useBaseline()
  const riskMap = useApi(getRiskMap, [])

  const feature = Array.isArray(riskMap.data?.features)
    ? riskMap.data.features.find((f) => f?.properties?.site_id === siteId) ?? null
    : null
  const coords = Array.isArray(feature?.geometry?.coordinates) ? feature.geometry.coordinates : []
  const lat = Number.isFinite(coords[1]) ? coords[1] : null
  const lng = Number.isFinite(coords[0]) ? coords[0] : null
  const fetchSeries = useCallback(() => getTimeseries(lat, lng, { timeout: TIMESERIES_TIMEOUT_MS }), [lat, lng])
  const series = useApi(fetchSeries, [lat, lng], { enabled: lat !== null && lng !== null })
  // A series kept from another site while this one loads is not shown.
  const seriesData = !series.loading && series.data && series.data.lat === lat && series.data.lng === lng ? series.data : null

  const model = useMemo(() => buildSiteDetailModel({
    riskMap: riskMap.data,
    siteId,
    request: { loading: riskMap.loading, error: riskMap.error },
    timeseries: seriesData,
    timeseriesRequest: { loading: series.loading, error: series.error },
    methods: baseline.methods,
  }), [riskMap.data, riskMap.loading, riskMap.error, siteId, seriesData, series.loading, series.error, baseline.methods])

  const disclaimerText = model.disclaimer?.text ?? null
  const disclaimerEndpoint = model.disclaimer?.endpoint ?? null
  useEffect(() => {
    reportDisclaimer?.(disclaimerText, disclaimerEndpoint)
  }, [reportDisclaimer, disclaimerText, disclaimerEndpoint])

  const onRetry = useMemo(() => ({ riskMap: riskMap.refetch, timeseries: series.refetch }), [riskMap.refetch, series.refetch])
  return <SiteDetailView model={model} onRetry={onRetry} />
}
