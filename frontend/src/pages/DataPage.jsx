/**
 * DataPage (`/data`): provenance, exports, API reference, limitations and
 * reproducibility (dashboard spec §4.5; test-baseline spec §8).
 *
 * Data source (all read-only):
 *   - `GET /raster-scan`: the run provenance table, the latest-scene line,
 *     the newer-scene poll, the per-day scene breakdown;
 *   - `GET /raster-scan/highlights?n=10`: the pins table (every column of
 *     the pins CSV) and the pins CSV;
 *   - `GET /risk-map`: the sites CSV and GeoJSON, and the site list for the
 *     per-site MODIS download;
 *   - `GET /timeseries`: only when a MODIS CSV button is pressed;
 *   - `GET /methods` (through useBaseline()): API version, baseline
 *     version, gates, MODIS grid resolution.
 * All view logic is in src/lib/dataModel.js; the limitations text is static
 * i18n indexed by src/lib/limitationsMap.js. Each block degrades alone: one
 * failed request never blanks the page.
 *
 * Rules: an unknown value is "—" with a reason; no number is computed; the
 * server `disclaimer` is shown verbatim in the footer (reported from the
 * raster response); no risk wording or colour.
 *
 * Print: the stylesheet hides controls and keeps tables whole, so "Save as
 * PDF" gives a clean document (this page and /methods).
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useOutletContext } from 'react-router-dom'
import Icon from '../components/Icon.jsx'
import ApiReference from '../components/ApiReference.jsx'
import LimitationsList from '../components/LimitationsList.jsx'
import RunTable, { RunNotes } from '../components/RunTable.jsx'
import ErrorState from '../components/ui/ErrorState.jsx'
import PageHeader from '../components/ui/PageHeader.jsx'
import SourceChip from '../components/ui/SourceChip.jsx'
import Value from '../components/ui/Value.jsx'
import { getHighlights, getRasterScan, getRiskMap, getTimeseries } from '../api/client.js'
import { useApi } from '../hooks/useApi.js'
import { loadBaseline, useBaseline } from '../hooks/useBaseline.js'
import { downloadText } from '../lib/browser.js'
import {
  DATA_PINS_N, DATA_SECTIONS, PIN_SERVER_TEXT_COLUMNS, buildApiReference, buildExports, buildPinsTable, buildReproducibility,
  buildRunTable, buildSceneSummary, runModisExport,
} from '../lib/dataModel.js'
import { formatValue } from '../lib/format.js'
import { renderMessage } from '../lib/overviewModel.js'
import { useLang } from '../i18n/useLang.js'

function Section({ id, titleKey, children }) {
  const { t } = useLang()
  return (
    <section className="pw-section pw-data-section" id={id} aria-labelledby={`${id}-heading`}>
      <h2 className="pw-section-title" id={`${id}-heading`}>{t(titleKey)}</h2>
      {children}
    </section>
  )
}

function Loading() {
  const { t } = useLang()
  return <p className="pw-ov-loading" aria-busy="true">{t('data.loading')}</p>
}

function BlockError({ error, onRetry }) {
  const { t } = useLang()
  return <ErrorState error={error?.error} endpoint={error?.endpoint} onRetry={onRetry} title={t('data.error_block')} level={3} />
}

function ServerBlock({ labelKey, children }) {
  const { t } = useLang()
  if (!children) return null
  return (
    <>
      <p className="pw-label">{t(labelKey)}</p>
      <blockquote className="pw-server-text" lang="en">{children}</blockquote>
    </>
  )
}

// ------------------------------------------------------------------ blocks

function RunBlock({ model, onRetry }) {
  const { t } = useLang()
  if (model.state === 'loading') return <Loading />
  if (model.state === 'error') return <BlockError error={model.error} onRetry={onRetry} />
  return (
    <>
      <p className="prose">{t('data.run.intro')}</p>
      <RunTable model={model} />
      <RunNotes notes={model.notes} />
      <ServerBlock labelKey="overview.server_reason">{model.serverReason}</ServerBlock>
    </>
  )
}

function LineBlock({ labelKey, block, serverLabelKey }) {
  const { t } = useLang()
  return (
    <article className="pw-card pw-data-line" data-state={block.state} data-tone={block.tone}>
      <div className="pw-card-head">
        <h3 className="pw-card-title">{t(labelKey)}</h3>
        {block.source && block.state !== 'loading' && block.state !== 'error' && <SourceChip source={block.source} />}
      </div>
      <p>{renderMessage(t, block.line)}</p>
      {block.notes.length > 0 && (
        <ul className="pw-ov-notes" role="list">
          {block.notes.map((n, i) => <li key={`${n.key}-${i}`} data-tone={n.tone}>{renderMessage(t, n)}</li>)}
        </ul>
      )}
      <ServerBlock labelKey={serverLabelKey}>{block.serverReason || block.serverText}</ServerBlock>
    </article>
  )
}

function SceneBlock({ model, onRetry }) {
  const { t } = useLang()
  if (model.state === 'loading') return <Loading />
  if (model.state === 'error') return <BlockError error={model.latest.error} onRetry={onRetry} />
  return (
    <>
      <div className="pw-cols-2">
        <LineBlock labelKey="data.scene.latest_heading" block={model.latest} serverLabelKey="overview.server_reason" />
        <LineBlock labelKey="data.scene.poll_heading" block={model.poll} serverLabelKey="overview.server_error" />
      </div>
      {model.lastUsed && (
        <dl className="pw-kv">
          <div>
            <dt>{t('data.scene.last_used')}</dt>
            <dd><Value value={model.lastUsed.value.raw} spec={model.lastUsed.value.spec} source={model.lastUsed.source} /></dd>
          </div>
        </dl>
      )}
      <h3 className="pw-card-title">{t('data.scene.dates_heading')}</h3>
      <p className="prose">{t('data.scene.dates_intro')}</p>
      {model.sceneDates.length === 0
        ? <p className="pw-map-note">{t('data.scene.dates_none')}</p>
        : (
          <div className="pw-table-wrap">
            <table className="pw-table pw-table--stack">
              <caption>{t('data.scene.dates_caption')}</caption>
              <thead>
                <tr>
                  <th scope="col">{t('data.scene.col_date')}</th>
                  <th scope="col">{t('data.scene.col_cells')}</th>
                  <th scope="col">{t('data.scene.col_share')}</th>
                </tr>
              </thead>
              <tbody>
                {model.sceneDates.map((d) => (
                  <tr key={d.key}>
                    <td data-label={t('data.scene.col_date')} className="num"><Value value={d.date.raw} spec={d.date.spec} source={model.sceneDatesSource} /></td>
                    <td data-label={t('data.scene.col_cells')} className="num"><Value value={d.cells.raw} spec={d.cells.spec} /></td>
                    <td data-label={t('data.scene.col_share')} className="num"><Value value={d.share.raw} spec={d.share.spec} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
    </>
  )
}

function DownloadButton({ spec, labelKey, disabled }) {
  const { t } = useLang()
  const onClick = () => {
    if (!spec) return
    try {
      downloadText(spec.filename, spec.content(), spec.type)
    } catch {
      // A click handler never throws; the page stays as it was.
    }
  }
  return (
    <button type="button" className="pw-btn" onClick={onClick} disabled={!spec || disabled}>
      <Icon name="download" size={16} strokeWidth={1.9} />
      {t(labelKey)}
    </button>
  )
}

function PinsBlock({ model, onRetry, exportSpec }) {
  const { t } = useLang()
  if (model.state === 'loading') return <Loading />
  if (model.state === 'error') return <BlockError error={model.error} onRetry={onRetry} />
  return (
    <>
      <p className="prose">{t('data.pins.intro')}</p>
      <ul className="pw-ov-notes" role="list">
        {model.notes.map((n) => <li key={n.key}>{renderMessage(t, n)}</li>)}
      </ul>
      {model.state === 'empty'
        ? (
          <>
            <p className="pw-map-note">{t('data.pins.empty')}</p>
            <ServerBlock labelKey="data.pins.empty_reason">{model.serverReason}</ServerBlock>
          </>
        )
        : (
          <>
            <p className="pw-label">
              {t('data.pins.scroll_hint')}
              {model.source && <SourceChip source={model.source} />}
            </p>
            <div className="pw-table-wrap" tabIndex={0} role="region" aria-label={t('data.pins.caption')}>
              <table className="pw-table pw-data-pins">
                <caption className="pw-sr-only">{t('data.pins.caption')}</caption>
                <thead>
                  <tr>{model.columns.map((c) => <th scope="col" key={c}><code className="pw-mono">{c}</code></th>)}</tr>
                </thead>
                <tbody>
                  {model.rows.map((row) => (
                    <tr key={row.key}>
                      {row.cells.map((cell, j) => {
                        const column = model.columns[j]
                        const server = PIN_SERVER_TEXT_COLUMNS.includes(column)
                        return (
                          <td key={column} className={cell.spec.kind === 'text' ? undefined : 'num'} data-null={cell.isNull ? 'true' : 'false'}>
                            {cell.isNull
                              ? <Value value={null} spec={{ reason: cell.reason ?? 'not_available' }} />
                              : <span className={server ? 'pw-data-server-cell' : undefined} lang={server ? 'en' : undefined}>{cell.text}</span>}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      <div className="pw-data-actions">
        <DownloadButton spec={exportSpec} labelKey="data.exports.pins_csv" />
      </div>
    </>
  )
}

function ModisExports({ targets, resolutionText }) {
  const { t } = useLang()
  const [status, setStatus] = useState({})
  const run = useCallback(async (target) => {
    setStatus((s) => ({ ...s, [target.siteId]: { state: 'busy' } }))
    const result = await runModisExport({ target, fetcher: getTimeseries, download: downloadText })
    setStatus((s) => ({ ...s, [target.siteId]: result.ok ? { state: 'done', file: result.filename } : { state: 'failed' } }))
  }, [])
  return (
    <div className="pw-data-modis">
      <h3 className="pw-card-title">{t('data.exports.modis_heading')}</h3>
      <p className="prose">
        {resolutionText
          ? t('data.exports.modis_intro', { resolution: resolutionText })
          : t('data.exports.modis_intro_no_resolution')}
      </p>
      {targets.length === 0
        ? <p className="pw-map-note">{t('data.exports.modis_none')}</p>
        : (
          <ul className="pw-data-modis-list" role="list">
            {targets.map((target) => {
              const st = status[target.siteId]?.state ?? 'idle'
              return (
                <li key={target.siteId}>
                  <button type="button" className="pw-btn" onClick={() => run(target)} disabled={st === 'busy'}>
                    <Icon name="download" size={16} strokeWidth={1.9} />
                    {t('data.exports.modis_button', { site: target.name })}
                  </button>
                  <span className="pw-data-status" role="status" aria-live="polite">
                    {st === 'busy' && t('data.exports.modis_busy')}
                    {st === 'done' && t('data.exports.modis_done', { file: status[target.siteId].file })}
                    {st === 'failed' && t('data.exports.modis_failed')}
                  </span>
                </li>
              )
            })}
          </ul>
        )}
    </div>
  )
}

function ExportsBlock({ exports, pinsModel, resolutionText }) {
  const { t } = useLang()
  return (
    <>
      <p className="prose">{t('data.exports.intro')}</p>
      <div className="pw-data-actions">
        <DownloadButton spec={exports.sitesCsv} labelKey="data.exports.sites_csv" />
        <DownloadButton spec={exports.sitesGeojson} labelKey="data.exports.sites_geojson" />
        <DownloadButton spec={pinsModel.csv} labelKey="data.exports.pins_csv" />
      </div>
      {(!exports.sitesCsv || !pinsModel.csv) && <p className="pw-map-note">{t('data.exports.unavailable')}</p>}
      <p className="pw-map-note">{t('data.exports.geojson_note')}</p>
      <ModisExports targets={exports.modis} resolutionText={resolutionText} />
      <p className="pw-map-note">{t('data.exports.cell_note')}</p>
    </>
  )
}

function ReproBlock({ model, onRetry }) {
  const { t } = useLang()
  return (
    <>
      <p className="prose">{t('data.repro.intro')}</p>
      {model.state === 'error' && <BlockError error={model.error} onRetry={onRetry} />}
      <dl className="pw-kv pw-data-repro">
        {model.items.map((it) => (
          <div key={it.id} data-row={it.id}>
            <dt>{it.labelKey ? t(it.labelKey) : <code className="pw-mono">{it.label}</code>}</dt>
            <dd>
              {it.isNull
                ? <Value value={null} spec={{ reason: model.state === 'loading' ? 'not_checked_yet' : 'not_available' }} source={it.source ?? undefined} />
                : (
                  <span className="pw-value">
                    <code className="pw-mono">{it.text}</code>
                    {it.source && <SourceChip source={it.source} />}
                  </span>
                )}
            </dd>
          </div>
        ))}
      </dl>
      <p className="pw-map-note">{t('data.repro.build_note')}</p>
      {model.isDevBuild && <p className="pw-map-note" data-tone="attention">{t('data.repro.dev_build')}</p>}
      <p className="pw-map-note">{t('data.repro.cite_hint')}</p>
    </>
  )
}

/** The page body for ready-made models (no fetching), so it renders under test. */
export function DataView({ models, onPrint, onRetry = {} }) {
  const { t } = useLang()
  return (
    <div className="pw-page pw-data-page">
      <PageHeader
        eyebrow={t('data.eyebrow')}
        title={t('nav.data')}
        lede={t('data.lede')}
        actions={(
          <button type="button" className="pw-btn" onClick={onPrint}>
            <Icon name="download" size={16} strokeWidth={1.9} />
            {t('data.print')}
          </button>
        )}
      />
      <nav className="pw-methods-toc" aria-labelledby="data-toc-label">
        <p className="pw-label" id="data-toc-label">{t('data.toc')}</p>
        <ol role="list">
          {DATA_SECTIONS.map((s) => <li key={s.id}><a href={`#${s.id}`}>{t(s.titleKey)}</a></li>)}
        </ol>
      </nav>
      <Section id="run" titleKey="data.section.run"><RunBlock model={models.run} onRetry={onRetry.raster} /></Section>
      <Section id="scene" titleKey="data.section.scene"><SceneBlock model={models.scene} onRetry={onRetry.raster} /></Section>
      <Section id="pins" titleKey="data.section.pins">
        <PinsBlock model={models.pins} onRetry={onRetry.pins} exportSpec={models.pins.csv} />
      </Section>
      <Section id="exports" titleKey="data.section.exports">
        <ExportsBlock exports={models.exports} pinsModel={models.pins} resolutionText={models.resolutionText} />
      </Section>
      <Section id="api" titleKey="data.section.api">
        <p className="prose">{t('data.api.intro')}</p>
        <ApiReference rows={models.api} />
      </Section>
      <Section id="limits" titleKey="data.section.limits"><LimitationsList /></Section>
      <Section id="repro" titleKey="data.section.repro"><ReproBlock model={models.repro} onRetry={onRetry.methods} /></Section>
    </div>
  )
}

const MINUTE_MS = 60000

/** Wall-clock time, refreshed each minute (for the poll's age text). */
function useNow(intervalMs) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

export default function DataPage() {
  const { reportDisclaimer } = useOutletContext() ?? {}
  const { hash } = useLocation()
  const baseline = useBaseline()
  const methods = baseline.methods
  const now = useNow(MINUTE_MS)
  const raster = useApi(getRasterScan, [])
  const riskMap = useApi(getRiskMap, [])
  const fetchPins = useCallback(() => getHighlights({ n: DATA_PINS_N }), [])
  const pins = useApi(fetchPins, [])

  const rasterReq = useMemo(() => ({ loading: raster.loading, error: raster.error }), [raster.loading, raster.error])
  const pinsReq = useMemo(() => ({ loading: pins.loading, error: pins.error }), [pins.loading, pins.error])
  const riskReq = useMemo(() => ({ loading: riskMap.loading, error: riskMap.error }), [riskMap.loading, riskMap.error])
  const methodsReq = useMemo(() => ({
    loading: baseline.status === 'loading',
    error: baseline.status === 'error' ? baseline.error : null,
  }), [baseline.status, baseline.error])

  const models = useMemo(() => {
    const run = buildRunTable({ raster: raster.data, request: rasterReq })
    const scene = buildSceneSummary({ raster: raster.data, request: rasterReq, methods, nowMs: now })
    const pinsModel = buildPinsTable({ highlights: pins.data, request: pinsReq })
    const exports = buildExports({ riskMap: riskMap.data, pins: pinsModel, riskMapRequest: riskReq })
    const grid = methods?.modis?.grid_resolution_m
    const resolution = formatValue(grid, { kind: 'count', unit: 'm' })
    return {
      run,
      scene,
      pins: pinsModel,
      exports,
      api: buildApiReference({ raster: raster.data }),
      repro: buildReproducibility({ methods, request: methodsReq }),
      resolutionText: resolution.isNull ? null : resolution.text,
    }
  }, [now, raster.data, rasterReq, methods, pins.data, pinsReq, riskMap.data, riskReq, methodsReq])

  const disclaimerText = typeof raster.data?.disclaimer === 'string' ? raster.data.disclaimer : null
  useEffect(() => {
    reportDisclaimer?.(disclaimerText, disclaimerText ? '/raster-scan' : null)
  }, [reportDisclaimer, disclaimerText])

  // Content arrives after the route renders, so jump to the URL's anchor once
  // the first block has settled. getElementById, not querySelector.
  const settled = !raster.loading
  useEffect(() => {
    const fragment = typeof hash === 'string' ? hash.replace(/^#/, '') : ''
    if (!settled || typeof document === 'undefined' || fragment === '') return
    let id
    try {
      id = decodeURIComponent(fragment)
    } catch {
      return
    }
    document.getElementById(id)?.scrollIntoView({ block: 'start' })
  }, [settled, hash])

  const onPrint = useCallback(() => {
    if (typeof window !== 'undefined' && typeof window.print === 'function') window.print()
  }, [])

  return (
    <DataView
      models={models}
      onPrint={onPrint}
      onRetry={{ raster: raster.refetch, pins: pins.refetch, methods: () => loadBaseline() }}
    />
  )
}

