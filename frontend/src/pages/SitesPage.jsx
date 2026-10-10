/**
 * SitesPage (`/sites`): the seven fixed monitoring sites, one row each
 * (dashboard spec §4.3).
 *
 * Data source: `GET /risk-map` (RiskMapResponse) -- the scheduler's cached
 * latest Sentinel-2 reading per site, never a live pull -- and its
 * `baseline` block for the TEST anomaly column. All view logic is in
 * src/lib/sitesModel.js; this file renders it and keeps the sort in the
 * URL (`?sort=<column>&dir=asc|desc`, other params such as `lang` kept),
 * so a sorted view can be linked.
 *
 * Exports: the sites CSV (src/lib/csv.js `sitesCsv`, documented column
 * order) and the GeoJSON (the `/risk-map` response verbatim), both built
 * on click from the response already on the page.
 *
 * Footer: the response's server `disclaimer`, reported verbatim to the
 * shell's TruthFooter.
 *
 * Limitations: read-only, fetched once per visit (Retry on error). Index
 * readings only; bloom risk is not evaluated.
 */
import { useCallback, useEffect, useMemo } from 'react'
import { useOutletContext, useSearchParams } from 'react-router-dom'
import Icon from '../components/Icon.jsx'
import SitesTable from '../components/SitesTable.jsx'
import EmptyState from '../components/ui/EmptyState.jsx'
import ErrorState from '../components/ui/ErrorState.jsx'
import PageHeader from '../components/ui/PageHeader.jsx'
import { getRiskMap } from '../api/client.js'
import { useApi } from '../hooks/useApi.js'
import { downloadText } from '../lib/browser.js'
import { buildSitesModel } from '../lib/sitesModel.js'
import { renderMessage } from '../lib/overviewModel.js'
import { useLang } from '../i18n/useLang.js'

function ExportButton({ spec, labelKey }) {
  const { t } = useLang()
  const onClick = () => {
    if (!spec) return
    try {
      downloadText(spec.filename, spec.content(), spec.type)
    } catch {
      // Never throw from a click handler; the table stays on screen.
    }
  }
  return (
    <button type="button" className="pw-btn" onClick={onClick} disabled={!spec}>
      <Icon name="download" size={16} strokeWidth={1.9} />
      {t(labelKey)}
    </button>
  )
}

function LoadingTable() {
  const { t } = useLang()
  return (
    <div aria-busy="true">
      <ul className="pw-sites-skeleton" aria-hidden="true">
        {Array.from({ length: 7 }, (_, i) => <li key={i}><span /><span /><span /></li>)}
      </ul>
      <p className="pw-ov-loading">{t('sites.loading')}</p>
    </div>
  )
}

/** The page body for a model (no fetching), so it renders under test. */
export function SitesView({ model, onSort, onRetry }) {
  const { t } = useLang()
  let body
  if (model.state === 'loading') body = <LoadingTable />
  else if (model.state === 'error') {
    body = <ErrorState error={model.error?.error} endpoint={model.error?.endpoint} onRetry={onRetry} title={t('sites.error')} />
  } else if (model.state === 'empty') {
    body = <EmptyState title={t('sites.empty_title')} body={renderMessage(t, model.notes[0])} />
  } else body = <SitesTable model={model} onSort={onSort} />

  const showNotes = model.state === 'ready' || model.state === 'stale'
  return (
    <div className="pw-page pw-sites-page">
      <PageHeader
        eyebrow={t('sites.eyebrow')}
        title={t('nav.sites')}
        lede={t('sites.lede')}
        actions={(
          <>
            <ExportButton spec={model.exports?.csv} labelKey="action.download_csv" />
            <ExportButton spec={model.exports?.geojson} labelKey="sites.export_geojson" />
          </>
        )}
      />
      {showNotes && model.notes.length > 0 && (
        <ul className="pw-ov-notes pw-sites-notes" role="list">
          {model.notes.map((n, i) => <li key={`${n.key}-${i}`} data-tone={n.tone}>{renderMessage(t, n)}</li>)}
        </ul>
      )}
      <section className="pw-section" aria-labelledby="sites-table">
        <h2 className="pw-section-title" id="sites-table">{t('sites.table_heading')}</h2>
        {body}
      </section>
      <p className="pw-sites-footnote">{t('sites.footnote')}</p>
    </div>
  )
}

export default function SitesPage() {
  const { reportDisclaimer } = useOutletContext() ?? {}
  const riskMap = useApi(getRiskMap, [])
  const [params, setParams] = useSearchParams()
  const sortParam = params.get('sort')
  const dirParam = params.get('dir')
  const sort = useMemo(() => (sortParam ? { column: sortParam, direction: dirParam === 'desc' ? 'desc' : 'asc' } : null), [sortParam, dirParam])

  const model = useMemo(() => buildSitesModel({
    riskMap: riskMap.data,
    request: { loading: riskMap.loading, error: riskMap.error },
    sort,
  }), [riskMap.data, riskMap.loading, riskMap.error, sort])

  const onSort = useCallback((next) => {
    setParams((prev) => {
      const out = new URLSearchParams(prev)
      if (next) {
        out.set('sort', next.column)
        out.set('dir', next.direction)
      } else {
        out.delete('sort')
        out.delete('dir')
      }
      return out
    }, { replace: true })
  }, [setParams])

  const disclaimerText = model.disclaimer?.text ?? null
  const disclaimerEndpoint = model.disclaimer?.endpoint ?? null
  useEffect(() => {
    reportDisclaimer?.(disclaimerText, disclaimerEndpoint)
  }, [reportDisclaimer, disclaimerText, disclaimerEndpoint])

  return <SitesView model={model} onSort={onSort} onRetry={riskMap.refetch} />
}
