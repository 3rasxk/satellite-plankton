/**
 * MethodsPage (`/methods`): how every number on the dashboard is made,
 * rendered from the values the server's code actually uses (dashboard spec
 * §4.4; test-baseline spec §3-§5, §7, §8).
 *
 * Data source:
 *   - `GET /methods` (MethodsResponse), read once per page load through
 *     useBaseline() (the shell's shared, cached request): data sources,
 *     index definitions with server-computed worked examples, masks and
 *     quality screens, gates and floors, the robust-z statistic, the TEST
 *     baseline status with its Level A self-check base rates, the season
 *     windows, the latest-scene policy, the references and the server
 *     `disclaimer` (reported verbatim to the shell's TruthFooter);
 *   - `GET /raster-scan/highlights?mode=anomaly`, only while a valid TEST
 *     baseline is in force: `baseline.level_b`, the Level B per-cell
 *     baseline summary. Its failure degrades that block only.
 * All view logic is in src/lib/methodsModel.js; this file renders it.
 *
 * Rules: no number, formula or threshold is written here or in the i18n
 * prose -- prose names fields and receives their values as parameters
 * (tests/methods_model.test.js greps this file); server texts are shown
 * verbatim and marked `lang="en"`; long-form prose uses the serif `.prose`
 * class; no risk wording or colour. Anchors: one per section, per index
 * key, plus `#sentinel2`, `#modis`, `#robust_z`, `#baseline` (always
 * present) and, in TEST mode, `#level_a`, `#level_b`. The page scrolls to
 * the URL's hash once the content is there (it loads after the route).
 *
 * Print: the stylesheet hides controls and source buttons and keeps cards
 * whole, so the browser's "Save as PDF" gives a clean document.
 */
import { useCallback, useEffect, useMemo } from 'react'
import { useLocation, useOutletContext } from 'react-router-dom'
import Icon from '../components/Icon.jsx'
import GateTable from '../components/GateTable.jsx'
import IndexCard from '../components/IndexCard.jsx'
import ReferenceList from '../components/ReferenceList.jsx'
import EmptyState from '../components/ui/EmptyState.jsx'
import ErrorState from '../components/ui/ErrorState.jsx'
import PageHeader from '../components/ui/PageHeader.jsx'
import SourceChip from '../components/ui/SourceChip.jsx'
import Value from '../components/ui/Value.jsx'
import { getHighlights } from '../api/client.js'
import { useApi } from '../hooks/useApi.js'
import { loadBaseline, useBaseline } from '../hooks/useBaseline.js'
import { NULL_TEXT, reasonKey } from '../lib/format.js'
import {
  LEVEL_B_PARAMS, buildLevelBModel, buildMethodsModel, wantsLevelB,
} from '../lib/methodsModel.js'
import { renderMessage } from '../lib/overviewModel.js'
import { useLang } from '../i18n/useLang.js'

/** One value of the model: a number/date through Value, a code or list as
 * mono text; both with their source button. */
function ItemValue({ it }) {
  if (it.spec) return <Value value={it.raw} spec={it.spec} source={it.source} />
  return (
    <span className="pw-value">
      <code className="pw-mono">{it.text}</code>
      <SourceChip source={it.source} />
    </span>
  )
}

function Facts({ items }) {
  const { t } = useLang()
  return (
    <dl className="pw-kv">
      {items.map((it) => (
        <div key={it.id} data-row={it.id}>
          <dt>{t(it.labelKey)}</dt>
          <dd><ItemValue it={it} /></dd>
        </div>
      ))}
    </dl>
  )
}

function ServerText({ label, children }) {
  const { t } = useLang()
  if (!children) return null
  return (
    <div className="pw-methods-server">
      <p className="pw-label">{label ?? t('methods.server_note')}</p>
      <p className="pw-server-text" lang="en">{children}</p>
    </div>
  )
}

/** Paragraphs of static explanatory prose (i18n), serif. */
function Prose({ keys, children }) {
  const { t } = useLang()
  return (
    <div className="prose">
      {keys?.map((key) => <p key={key}>{t(key)}</p>)}
      {children}
    </div>
  )
}

function Section({ id, titleKey, children }) {
  const { t } = useLang()
  return (
    <section className="pw-section pw-methods-section" id={id} aria-labelledby={`${id}-heading`}>
      <h2 className="pw-section-title" id={`${id}-heading`}>{t(titleKey)}</h2>
      {children}
    </section>
  )
}

// ------------------------------------------------------------- sections

function Sources({ section }) {
  const { t } = useLang()
  const { sentinel2: s2, modis } = section
  return (
    <Section id={section.id} titleKey={section.titleKey}>
      <Prose keys={['methods.sources.intro']} />
      <div className="pw-cols-2">
        <article className="pw-card pw-methods-source" id={s2.anchor} aria-labelledby="sentinel2-title">
          <h3 className="pw-card-title" id="sentinel2-title">{t('methods.s2.heading')}</h3>
          <Facts items={[s2.collection]} />
          <div className="pw-table-wrap">
            <table className="pw-table pw-band-table">
              <caption>{t('methods.s2.bands_caption')}</caption>
              <thead>
                <tr>
                  <th scope="col">{t('methods.s2.col_band')}</th>
                  <th scope="col" className="num">{t('methods.s2.col_resolution')}</th>
                  <th scope="col" className="num">{t('methods.s2.col_wavelength')}</th>
                </tr>
              </thead>
              <tbody>
                {s2.bands.map((b) => (
                  <tr key={b.band} data-band={b.band}>
                    <th scope="row"><code className="pw-mono">{b.band}</code></th>
                    <td className="num"><Value value={b.resolution.raw} spec={b.resolution.spec} source={b.resolution.source} /></td>
                    <td className="num">
                      {b.wavelengthDocumented
                        ? <Value value={b.wavelength.raw} spec={b.wavelength.spec} source={b.wavelength.source} />
                        : <Value value={null} spec={b.wavelength.spec} source={b.wavelength.source} reasonText={t('methods.wavelength_none')} />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ServerText>{s2.wavelengthsNote}</ServerText>
          <Facts items={s2.facts} />
          <Prose>
            {s2.scaleNote && <p>{renderMessage(t, s2.scaleNote)}</p>}
            {s2.sceneAgeNote && <p>{renderMessage(t, s2.sceneAgeNote)}</p>}
          </Prose>
        </article>

        <article className="pw-card pw-methods-source" id={modis.anchor} aria-labelledby="modis-title">
          <h3 className="pw-card-title" id="modis-title">{t('methods.modis.heading')}</h3>
          <Facts items={[modis.collection, modis.bands, ...modis.facts]} />
          <ServerText>{modis.note}</ServerText>
          <Prose keys={['methods.modis.separate']} />
        </article>
      </div>
    </Section>
  )
}

function Indices({ section }) {
  return (
    <Section id={section.id} titleKey={section.titleKey}>
      <Prose keys={['methods.indices.intro', 'methods.indices.compare']} />
      <div className="pw-index-grid">
        {section.cards.map((card) => <IndexCard key={card.key} card={card} />)}
      </div>
    </Section>
  )
}

function Quality({ section }) {
  const { t } = useLang()
  return (
    <Section id={section.id} titleKey={section.titleKey}>
      <Prose keys={['methods.quality.intro']} />
      <div className="pw-card">
        <h3 className="pw-card-title">{t('methods.quality.masks_heading')}</h3>
        <Facts items={section.masks} />
      </div>
      <Prose keys={['methods.quality.screens_intro']} />
      <div className="pw-cols-2">
        {section.screens.map((s) => (
          <article key={s.id} className="pw-card pw-screen-card" id={`screen-${s.id}`} data-screen={s.id}>
            <header className="pw-index-head">
              <h3 className="pw-card-title">{t(s.titleKey)}</h3>
              {s.labelKey && <span className="pw-role-tag" data-role="not_validated">{t(s.labelKey)}</span>}
            </header>
            {s.rule && (
              <p className="pw-screen-rule">
                <span className="pw-label">{t('methods.quality.rule')}</span>{' '}
                <code className="pw-formula" lang="en">{s.rule}</code>
              </p>
            )}
            <Facts items={s.bands ? [...s.values, s.bands] : s.values} />
            {s.texts.map((x) => <ServerText key={x.id} label={t(x.labelKey)}>{x.text}</ServerText>)}
            <ServerText label={t('methods.quality.status')}>{s.status}</ServerText>
          </article>
        ))}
      </div>
    </Section>
  )
}

function Gates({ section }) {
  const { t } = useLang()
  const st = section.statistic
  return (
    <Section id={section.id} titleKey={section.titleKey}>
      <Prose keys={['methods.gates.why_no_ml', 'methods.gates.why_no_ml_labels']}>
        <p>{renderMessage(t, section.whyNoRisk)}</p>
      </Prose>
      <GateTable rows={section.rows} floors={section.floors} />
      <article className="pw-card pw-methods-stat" id={st.anchor} aria-labelledby="robust_z-title">
        <h3 className="pw-card-title" id="robust_z-title">{t('methods.stat.heading')}</h3>
        {st.formula && (
          <p className="pw-screen-rule">
            <span className="pw-value">
              <code className="pw-formula" lang="en">{st.formula}</code>
              <SourceChip source={st.formulaSource} />
            </span>
          </p>
        )}
        <Facts items={st.values} />
        <Prose>
          <p>{renderMessage(t, st.levels)}</p>
          <p>{t('methods.stat.wide_mad')}</p>
          <p>{t('methods.stat.reasons')}</p>
        </Prose>
        <ServerText>{st.note}</ServerText>
      </article>
    </Section>
  )
}

function LevelB({ levelB, onRetry }) {
  const { t } = useLang()
  let body
  if (levelB.state === 'loading') body = <p className="pw-ov-loading" aria-busy="true">{t('methods.level_b.loading')}</p>
  else if (levelB.state === 'error') {
    body = <ErrorState error={levelB.error} endpoint={levelB.endpoint} onRetry={onRetry} title={t('methods.level_b.error')} level={4} />
  } else if (levelB.state === 'empty') body = <p>{t(levelB.key)}</p>
  else {
    body = (
      <>
        <Facts items={[levelB.season, levelB.months, ...levelB.facts, levelB.signature]} />
        <ServerText label={t('methods.level_b.history_end_rule')}>{levelB.historyEndRule}</ServerText>
        <p className="pw-label">{t('methods.level_b.source', { endpoint: `GET ${levelB.endpoint}`, run: levelB.runId ?? NULL_TEXT })}</p>
      </>
    )
  }
  return (
    <section className="pw-card" id="level_b" aria-labelledby="level_b-title">
      <h3 className="pw-card-title" id="level_b-title">{t('methods.level_b.heading')}</h3>
      <Prose keys={['methods.level_b.intro', 'methods.level_b.no_self_check']} />
      {body}
    </section>
  )
}

function BaseRates({ rates }) {
  const { t } = useLang()
  if (!rates) return <p>{t('methods.rates.none')}</p>
  return (
    <>
      <div className="pw-table-wrap">
        <table className="pw-table pw-rates-table">
          <caption>{t('methods.rates.caption')}</caption>
          <thead>
            <tr>
              <th scope="col">{t('methods.rates.col_bucket')}</th>
              <th scope="col" className="num">{t('methods.rates.col_count')}</th>
            </tr>
          </thead>
          <tbody>
            {rates.counts.map((c) => (
              <tr key={c.id} data-bucket={c.id}>
                <th scope="row">{t(c.labelKey)} <code className="pw-mono">{c.id}</code></th>
                <td className="num"><Value value={c.raw} spec={c.spec} source={c.source} /></td>
              </tr>
            ))}
            {rates.reasons.map((r) => {
              const key = reasonKey(r.code)
              return (
                <tr key={r.id} data-reason={r.code}>
                  <th scope="row" className="pw-rates-reason">
                    {t('methods.rates.because')} {key ? t(key) : null} <code className="pw-mono">{r.code}</code>
                  </th>
                  <td className="num"><Value value={r.raw} spec={r.spec} source={r.source} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <Prose>
        <p>{renderMessage(t, rates.summary)}</p>
        <p><strong>{t('methods.rates.not_accuracy')}</strong></p>
      </Prose>
    </>
  )
}

function Baseline({ section, onRetryLevelB }) {
  const { t } = useLang()
  const b = section.baseline
  if (b.state !== 'test') {
    return (
      <Section id={section.id} titleKey={section.titleKey}>
        <Prose keys={[b.explanationKey]} />
        {b.state === 'invalid' && <ServerText label={t('methods.baseline.reason')}>{b.reason}</ServerText>}
      </Section>
    )
  }
  return (
    <Section id={section.id} titleKey={section.titleKey}>
      <Prose keys={['methods.baseline.what']}>
        <p>{renderMessage(t, b.intro)}</p>
        <p>{t('methods.baseline.levels')}</p>
      </Prose>

      <section className="pw-card" id="level_a" aria-labelledby="level_a-title">
        <h3 className="pw-card-title" id="level_a-title">{t('methods.baseline.level_a_heading')}</h3>
        <Facts items={[b.version, ...b.facts, b.signature]} />
        <Prose keys={['methods.baseline.signature_note']} />

        <h4 className="pw-methods-h4">{t('methods.baseline.season_heading')}</h4>
        {b.seasonRule && (
          <p className="pw-value">
            <span className="pw-label">{t('methods.baseline.season_rule')}</span>{' '}
            <span lang="en">{b.seasonRule}</span>
            <SourceChip source={b.seasonRuleSource} />
          </p>
        )}
        <div className="pw-table-wrap">
          <table className="pw-table pw-season-table">
            <caption>{t('methods.baseline.season_caption')}</caption>
            <thead>
              <tr>
                <th scope="col" className="num">{t('methods.baseline.col_month')}</th>
                <th scope="col">{t('methods.baseline.col_key')}</th>
                <th scope="col">{t('methods.baseline.col_months')}</th>
              </tr>
            </thead>
            <tbody>
              {b.seasonWindows.map((w) => (
                <tr key={w.month.id}>
                  <td className="num"><Value value={w.month.raw} spec={w.month.spec} source={w.month.source} /></td>
                  <td><code className="pw-mono">{w.key}</code></td>
                  <td><ItemValue it={w.months} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h4 className="pw-methods-h4">{t('methods.baseline.support_heading')}</h4>
        <div className="pw-table-wrap">
          <table className="pw-table pw-support-table">
            <caption>{t('methods.baseline.support_caption')}</caption>
            <thead>
              <tr>
                <th scope="col">{t('methods.baseline.col_site')}</th>
                <th scope="col" className="num">{t('methods.baseline.col_support')}</th>
              </tr>
            </thead>
            <tbody>
              {b.perSite.map((s) => (
                <tr key={s.site} data-site={s.site}>
                  <th scope="row"><code className="pw-mono">{s.site}</code></th>
                  <td className="num"><Value value={s.count.raw} spec={s.count.spec} source={s.count.source} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h4 className="pw-methods-h4">{t('methods.rates.heading')}</h4>
        <Prose keys={['methods.rates.intro']} />
        <BaseRates rates={b.rates} />
      </section>

      <LevelB levelB={b.levelB} onRetry={onRetryLevelB} />
    </Section>
  )
}

function LatestScene({ section }) {
  const { t } = useLang()
  return (
    <Section id={section.id} titleKey={section.titleKey}>
      <Prose keys={['methods.scene.unit', 'methods.scene.criterion', 'methods.scene.trigger', 'methods.scene.mosaic']} />
      <div className="pw-card">
        <h3 className="pw-card-title">{t('methods.scene.values_heading')}</h3>
        <Facts items={section.facts} />
      </div>
    </Section>
  )
}

function References({ section }) {
  return (
    <Section id={section.id} titleKey={section.titleKey}>
      <Prose keys={['methods.refs.intro']} />
      <ReferenceList references={section.references} />
    </Section>
  )
}

const SECTION_VIEWS = Object.freeze({
  sources: Sources,
  indices: Indices,
  quality: Quality,
  gates: Gates,
  baseline: Baseline,
  latest_scene: LatestScene,
  references: References,
})

/** The page body for a model (no fetching), so it renders under test. */
export function MethodsView({ model, onRetry, onRetryLevelB, onPrint }) {
  const { t } = useLang()
  const header = (
    <PageHeader
      eyebrow={t('methods.eyebrow')}
      title={t('nav.methods')}
      lede={t('methods.lede')}
      actions={model.state === 'ready' ? (
        <>
          {typeof onPrint === 'function' && (
            <button type="button" className="pw-btn" onClick={onPrint}>
              <Icon name="file" size={16} strokeWidth={1.9} />
              {t('methods.print')}
            </button>
          )}
          <a className="pw-btn pw-btn--quiet" href={model.rawUrl} target="_blank" rel="noopener noreferrer">
            {t('action.open_raw_json')}
            <Icon name="external" size={14} strokeWidth={2} />
          </a>
        </>
      ) : null}
    >
      {model.state === 'ready' && (
        <p className="pw-methods-version">
          <span className="pw-label">{t('methods.api_version')}</span>{' '}
          <span className="pw-value"><code className="pw-mono">{model.apiVersion ?? NULL_TEXT}</code><SourceChip source={model.apiVersionSource} /></span>
        </p>
      )}
    </PageHeader>
  )

  if (model.state === 'loading') {
    return (
      <div className="pw-page pw-methods-page" aria-busy="true">
        {header}
        <p className="pw-ov-loading">{t('methods.loading')}</p>
      </div>
    )
  }
  if (model.state === 'error') {
    return (
      <div className="pw-page pw-methods-page">
        {header}
        <ErrorState error={model.error?.error} endpoint={model.error?.endpoint} onRetry={onRetry} title={t('methods.error')} />
        <EmptyState title={t('methods.error_title')} body={t('methods.error_body')} kind="unknown" />
      </div>
    )
  }

  return (
    <div className="pw-page pw-methods-page" data-test-baseline={model.isTest ? 'true' : 'false'}>
      {header}
      <nav className="pw-methods-toc" aria-labelledby="methods-toc-label">
        <p className="pw-label" id="methods-toc-label">{t('methods.toc')}</p>
        <ol role="list">
          {model.toc.map((s) => <li key={s.id}><a href={`#${s.id}`}>{t(s.titleKey)}</a></li>)}
        </ol>
      </nav>
      <Prose keys={['methods.how_to_read']} />
      {model.sections.map((section) => {
        const View = SECTION_VIEWS[section.id]
        return View ? <View key={section.id} section={section} onRetryLevelB={onRetryLevelB} /> : null
      })}
    </div>
  )
}

/** The baseline hook's `{status, message}` error as the axios-like shape
 * ErrorState reads. */
function asRequestError(error) {
  if (!error) return null
  return Number.isInteger(error.status)
    ? { response: { status: error.status }, message: error.message }
    : { message: error.message }
}

export default function MethodsPage() {
  const { reportDisclaimer } = useOutletContext() ?? {}
  const { hash } = useLocation()
  const baseline = useBaseline()
  const methods = baseline.methods
  const levelBWanted = wantsLevelB(methods)
  const fetchLevelB = useCallback(() => getHighlights(LEVEL_B_PARAMS), [])
  const highlights = useApi(fetchLevelB, [levelBWanted], { enabled: levelBWanted })

  const levelB = useMemo(() => (levelBWanted
    ? buildLevelBModel({ highlights: highlights.data, request: { loading: highlights.loading, error: highlights.error } })
    : null), [levelBWanted, highlights.data, highlights.loading, highlights.error])

  const model = useMemo(() => buildMethodsModel({
    methods,
    request: { loading: baseline.status === 'loading', error: baseline.status === 'error' ? asRequestError(baseline.error) : null },
    levelB,
  }), [methods, baseline.status, baseline.error, levelB])

  const disclaimerText = model.disclaimer?.text ?? null
  const disclaimerEndpoint = model.disclaimer?.endpoint ?? null
  useEffect(() => {
    reportDisclaimer?.(disclaimerText, disclaimerEndpoint)
  }, [reportDisclaimer, disclaimerText, disclaimerEndpoint])

  // The content arrives after the route renders, so the browser's own jump
  // to `#anchor` finds nothing; jump once it is there. getElementById, not
  // querySelector: `#2bda` is a valid id but not a valid CSS selector.
  // Once more when the Level B block settles, since it changes the height
  // of everything above the later sections.
  const ready = model.state === 'ready'
  const levelBState = levelB?.state ?? null
  useEffect(() => {
    const fragment = typeof hash === 'string' ? hash.replace(/^#/, '') : ''
    if (!ready || typeof document === 'undefined' || fragment === '') return
    let id
    try {
      id = decodeURIComponent(fragment)
    } catch {
      return
    }
    document.getElementById(id)?.scrollIntoView({ block: 'start' })
  }, [ready, hash, levelBState])

  const onPrint = useCallback(() => {
    if (typeof window !== 'undefined' && typeof window.print === 'function') window.print()
  }, [])

  return (
    <MethodsView
      model={model}
      onRetry={() => loadBaseline()}
      onRetryLevelB={highlights.refetch}
      onPrint={onPrint}
    />
  )
}
