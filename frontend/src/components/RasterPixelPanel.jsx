/**
 * What one clicked cell of the raster actually holds (the cell inspector,
 * dashboard spec §4.2).
 *
 * Every number here comes from the API, which read it out of the stored
 * blob the overlay was drawn from (backend/src/raster_scan/pixel.py).
 * Nothing is computed in this file: no index is re-derived, no value is
 * inferred from a colour, no z-score is computed, and no reading is
 * invented for a cell that has none. The view model is
 * `buildCellModel` (src/lib/mapModel.js); text is i18n `map.cell.*`.
 *
 * The panel answers in the same three states the overlay paints, because
 * a difference a viewer can see on the map has to be a difference they
 * can read in words:
 *
 *   reading             the four index values (each with its source and a
 *                       link to its definition on /methods), THIS cell's
 *                       own acquisition date and time, the observed pixel
 *                       vs the drawn square's centre, the read scale and
 *                       the one-sampled-pixel statement, the run -- and,
 *                       only when the response carries `anomaly` (TEST
 *                       cell baseline), the anomaly block labelled TEST
 *   not_measured        inside the study area, nothing usable here --
 *                       cloud, land, or no scene covered it. Never shown
 *                       as a number, and never as zero: an unmeasured
 *                       cell downloads as 0.0 and 0.0 is also a real NDCI
 *                       reading, so displaying one for the other is this
 *                       project's cardinal overclaim in words.
 *   outside_study_area  nothing was ever looked at here.
 *
 * Only a state of exactly "reading" produces numbers; every other value,
 * including one this build does not recognise, is shown as unmeasured.
 *
 * Actions (every state): Copy citation, Copy permalink, Download cell CSV
 * (`cellCsv`), Open raw JSON (the exact API request).
 *
 * Bound by the same rule as the legend and the pins: these are index
 * readings, not risk levels (CLAUDE.md §0/§1).
 */
import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import CiteButton from './ui/CiteButton.jsx'
import RouteLink from './ui/RouteLink.jsx'
import SourceChip from './ui/SourceChip.jsx'
import StatusChip from './ui/StatusChip.jsx'
import Value from './ui/Value.jsx'
import { buildCellModel } from '../lib/mapModel.js'
import { copyText, downloadText } from '../lib/browser.js'
import { reasonKey } from '../lib/format.js'
import { useLang } from '../i18n/useLang.js'

const CONFIRM_MS = 6000

/** Copy-permalink button with a polite outcome and a selectable fallback. */
function CopyPermalink({ permalink }) {
  const { t } = useLang()
  const [status, setStatus] = useState('idle')
  const [link, setLink] = useState('')
  const timer = useRef(null)
  useEffect(() => () => clearTimeout(timer.current), [])

  const onClick = async () => {
    clearTimeout(timer.current)
    let href = ''
    try {
      href = typeof permalink === 'function' ? permalink() : typeof permalink === 'string' ? permalink : ''
    } catch {
      href = ''
    }
    setLink(href)
    let ok = false
    try {
      ok = href !== '' && (await copyText(href))
    } catch {
      ok = false
    }
    setStatus(ok ? 'copied' : 'failed')
    if (ok) timer.current = setTimeout(() => setStatus('idle'), CONFIRM_MS)
  }

  const message = status === 'copied' ? t('map.actions.permalink_copied') : status === 'failed' ? t('map.actions.permalink_failed') : ''
  return (
    <div className="pw-map-copy">
      <button type="button" className="pw-btn pw-btn--quiet pw-btn--small" onClick={onClick}>
        <Icon name="external" size={14} strokeWidth={2} />
        {t('action.copy_permalink')}
      </button>
      <span className="pw-cite-status" role="status" aria-live="polite">{message}</span>
      {status === 'failed' && link !== '' && (
        <label className="pw-cite-fallback">
          <span>{t('map.actions.permalink_label')}</span>
          <input type="text" readOnly value={link} onFocus={(event) => event.target.select()} />
        </label>
      )}
    </div>
  )
}

/**
 * The inspector's action row, shared by the cell and pin inspectors.
 * `citation` = CiteButton props; `permalink` = () => absolute URL; `csv` =
 * `{filename, content, labelKey}`; `rawUrl` = the API request; `children`
 * are extra buttons placed first (e.g. Zoom to cell).
 */
export function InspectorActions({ citation, permalink, csv, rawUrl, children }) {
  const { t } = useLang()
  const onCsv = () => {
    try {
      const content = typeof csv.content === 'function' ? csv.content() : csv.content
      downloadText(csv.filename, content)
    } catch {
      // Never throw from a click handler; the raw JSON stays available.
    }
  }
  return (
    <div className="pw-map-actions" role="group" aria-label={t('map.actions.label')}>
      {children}
      <CiteButton className="pw-map-cite" {...(citation ?? {})} permalink={typeof permalink === 'function' ? safeCall(permalink) : undefined} />
      <CopyPermalink permalink={permalink} />
      {csv && (
        <button type="button" className="pw-btn pw-btn--quiet pw-btn--small" onClick={onCsv}>
          <Icon name="download" size={14} strokeWidth={2} />
          {t(csv.labelKey ?? 'action.download_csv')}
        </button>
      )}
      {typeof rawUrl === 'string' && rawUrl !== '' && (
        <a className="pw-btn pw-btn--quiet pw-btn--small" href={rawUrl} target="_blank" rel="noopener noreferrer">
          <Icon name="external" size={14} strokeWidth={2} />
          {t('action.open_raw_json')}
        </a>
      )}
    </div>
  )
}

function safeCall(fn) {
  try {
    const out = fn()
    return typeof out === 'string' ? out : undefined
  } catch {
    return undefined
  }
}

/** One labelled value with its source chip. */
function Field({ label, value, source, reasonText, showReason = false, children }) {
  return (
    <div className="pw-map-field">
      <dt>{label}</dt>
      <dd>
        <Value value={value.raw} spec={value.spec} source={source} reasonText={reasonText} showReason={showReason} />
        {children}
      </dd>
    </div>
  )
}

function Coordinate({ label, coord }) {
  return (
    <div className="pw-map-field">
      <dt>{label}</dt>
      <dd>
        <Value value={coord.lat.raw} spec={coord.lat.spec} />
        {', '}
        <Value value={coord.lng.raw} spec={coord.lng.spec} source={coord.source} />
      </dd>
    </div>
  )
}

function ServerText({ labelKey, text }) {
  const { t } = useLang()
  if (!text) return null
  return (
    <div className="pw-map-server">
      <p className="pw-label">{t(labelKey)}</p>
      <blockquote className="pw-server-text" lang="en">{text}</blockquote>
    </div>
  )
}

/** The TEST anomaly block of a cell (present only when `anomaly != null`). */
function CellAnomaly({ anomaly }) {
  const { t } = useLang()
  const reasonLabel = anomaly.reason
    ? (reasonKey(anomaly.reason) ? t(reasonKey(anomaly.reason)) : anomaly.reason)
    : null
  return (
    <section className="pw-map-block pw-map-test-block" data-test-block="true">
      <h3 className="pw-map-block-title">{t('map.anomaly.heading')}</h3>
      <p className="pw-map-chips"><StatusChip chip={anomaly.chip} /></p>
      <dl className="pw-map-fields">
        {anomaly.rows.map((row) => (
          <Field
            key={row.id}
            label={t(row.labelKey)}
            value={row.value}
            source={row.source}
            showReason={row.id === 'robust_z'}
          />
        ))}
        {anomaly.reason && (
          <div className="pw-map-field">
            <dt>{t('map.anomaly.reason')}</dt>
            <dd><code className="pw-mono">{anomaly.reason}</code>{reasonLabel && reasonLabel !== anomaly.reason ? ` — ${reasonLabel}` : ''}</dd>
          </div>
        )}
        <div className="pw-map-field">
          <dt>{t('map.anomaly.season_key')}</dt>
          <dd><code className="pw-mono">{anomaly.seasonKey}</code></dd>
        </div>
        <div className="pw-map-field">
          <dt>{t('map.anomaly.baseline_version')}</dt>
          <dd><code className="pw-mono">{anomaly.baselineVersion}</code></dd>
        </div>
      </dl>
      {anomaly.bands ? (
        <>
          <p className="pw-label">{t('map.pin.bands')}</p>
          <dl className="pw-map-fields pw-map-fields--3">
            {anomaly.bands.map((b) => <Field key={b.id} label={t(b.labelKey)} value={b.value} source={b.source} />)}
          </dl>
        </>
      ) : null}
      <p className="pw-map-note">{t('map.anomaly.note')}</p>
    </section>
  )
}

function PixelBody({ model }) {
  const { t } = useLang()
  if (model.state === 'outside') {
    return <p className="raster-pixel-note">{t('map.cell.outside')}</p>
  }

  // Anything that is not positively a reading is drawn as "not measured".
  if (model.state !== 'reading') {
    return (
      <>
        <p className="raster-pixel-note">
          {t('map.cell.not_measured')}{' '}
          <strong>{t('map.cell.not_measured_strong')}</strong>
        </p>
        <p className="raster-pixel-note">{t('map.cell.not_measured_causes')}</p>
      </>
    )
  }

  return (
    <>
      <dl className="raster-pixel-values">
        {model.indices.map((row) => (
          <div className="raster-pixel-value" key={row.id}>
            <dt><RouteLink to={row.href} className="pw-map-index-link">{row.label}</RouteLink></dt>
            <dd className="mono">
              <Value
                value={row.value.raw}
                spec={row.value.spec}
                source={row.source}
                reasonText={row.unreadable ? t('map.cell.unreadable') : undefined}
                showReason={row.unreadable}
              />
            </dd>
          </div>
        ))}
      </dl>

      <dl className="pw-map-fields">
        <Field label={t('map.cell.acquired_date')} value={model.acquiredDate.value} source={model.acquiredDate.source} />
        <Field label={t('map.cell.acquired_at')} value={model.acquiredAt.value} source={model.acquiredAt.source} />
        <Coordinate label={t('map.cell.cell')} coord={model.cell} />
        <Coordinate label={t('map.cell.centre')} coord={model.centre} />
        <Field label={t('map.cell.scale')} value={model.scale.value} source={model.scale.source} />
      </dl>

      <p className="raster-pixel-note">{t(model.scale.note.key, model.scale.note.params)}</p>

      {model.anomaly
        ? <CellAnomaly anomaly={model.anomaly} />
        : <p className="raster-pixel-note">{t('map.cell.no_anomaly')}</p>}
    </>
  )
}

/**
 * @param {{pixel, loading, error, onClose, citation?, permalink?}} props
 *   `citation`: CiteButton props (runId, oldestScene, newestScene,
 *   baselineVersion); `permalink`: () => absolute URL of this view.
 */
export default function RasterPixelPanel({ pixel, loading, error, onClose, citation, permalink }) {
  const { t } = useLang()
  if (!loading && !error && !pixel) return null
  const model = !loading && !error ? buildCellModel(pixel) : null
  const status = error?.response?.status
  const detail = error?.response?.data?.detail

  return (
    <div className="raster-pixel-panel glass" role="region" aria-label={t('map.cell.region')}>
      <div className="raster-pixel-head">
        <span className="raster-pixel-title">{t('map.cell.title')}</span>
        {onClose && (
          <button type="button" className="raster-pixel-close" onClick={onClose} aria-label={t('common.close')}>
            ×
          </button>
        )}
      </div>

      {loading && <p className="raster-pixel-note">{t('map.cell.loading')}</p>}

      {error && (
        <>
          <p className="raster-pixel-note">
            {t('map.cell.error')} <strong>{t('map.cell.error_strong')}</strong> {t('map.cell.error_rest')}
          </p>
          {(Number.isInteger(status) || typeof detail === 'string') && (
            <p className="raster-pixel-note">
              {Number.isInteger(status) && <span className="pw-mono">{t('error.http', { status })}</span>}
              {typeof detail === 'string' && detail !== '' && (
                <> · <span lang="en">{detail}</span></>
              )}
            </p>
          )}
        </>
      )}

      {model && (
        <>
          <p className="pw-map-chips">
            <StatusChip chip={model.chip} />
            <span className="pw-map-run">
              {t('common.run')} <span className="pw-mono">{model.runId}</span>
              <SourceChip source={model.runSource} />
            </span>
          </p>
          <PixelBody model={model} />
          <ServerText labelKey="map.cell.meaning" text={model.meaning} />
          <InspectorActions
            citation={citation}
            permalink={permalink}
            csv={{ ...model.csv, labelKey: 'map.cell.download_csv' }}
            rawUrl={model.rawUrl}
          />
        </>
      )}
    </div>
  )
}
