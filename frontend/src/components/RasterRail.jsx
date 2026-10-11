/**
 * RasterRail: the raster map's left glass card (dashboard spec §4.2; 2026-10
 * glass restyle) -- a headline from real data ("6 of 7 stations have an
 * index reading", "5 highest-NDCI pins in this scan"), count chips by real
 * categories, the monitoring-station list, the pins (controls, legend entry,
 * keyboard-reachable list, how the cells were assessed) and, folded under
 * "Scan details", the newest-acquisition and newer-scene-check lines as on
 * the Overview, coverage and sampling, the scene-date chart and the run's
 * provenance. The layer switch and the NDCI colour bar live in the map's
 * bottom dock (src/pages/RasterPage.jsx), so the legend is not repeated
 * here.
 *
 * Data source: `GET /raster-scan` (via `buildRailModel`, src/lib/mapModel.js,
 * and RasterScanBanner), `GET /raster-scan/highlights` (via
 * `buildPinsModel`), `GET /risk-map` (via src/lib/mapListModel.js
 * `buildSiteListModel`). Text: i18n `glass.list.*`, `map.*` (the
 * scene/poll lines reuse `overview.scene.*` / `overview.poll.*`, so both
 * pages say the same thing). The chips never name a risk class.
 *
 * Layout: a floating glass card over the map at >= 1024 px (hidden while a
 * station or pin is open in the detail panel); below that a drawer (a
 * bottom drawer under 720 px). The card is outside the Leaflet container,
 * so nothing in it can reach the map's click handler. In drawer mode Esc
 * closes it and focus returns to the opener (the page handles that).
 */
import { useId } from 'react'
import Icon from './Icon.jsx'
import PinList from './PinList.jsx'
import RasterScanBanner from './RasterScanBanner.jsx'
import SceneDateChart from './SceneDateChart.jsx'
import ErrorState from './ui/ErrorState.jsx'
import Segmented from './ui/Segmented.jsx'
import SourceChip from './ui/SourceChip.jsx'
import StatusChip from './ui/StatusChip.jsx'
import Value from './ui/Value.jsx'
import { PIN_N_OPTIONS } from '../lib/mapModel.js'
import { renderMessage } from '../lib/overviewModel.js'
import { useLang } from '../i18n/useLang.js'

function Section({ titleKey, children, id }) {
  const { t } = useLang()
  const headingId = useId()
  return (
    <section className="pw-map-section" aria-labelledby={headingId} data-section={id}>
      <h3 className="pw-map-section-title" id={headingId}>{t(titleKey)}</h3>
      {children}
    </section>
  )
}

function Notes({ notes }) {
  const { t } = useLang()
  if (!Array.isArray(notes) || notes.length === 0) return null
  return (
    <ul className="pw-map-notes" role="list">
      {notes.map((n, i) => <li key={`${n.key}-${i}`} data-tone={n.tone}>{renderMessage(t, n)}</li>)}
    </ul>
  )
}

/** A latest-scene or poll line, as on the Overview. */
function LineBlock({ labelKey, block, serverLabelKey }) {
  const { t } = useLang()
  if (!block) return null
  return (
    <div className="pw-map-line" data-state={block.state} data-tone={block.tone}>
      <p className="pw-map-line-head">
        <span className="pw-label">{t(labelKey)}</span>
        {block.source && block.state !== 'loading' && block.state !== 'error' && <SourceChip source={block.source} />}
      </p>
      <p>{renderMessage(t, block.line)}</p>
      <Notes notes={block.notes} />
      {(block.serverReason || block.serverText) && (
        <>
          <p className="pw-label">{t(serverLabelKey)}</p>
          <blockquote className="pw-server-text" lang="en">{block.serverReason || block.serverText}</blockquote>
        </>
      )}
    </div>
  )
}

function RunProvenance({ run }) {
  const { t } = useLang()
  if (!run || run.state === 'empty') {
    return (
      <>
        <p className="pw-map-note">{t('map.run.none')}</p>
        {run?.serverReason && <blockquote className="pw-server-text" lang="en">{run.serverReason}</blockquote>}
      </>
    )
  }
  return (
    <>
      {run.staleNote && <p className="pw-map-note" data-tone="attention">{renderMessage(t, run.staleNote)}</p>}
      <dl className="pw-map-fields">
        {run.rows.map((row) => (
          <div className="pw-map-field" key={row.id} data-row={row.id}>
            <dt>{t(row.labelKey)}</dt>
            <dd>
              {row.value
                ? <Value value={row.value.raw} spec={row.value.spec} source={row.source} />
                : <><code className="pw-mono">{row.code}</code><SourceChip source={row.source} /></>}
            </dd>
          </div>
        ))}
      </dl>
      {run.sceneIds.length > 0 ? (
        <details className="pw-disclosure pw-map-scene-ids">
          <summary>
            {t('map.run.scene_ids', { n: run.sceneIds.length })}
          </summary>
          <div className="pw-disclosure-body">
            <ul className="pw-map-id-list" role="list">
              {run.sceneIds.map((id) => <li key={id}><code className="pw-mono">{id}</code></li>)}
            </ul>
            <SourceChip source={run.sceneIdsSource} />
          </div>
        </details>
      ) : (
        <p className="pw-map-note">{t('map.run.scene_ids_none')}</p>
      )}
    </>
  )
}

function PinControls({ show, onShow, count, onCount }) {
  const { t } = useLang()
  return (
    <div className="pw-map-pin-controls" role="group" aria-label={t('glass.list.pins_controls')}>
      <label className="pw-map-check">
        <input type="checkbox" checked={show} onChange={(event) => onShow?.(event.target.checked)} />
        <span>{t('map.pins.show')}</span>
      </label>
      <div className="pw-map-count-seg">
        <span className="pw-map-count-label" aria-hidden="true">{t('map.pins.count')}</span>
        <Segmented
          label={t('map.pins.count')}
          options={PIN_N_OPTIONS.map((n) => ({ value: n, label: String(n) }))}
          value={count}
          onChange={(n) => onCount?.(Number(n))}
          className="pw-seg--fill"
        />
      </div>
    </div>
  )
}

/** Count chips by real categories (status vocabulary + the API's TEST
 * anomaly counts), each "icon count label". Never a risk class. */
function CountChips({ chips }) {
  const { t } = useLang()
  if (!Array.isArray(chips) || chips.length === 0) return null
  return (
    <ul className="pw-count-chips" role="list" aria-label={t('glass.list.chips_label')}>
      {chips.map((c) => (
        <li
          key={c.id}
          className="pw-chip pw-count-chip"
          data-count-chip={c.id}
          data-status={c.chip.key}
          data-tone={c.chip.tone}
          data-hatch={c.chip.hatch ? 'true' : 'false'}
        >
          <Icon name={c.chip.icon} size={13} strokeWidth={2} className="pw-chip-icon" />
          <span className="pw-num pw-count-n">{c.count}</span>
          <span className="pw-chip-text">{t(`status.${c.chip.key}`)}</span>
        </li>
      ))}
    </ul>
  )
}

/** The monitoring stations as real buttons (Tab, Enter, Space), in the
 * model's order; the selected one is pressed. */
function SiteList({ sites, selectedId, onSelect, onRetry }) {
  const { t } = useLang()
  if (!sites) return null
  if (sites.state === 'loading') return <p className="pw-map-loading" aria-busy="true">{t('glass.list.headline_loading')}</p>
  if (sites.state === 'error') {
    return <ErrorState error={sites.error?.error} endpoint={sites.error?.endpoint} onRetry={onRetry} title={t('glass.list.sites_error')} level={3} />
  }
  if (sites.state === 'empty') return <p className="pw-map-note">{t('glass.list.headline_empty')}</p>
  return (
    <>
      <p className="pw-map-note">{t(sites.sortedBy === 'anomaly' ? 'glass.list.sorted_anomaly' : 'glass.list.sorted_name')}</p>
      <ul className="pw-map-site-list" role="list" aria-label={t('glass.list.sites_heading')}>
        {sites.items.map((s) => {
          const selected = s.id === selectedId
          return (
            <li key={s.id} data-site={s.id}>
              <button
                type="button"
                className="pw-map-site-row"
                aria-pressed={selected}
                onClick={() => onSelect?.(s.id)}
              >
                <span className="pw-site-glyph" data-kind={s.kind} aria-hidden="true" />
                <span className="pw-map-site-body">
                  <span className="pw-map-site-name">{s.name}</span>
                  <span className="pw-map-site-meta">
                    {t(`status.${s.primaryChip.key}`)}
                    {s.stale && ` · ${t('status.stale')}`}
                    {!s.onMap && ` · ${t('glass.list.no_position')}`}
                  </span>
                </span>
                <span className="pw-map-site-values">
                  <span className="pw-map-site-value"><span className="pw-label">NDCI</span><Value value={s.ndci.raw} spec={s.ndci.spec} /></span>
                  {s.anomaly.shown && (
                    <span className="pw-map-site-value"><span className="pw-label">z</span><Value value={s.anomaly.z.raw} spec={s.anomaly.z.spec} /></span>
                  )}
                </span>
              </button>
              {s.anomaly.chip && <StatusChip chip={s.anomaly.chip} className="pw-map-site-chip" />}
            </li>
          )
        })}
      </ul>
    </>
  )
}

export default function RasterRail({
  id, open = true, drawer = false, onClose, titleId,
  raster, rasterLoading, rasterError, onRefresh, isTest = false,
  rail, pins, pinCount, onPinCount, showPins = true, onShowPins,
  selectedRank, onSelectPin, onRetryPins, notes,
  sites, headline, countChips, selectedSiteId = null, onSelectSite, onRetrySites,
}) {
  const { t } = useLang()
  const hasRaster = Boolean(raster?.run_id)
  return (
    <aside
      id={id}
      className="pw-map-rail"
      data-open={open ? 'true' : 'false'}
      data-drawer={drawer ? 'true' : 'false'}
      aria-label={t('map.rail.label')}
      hidden={!open}
    >
      <div className="pw-map-rail-scroll">
        <div className="pw-map-rail-head">
          <div className="pw-map-rail-titles">
            <h2 className="pw-map-rail-title" id={titleId} tabIndex={-1}>
              {headline ? renderMessage(t, headline.headline) : t('map.title')}
            </h2>
            {headline?.subline && <p className="pw-map-rail-sub">{renderMessage(t, headline.subline)}</p>}
          </div>
          {onClose && (
            <button type="button" className="pw-icon-btn pw-map-rail-close" onClick={onClose} aria-label={t('map.rail.hide')} aria-controls={id} aria-expanded={open}>
              <Icon name="close" size={16} strokeWidth={2} />
            </button>
          )}
        </div>

        <CountChips chips={countChips} />

        <Notes notes={notes} />

        <Section titleKey="glass.list.sites_heading" id="sites">
          <SiteList sites={sites} selectedId={selectedSiteId} onSelect={onSelectSite} onRetry={onRetrySites} />
        </Section>

        <Section titleKey={pins?.headingKey ?? 'map.rail.pins'} id="pins">
          {hasRaster && <PinControls show={showPins} onShow={onShowPins} count={pinCount} onCount={onPinCount} />}
          <PinList pins={pins} selectedRank={selectedRank} onSelect={onSelectPin} onRetry={onRetryPins} />
        </Section>

        <details className="pw-map-more">
          <summary>{t('glass.list.details')}</summary>
          {!hasRaster && <p className="pw-map-note">{t('map.run.none')}</p>}

          <Section titleKey="map.rail.scene" id="scene">
            <LineBlock labelKey="overview.scene_label" block={rail?.latestScene} serverLabelKey="overview.server_reason" />
            <LineBlock labelKey="overview.poll_label" block={rail?.poll} serverLabelKey="overview.server_error" />
          </Section>

          <Section titleKey="map.rail.coverage" id="coverage">
            <RasterScanBanner
              data={raster}
              loading={rasterLoading}
              error={rasterError}
              onRefresh={onRefresh}
              isTest={isTest}
              compact
            />
          </Section>

          <Section titleKey="map.rail.dates" id="dates">
            <SceneDateChart chart={rail?.chart} figureNumber={1} />
          </Section>

          <Section titleKey="map.rail.provenance" id="provenance">
            <RunProvenance run={rail?.run} />
          </Section>
        </details>
      </div>
    </aside>
  )
}
