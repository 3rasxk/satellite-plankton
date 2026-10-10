/**
 * ModisSeries: the MODIS-Aqua `chlor_a` series at one monitoring site, with
 * its day-of-year-climatology z-score, as a numbered figure with the full
 * data table beneath and a CSV (dashboard spec §4.3).
 *
 * Data source: `model.modis` from src/lib/sitesModel.js `buildModisModel`:
 *   - `GET /timeseries?lat=&lng=` (TimeseriesResponse): `points[].date`,
 *     `chlor_a` (mg m⁻³), `anomaly_z` (z against the MODIS-Aqua
 *     day-of-year climatology of the same quantity) and `reason` when z is
 *     null; `source` (server text, shown verbatim);
 *   - `GET /methods` `modis.grid_resolution_m` (the Level-3 grid, 4638 m),
 *     never a hard-coded "1 km".
 *
 * The two scatter panels live in ModisChart.jsx (lazy-loaded with the
 * charting library); this file keeps the figure, data table, CSV and
 * states, so the numbers are readable before (or without) the chart.
 *
 * Why a new chart and not the legacy TimeSeriesChart: that component
 * averages points by month and fills months without data with built-in
 * "reference" values, which would draw numbers the API never sent. Here
 * every mark is one API point; nothing is averaged, interpolated or
 * filled. Points are drawn as dots (no line), because the observations are
 * irregular and a line would imply values between them.
 *
 * Two panels, two axes, one quantity each: `chlor_a` (top) and
 * `anomaly_z` (bottom). The Sentinel-2 indices are never plotted here, on
 * any axis. A null z is not drawn (and never as 0); the table lists it
 * with the server's reason. Marks are ink, never a risk or accent colour.
 *
 * States: loading (skeleton; a cold request reads a multi-year archive),
 * timeout, error (HTTP status, endpoint, server detail, retry), empty, ready.
 * A failure here degrades this block only.
 */
import { Suspense, lazy, useId } from 'react'
import Icon from './Icon.jsx'
import RouteLink from './ui/RouteLink.jsx'
import EmptyState from './ui/EmptyState.jsx'
import ErrorState from './ui/ErrorState.jsx'
import FigureFrame from './ui/FigureFrame.jsx'
import SourceChip from './ui/SourceChip.jsx'
import Value from './ui/Value.jsx'
import { renderMessage } from '../lib/overviewModel.js'
import { useLang } from '../i18n/useLang.js'

// The charting library is large; fetch it only when a series is drawn.
const ModisChart = lazy(() => import('./ModisChart.jsx'))

function ChartFallback() {
  return <div className="pw-modis-skeleton" aria-hidden="true"><span /><span /></div>
}

function DataTable({ modis }) {
  const { t } = useLang()
  return (
    <table className="pw-table pw-modis-table">
      <caption>{t('site.modis.table_caption', { n: String(modis.count) })}</caption>
      <thead>
        <tr>
          <th scope="col">{t('site.modis.col_date')}</th>
          <th scope="col" className="num">chlor_a (mg m⁻³)</th>
          <th scope="col" className="num">anomaly_z</th>
          <th scope="col">{t('site.modis.col_reason')}</th>
        </tr>
      </thead>
      <tbody>
        {modis.rows.map((r) => (
          <tr key={r.key}>
            <td className="pw-mono">{r.date.text}</td>
            <td className="num"><Value value={r.chlor.raw} spec={r.chlor.spec} /></td>
            <td className="num"><Value value={r.z.raw} spec={r.z.spec} /></td>
            <td>{r.reasonText ? <span lang="en">{r.reasonText}</span> : null}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Facts({ modis }) {
  const { t } = useLang()
  return (
    <dl className="pw-kv pw-modis-facts">
      <div>
        <dt>{t('site.modis.resolution')}</dt>
        <dd><Value value={modis.resolution.value.raw} spec={modis.resolution.value.spec} source={modis.resolution.source} /></dd>
      </div>
      <div>
        <dt>{t('site.modis.collection')}</dt>
        <dd>{modis.resolution.collection ? <code className="pw-mono">{modis.resolution.collection}</code> : <Value value={null} spec={{}} />}</dd>
      </div>
      <div>
        <dt>{t('site.modis.request')}</dt>
        <dd><code className="pw-mono">{`GET ${modis.endpoint}`}</code></dd>
      </div>
    </dl>
  )
}

export default function ModisSeries({ modis, figureNumber, onRetry }) {
  const { t } = useLang()
  const altId = useId()
  if (!modis) return null

  let body
  if (modis.state === 'loading') {
    body = (
      <div className="pw-modis-loading" aria-busy="true">
        <div className="pw-modis-skeleton" aria-hidden="true"><span /><span /></div>
        <p className="pw-ov-loading">{t('site.modis.loading')}</p>
      </div>
    )
  } else if (modis.state === 'timeout' || modis.state === 'error') {
    body = (
      <ErrorState
        error={modis.error?.error}
        endpoint={modis.error?.endpoint}
        onRetry={onRetry}
        level={3}
        title={modis.state === 'timeout'
          ? t('site.modis.timeout', { seconds: String(modis.timeoutSeconds) })
          : t('site.modis.error')}
      />
    )
  } else if (modis.state === 'empty') {
    body = <EmptyState level={3} icon="chart" title={t('site.modis.empty_title')} body={renderMessage(t, modis.empty)} />
  } else {
    const caption = t('site.modis.caption', {
      n: String(modis.count), span: modis.span, resolution: modis.resolution.value.text,
    })
    body = (
      <FigureFrame
        number={figureNumber}
        caption={caption}
        source={modis.source}
        dataTable={<DataTable modis={modis} />}
        csv={modis.csv}
        className="pw-modis-figure"
      >
        <p className="pw-sr-only" id={altId}>{t('site.modis.alt', { n: String(modis.count), first: modis.first, last: modis.last })}</p>
        <div className="pw-modis-panels" role="img" aria-labelledby={altId}>
          <Suspense fallback={<ChartFallback />}>
            <ModisChart data={modis.chart} chlLabel={t('site.modis.chart_chl')} zLabel={t('site.modis.z_label')} />
          </Suspense>
        </div>
      </FigureFrame>
    )
  }

  return (
    <div className="pw-modis" data-state={modis.state}>
      <p className="pw-modis-z-note">
        <span className="pw-modis-z-label">{t('site.modis.z_label')}</span>
        {modis.zSource && <SourceChip source={modis.zSource} />}
      </p>
      <Facts modis={modis} />
      {body}
      {modis.state === 'ready' && modis.zMissing > 0 && (
        <p className="pw-modis-note">{t('site.modis.z_missing', { n: String(modis.zMissing) })}</p>
      )}
      {modis.sourceText && (
        <>
          <p className="pw-label">{t('site.modis.server_source')}</p>
          <blockquote className="pw-server-text" lang="en">{modis.sourceText}</blockquote>
        </>
      )}
      <p className="pw-modis-methods">
        <RouteLink to="/methods#modis">
          {t('site.modis.methods_link')}
          <Icon name="arrow-right" size={14} strokeWidth={2} />
        </RouteLink>
      </p>
    </div>
  )
}
