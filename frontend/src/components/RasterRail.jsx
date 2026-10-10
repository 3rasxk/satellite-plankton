/**
 * RasterRail: the raster map's left rail (dashboard spec §4.2) -- layer
 * switcher, legend, pins (controls, legend entry, keyboard-reachable list,
 * how the cells were assessed), the newest-acquisition and newer-scene-check
 * lines as on the Overview, coverage and sampling, the scene-date chart and
 * the run's provenance.
 *
 * Data source: `GET /raster-scan` (via `buildRailModel`, src/lib/mapModel.js,
 * and RasterScanBanner), `GET /raster-scan/highlights` (via
 * `buildPinsModel`). Text: i18n `map.*` (the scene/poll lines reuse
 * `overview.scene.*` / `overview.poll.*`, so both pages say the same thing).
 *
 * Layout: a column beside the map at >= 1024 px, collapsible; below that a
 * drawer over the map (stylesheet; `drawer` says which). The rail is outside
 * the Leaflet container, so nothing in it can reach the map's click handler.
 * In drawer mode Esc closes it and focus returns to the opener (the page
 * handles that).
 */
import { useId } from 'react'
import Icon from './Icon.jsx'
import PinList from './PinList.jsx'
import RasterLayerSwitcher from './RasterLayerSwitcher.jsx'
import { RasterLegendDock } from './RasterLegend.jsx'
import RasterScanBanner from './RasterScanBanner.jsx'
import SceneDateChart from './SceneDateChart.jsx'
import SourceChip from './ui/SourceChip.jsx'
import Value from './ui/Value.jsx'
import { PIN_N_OPTIONS } from '../lib/mapModel.js'
import { renderMessage } from '../lib/overviewModel.js'
import { useLang } from '../i18n/useLang.js'

function Section({ titleKey, children, id }) {
  const { t } = useLang()
  const headingId = useId()
  return (
    <section className="pw-map-section" aria-labelledby={headingId} data-section={id}>
      <h2 className="pw-map-section-title" id={headingId}>{t(titleKey)}</h2>
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
  const countId = useId()
  return (
    <div className="pw-map-pin-controls">
      <label className="pw-map-check">
        <input type="checkbox" checked={show} onChange={(event) => onShow?.(event.target.checked)} />
        <span>{t('map.pins.show')}</span>
      </label>
      <label className="pw-map-select" htmlFor={countId}>
        <span>{t('map.pins.count')}</span>
        <select id={countId} value={count} onChange={(event) => onCount?.(Number(event.target.value))}>
          {PIN_N_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </label>
    </div>
  )
}

export default function RasterRail({
  id, open = true, drawer = false, onClose,
  raster, rasterLoading, rasterError, onRefresh, isTest = false,
  layerMode, onLayerChange, rail, pins, pinCount, onPinCount, showPins = true, onShowPins,
  selectedRank, onSelectPin, onRetryPins, notes,
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
      <div className="pw-map-rail-head">
        <span className="pw-map-rail-title">{t('map.title')}</span>
        {onClose && (
          <button type="button" className="pw-icon-btn pw-map-rail-close" onClick={onClose} aria-label={t('map.rail.hide')} aria-controls={id} aria-expanded={open}>
            <Icon name="close" size={16} strokeWidth={2} />
          </button>
        )}
      </div>

      <Notes notes={notes} />

      <Section titleKey="map.rail.layers" id="layers">
        <RasterLayerSwitcher
          mode={layerMode}
          onModeChange={onLayerChange}
          trueColorAvailable={Boolean(raster?.true_color_url)}
          t={t}
        />
      </Section>

      <Section titleKey="map.rail.legend" id="legend">
        <RasterLegendDock layerMode={layerMode} legend={raster?.legend} hasRaster={hasRaster} />
        {!hasRaster && <p className="pw-map-note">{t('map.run.none')}</p>}
      </Section>

      <Section titleKey={pins?.headingKey ?? 'map.rail.pins'} id="pins">
        {hasRaster && <PinControls show={showPins} onShow={onShowPins} count={pinCount} onCount={onPinCount} />}
        <PinList pins={pins} selectedRank={selectedRank} onSelect={onSelectPin} onRetry={onRetryPins} />
      </Section>

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
    </aside>
  )
}
