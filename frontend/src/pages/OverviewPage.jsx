/**
 * OverviewPage (`/`): the current situation, honestly stated (dashboard
 * spec §4.1). An officer should know in seconds what the satellite saw,
 * when, how much of the area was actually measured, and what is not
 * claimed; a judge can open the source of every number.
 *
 * Data source: four read-only requests, each degrading only its own block
 * (spec §10) --
 *   - `GET /raster-scan`   status banner, three key facts, latest-scene and
 *                          poll lines, the map figure;
 *   - `GET /summary`       status banner, "sites with a usable reading";
 *   - `GET /risk-map`      the sites strip and the site marks on the figure;
 *   - `GET /raster-scan/highlights?n=5&run_id=<served run>`  the pins, asked
 *                          only once the raster names its run, so the pins
 *                          and the picture always describe the same run;
 * plus useBaseline() (`/methods`, shared and cached) for the TEST lines.
 * All view logic is in src/lib/overviewModel.js; this file renders it.
 *
 * Footer: the server `disclaimer` of the response the model picks (the
 * highlights while their pins are drawn, else /summary, /risk-map,
 * /raster-scan) is reported to the shell's TruthFooter, verbatim.
 *
 * Limitations: read-only and fetched once per visit (Retry per block); the
 * ages in the poll line advance each minute without refetching. Nothing
 * here is a bloom statement or a risk level.
 */
import { useCallback, useEffect, useId, useMemo, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import Icon from '../components/Icon.jsx'
import OverviewMapPreview, { InlineError } from '../components/OverviewMapPreview.jsx'
import EmptyState from '../components/ui/EmptyState.jsx'
import ErrorState from '../components/ui/ErrorState.jsx'
import PageHeader from '../components/ui/PageHeader.jsx'
import RouteLink from '../components/ui/RouteLink.jsx'
import SourceChip from '../components/ui/SourceChip.jsx'
import StatusChip from '../components/ui/StatusChip.jsx'
import Value from '../components/ui/Value.jsx'
import { getHighlights, getRasterScan, getRiskMap, getSummary } from '../api/client.js'
import { useApi } from '../hooks/useApi.js'
import { useBaseline } from '../hooks/useBaseline.js'
import { buildOverviewModel, renderMessage, PIN_COUNT } from '../lib/overviewModel.js'
import { useLang } from '../i18n/useLang.js'

const MINUTE_MS = 60000

/** Wall-clock time, re-read every `intervalMs`, so ages stay true. */
function useNow(intervalMs) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

function Notes({ notes, className = 'pw-ov-notes' }) {
  const { t } = useLang()
  if (!Array.isArray(notes) || notes.length === 0) return null
  return (
    <ul className={className} role="list">
      {notes.map((n, i) => <li key={`${n.key}-${i}`} data-tone={n.tone}>{renderMessage(t, n)}</li>)}
    </ul>
  )
}

function StatusBanner({ banner }) {
  const { t } = useLang()
  const headingId = useId()
  const loading = banner.state === 'loading'
  return (
    <section
      className="pw-ov-banner"
      data-state={banner.state}
      data-tone={banner.tone}
      aria-labelledby={headingId}
      aria-busy={loading || undefined}
    >
      <h2 className="pw-sr-only" id={headingId}>{t('overview.status_heading')}</h2>
      <span className="pw-ov-banner-icon" aria-hidden="true">
        <Icon name={banner.tone === 'attention' ? 'alert' : 'satellite'} size={20} strokeWidth={1.7} />
      </span>
      <div className="pw-ov-banner-body" aria-live="polite">
        <p className="pw-ov-banner-head">{t(banner.key, banner.params)}</p>
        {banner.lines.length > 0 && (
          <ul className="pw-ov-banner-lines" role="list">
            {banner.lines.map((line, i) => (
              <li key={`${line.key}-${i}`} data-tone={line.tone}>{t(line.key, line.params)}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

function FactCard({ card, onRetry }) {
  const { t } = useLang()
  const titleId = useId()
  const loading = card.state === 'loading'
  let body
  if (loading) {
    body = (
      <>
        <div className="pw-fact-skeleton" aria-hidden="true"><span /><span /></div>
        <p className="pw-ov-loading">{renderMessage(t, card.notes[0])}</p>
      </>
    )
  } else if (card.state === 'error') {
    body = (
      <>
        <p className="pw-fact-figure"><span className="pw-stat-value"><Value value={null} spec={card.value.spec} /></span></p>
        <InlineError message={card.notes[0]} error={card.error} onRetry={onRetry} />
      </>
    )
  } else {
    body = (
      <>
        <p className="pw-fact-figure">
          <span className="pw-stat-value">
            <Value value={card.value.raw} spec={card.value.spec} source={card.source} />
          </span>
          {card.unit && <span className="pw-fact-unit">{renderMessage(t, card.unit)}</span>}
        </p>
        {card.breakdown.length > 0 && (
          <dl className="pw-fact-breakdown">
            {card.breakdown.map((row) => (
              <div key={row.id} data-row={row.id}>
                <dt><StatusChip chip={row.chip} /></dt>
                <dd><Value value={row.value.raw} spec={row.value.spec} source={row.source} /></dd>
              </div>
            ))}
          </dl>
        )}
        <Notes notes={card.notes} className="pw-ov-notes pw-fact-notes" />
        {card.link && (
          <RouteLink to={card.link.to} className="pw-fact-link">
            {t(card.link.key)}
            <Icon name="arrow-right" size={14} strokeWidth={2} />
          </RouteLink>
        )}
      </>
    )
  }
  return (
    <article
      className="pw-card pw-fact pw-span-3"
      data-fact={card.id}
      data-state={card.state}
      aria-labelledby={titleId}
      aria-busy={loading || undefined}
    >
      <div className="pw-card-head">
        <h3 className="pw-card-title" id={titleId}>{t(card.titleKey)}</h3>
        {card.chips.length > 0 && (
          <span className="pw-chips">{card.chips.map((c) => <StatusChip key={c.key} chip={c} />)}</span>
        )}
      </div>
      {body}
    </article>
  )
}

function LineCard({ block, labelKey, id, serverLabelKey, onRetry }) {
  const { t } = useLang()
  const titleId = useId()
  let body
  if (block.state === 'loading') {
    body = <p className="pw-ov-loading">{renderMessage(t, block.line)}</p>
  } else if (block.state === 'error') {
    body = <InlineError message={block.line} error={block.error} onRetry={onRetry} />
  } else {
    body = (
      <>
        <p className="pw-ov-line-text">{renderMessage(t, block.line)}</p>
        <Notes notes={block.notes} />
        {block.serverText && (
          <>
            <p className="pw-label pw-ov-server-label">{t(serverLabelKey)}</p>
            <blockquote className="pw-server-text" lang="en">{block.serverText}</blockquote>
          </>
        )}
      </>
    )
  }
  return (
    <article
      className="pw-card pw-ov-line pw-span-6"
      data-block={id}
      data-state={block.state}
      data-tone={block.tone}
      aria-labelledby={titleId}
      aria-busy={block.state === 'loading' || undefined}
    >
      <div className="pw-card-head">
        <h3 className="pw-card-title" id={titleId}>{t(labelKey)}</h3>
        {block.source && block.state !== 'loading' && block.state !== 'error' && <SourceChip source={block.source} />}
      </div>
      {body}
    </article>
  )
}

function SitesStrip({ sites, onRetry }) {
  const { t } = useLang()
  if (sites.state === 'loading') {
    return (
      <div aria-busy="true">
        <ul className="pw-ov-sites pw-ov-sites--loading" aria-hidden="true">
          {Array.from({ length: 7 }, (_, i) => <li key={i} className="pw-ov-site-card"><span /><span /></li>)}
        </ul>
        <p className="pw-ov-loading">{t('overview.state.sites_loading')}</p>
      </div>
    )
  }
  if (sites.state === 'error') {
    return (
      <ErrorState error={sites.error?.error} endpoint={sites.error?.endpoint} onRetry={onRetry} title={t('overview.state.sites_error')} level={3} />
    )
  }
  if (sites.state === 'empty') {
    return <EmptyState level={3} icon="grid" title={t('overview.sites_heading')} body={renderMessage(t, sites.empty)} />
  }
  return (
    <>
      <Notes notes={sites.notes} />
      <ul className="pw-ov-sites" role="list">
        {sites.items.map((s) => (
          <li key={s.id} className="pw-ov-site-card" data-site={s.id}>
            <RouteLink to={s.href} className="pw-ov-site-name" lang="en">{s.name}</RouteLink>
            <span className="pw-chips">{s.chips.map((c) => <StatusChip key={c.key} chip={c} />)}</span>
            <p className="pw-ov-site-date">
              <span className="pw-label">{t('overview.sites.date_label')}</span>
              <Value value={s.date.raw} spec={s.date.spec} source={s.source} />
            </p>
          </li>
        ))}
      </ul>
    </>
  )
}

/** The page body for a model (no fetching), so it renders under test. */
export function OverviewView({ model, onRetry = {} }) {
  const { t } = useLang()
  return (
    <div className="pw-page pw-overview">
      <PageHeader
        eyebrow={t('overview.eyebrow')}
        title={t('nav.overview')}
        lede={t('overview.lede')}
        actions={(
          <RouteLink to="/map" className="pw-btn">
            {t('overview.open_map')}
            <Icon name="arrow-right" size={16} strokeWidth={1.9} />
          </RouteLink>
        )}
      />

      <StatusBanner banner={model.banner} />

      <section className="pw-section" aria-labelledby="ov-facts">
        <h2 className="pw-section-title" id="ov-facts">{t('overview.facts_heading')}</h2>
        <div className="pw-grid">
          {model.facts.map((card) => (
            <FactCard key={card.id} card={card} onRetry={card.id === 'sites' ? onRetry.summary : onRetry.raster} />
          ))}
        </div>
      </section>

      <section className="pw-section" aria-labelledby="ov-scene">
        <h2 className="pw-section-title" id="ov-scene">{t('overview.scene_heading')}</h2>
        <div className="pw-grid">
          <LineCard block={model.latestScene} id="latest_scene" labelKey="overview.scene_label" serverLabelKey="overview.server_reason" onRetry={onRetry.raster} />
          <LineCard block={model.poll} id="poll" labelKey="overview.poll_label" serverLabelKey="overview.server_error" onRetry={onRetry.raster} />
        </div>
      </section>

      <section className="pw-section" aria-labelledby="ov-map">
        <h2 className="pw-section-title" id="ov-map">{t('overview.map_heading')}</h2>
        <OverviewMapPreview preview={model.preview} onRetry={onRetry.raster} onRetryPins={onRetry.highlights} />
      </section>

      <section className="pw-section" aria-labelledby="ov-sites">
        <h2 className="pw-section-title" id="ov-sites">{t('overview.sites_heading')}</h2>
        <p className="pw-ov-section-lede">{t('overview.sites_lede')}</p>
        <SitesStrip sites={model.sites} onRetry={onRetry.riskMap} />
      </section>
    </div>
  )
}

export default function OverviewPage() {
  const baseline = useBaseline()
  const { reportDisclaimer } = useOutletContext() ?? {}

  const raster = useApi(getRasterScan, [])
  const summary = useApi(getSummary, [])
  const riskMap = useApi(getRiskMap, [])
  const runId = Number.isInteger(raster.data?.run_id) ? raster.data.run_id : null
  const fetchHighlights = useCallback(() => getHighlights({ n: PIN_COUNT, run_id: runId }), [runId])
  const highlights = useApi(fetchHighlights, [runId], { enabled: runId !== null })
  const now = useNow(MINUTE_MS)

  // Asked for but not started yet (the render between the raster arriving
  // and the request effect) is loading, not "failed"; a response kept from
  // an earlier run while the next one loads is not shown.
  const highlightsLoading = runId !== null && (highlights.loading || (!highlights.data && !highlights.error))
  const highlightsData = highlightsLoading ? null : highlights.data

  const model = useMemo(() => buildOverviewModel({
    raster: raster.data,
    summary: summary.data,
    riskMap: riskMap.data,
    highlights: highlightsData,
    baseline,
    now,
    requests: {
      raster: { loading: raster.loading, error: raster.error },
      summary: { loading: summary.loading, error: summary.error },
      riskMap: { loading: riskMap.loading, error: riskMap.error },
      highlights: { loading: highlightsLoading, error: highlights.error },
    },
  }), [
    raster.data, raster.loading, raster.error, summary.data, summary.loading, summary.error,
    riskMap.data, riskMap.loading, riskMap.error, highlightsData, highlightsLoading, highlights.error,
    baseline, now,
  ])

  const disclaimerText = model.disclaimer?.text ?? null
  const disclaimerEndpoint = model.disclaimer?.endpoint ?? null
  useEffect(() => {
    reportDisclaimer?.(disclaimerText, disclaimerEndpoint)
  }, [reportDisclaimer, disclaimerText, disclaimerEndpoint])

  const onRetry = useMemo(() => ({
    raster: raster.refetch, summary: summary.refetch, riskMap: riskMap.refetch, highlights: highlights.refetch,
  }), [raster.refetch, summary.refetch, riskMap.refetch, highlights.refetch])

  return <OverviewView model={model} onRetry={onRetry} />
}
