/**
 * PinList: the pins of the served run as a keyboard-reachable list in the
 * map rail (dashboard spec §4.6 "a pin list ... for keyboard users (each
 * row focuses the pin)"), and CountsBlock, the plain-words account of how
 * the run's measured cells were assessed (test-baseline spec §6).
 *
 * Data source: `buildPinsModel` / `buildCountsBlock` (src/lib/mapModel.js)
 * over `GET /raster-scan/highlights`. Rows are in the API's rank order; each
 * row is a real <button> (Tab-focusable, Enter/Space select) that selects
 * its pin -- the inspector opens it and the map moves to it -- and reports
 * its state with `aria-pressed`.
 *
 * States are distinct: loading; error with the HTTP status and the
 * server's reason (e.g. 409 `mode_off`) -- never "no pins"; no raster;
 * pins of another run or of an unknown mode (not drawn, said why); empty
 * with the server's reason verbatim; ready.
 *
 * Limitations: labels and layout only; no value here is computed.
 */
import { useId } from 'react'
import Icon from './Icon.jsx'
import PinLegend, { PinBadge } from './PinLegend.jsx'
import StatusChip from './ui/StatusChip.jsx'
import Value from './ui/Value.jsx'
import { renderMessage } from '../lib/overviewModel.js'
import { useLang } from '../i18n/useLang.js'

function Notes({ notes }) {
  const { t } = useLang()
  if (!Array.isArray(notes) || notes.length === 0) return null
  return (
    <ul className="pw-map-notes" role="list">
      {notes.map((n, i) => <li key={`${n.key}-${i}`} data-tone={n.tone}>{renderMessage(t, n)}</li>)}
    </ul>
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

/** The pins request failed: status, server reason and message, verbatim. */
export function PinsError({ error, onRetry }) {
  const { t } = useLang()
  return (
    <div className="pw-map-error" role="status" data-state="error">
      <p>{t('map.pins.error')}</p>
      <p className="pw-state-facts">
        {Number.isInteger(error?.status) && <span className="pw-mono">{t('error.http', { status: error.status })}</span>}
        {error?.endpoint && <span>{t('error.request')}: <code className="pw-mono">{`GET ${error.endpoint}`}</code></span>}
      </p>
      {error?.reason && <p>{t('map.pins.error_reason', { reason: error.reason })}</p>}
      {error?.noResponse && <p>{t('error.no_response')}</p>}
      <ServerText labelKey="error.server_detail" text={error?.message} />
      {typeof onRetry === 'function' && (
        <button type="button" className="pw-btn pw-btn--quiet pw-btn--small" onClick={() => onRetry()}>
          <Icon name="refresh" size={14} strokeWidth={2} />
          {t('common.retry')}
        </button>
      )}
    </div>
  )
}

function CountRow({ row }) {
  const { t } = useLang()
  return (
    <div className="pw-map-count" data-count={row.id} data-group={row.group}>
      <dt>{t(row.labelKey)}</dt>
      <dd>
        <Value
          value={row.value.raw}
          spec={row.value.spec}
          source={row.source}
          reasonText={row.value.isNull && row.nullKey ? t(row.nullKey) : undefined}
          showReason={row.value.isNull && Boolean(row.nullKey)}
        />
      </dd>
    </div>
  )
}

/** How the run's measured cells were assessed, in fixed order and plain
 * words, with the partition check and the quality screens. */
export function CountsBlock({ counts, open = false }) {
  const { t } = useLang()
  if (!counts) return null
  const total = counts.rows.filter((r) => r.group === 'total' || r.group === 'assessable')
  const reasons = counts.rows.filter((r) => r.group === 'reason')
  const condition = counts.rows.filter((r) => r.group === 'condition' || r.group === 'share')
  return (
    <details className="pw-disclosure pw-map-counts" open={open || undefined} data-mode={counts.mode ?? undefined}>
      <summary>{t(counts.headingKey)}</summary>
      <div className="pw-disclosure-body">
        <p className="pw-map-note">{t(counts.introKey)}</p>
        <dl className="pw-map-count-list">
          {total.map((row) => <CountRow key={row.id} row={row} />)}
        </dl>
        {reasons.length > 0 && (
          <>
            <p className="pw-label">{t('map.counts.not_assessable')}</p>
            <dl className="pw-map-count-list pw-map-count-list--indent">
              {reasons.map((row) => <CountRow key={row.id} row={row} />)}
            </dl>
          </>
        )}
        {condition.length > 0 && (
          <>
            <p className="pw-label">{t('map.counts.condition')}</p>
            <dl className="pw-map-count-list pw-map-count-list--indent">
              {condition.map((row) => <CountRow key={row.id} row={row} />)}
            </dl>
          </>
        )}
        {counts.partition && (
          <p className="pw-map-partition" data-ok={counts.partition.ok === null ? 'unknown' : String(counts.partition.ok)} data-tone={counts.partition.message.tone}>
            {renderMessage(t, counts.partition.message)}
          </p>
        )}
        <p className="pw-label">{t('map.counts.quality')}</p>
        <dl className="pw-map-count-list">
          {counts.quality.map((row) => <CountRow key={row.id} row={row} />)}
        </dl>
        <ServerText labelKey="map.counts.quality_note" text={counts.qualityNote} />
      </div>
    </details>
  )
}

/**
 * @param {{pins, selectedRank, onSelect, onRetry}} props  `pins` from
 *   buildPinsModel; `onSelect(rank)` selects a pin.
 */
export default function PinList({ pins, selectedRank = null, onSelect, onRetry }) {
  const { t } = useLang()
  const listId = useId()
  if (!pins) return null

  if (pins.state === 'loading') {
    return <p className="pw-map-loading" aria-busy="true">{t('map.pins.loading')}</p>
  }
  if (pins.state === 'error') return <PinsError error={pins.error} onRetry={onRetry} />
  if (pins.state !== 'ready') {
    return (
      <div className="pw-map-pins-empty" data-state={pins.state}>
        {pins.state === 'empty' && <p>{t('map.pins.none')}</p>}
        <Notes notes={pins.notes} />
        <ServerText labelKey="overview.server_reason" text={pins.serverReason} />
        <CountsBlock counts={pins.counts} />
      </div>
    )
  }

  return (
    <div className="pw-map-pins" data-mode={pins.mode}>
      <PinLegend mode={pins.mode} />
      <ol className="pw-map-pin-list" role="list" aria-label={t('map.pins.list_label')} id={listId}>
        {pins.items.map((p) => {
          const selected = p.rank === selectedRank
          return (
            <li key={p.rank} data-pin={p.rank}>
              <button
                type="button"
                className="pw-map-pin-row"
                aria-pressed={selected}
                aria-label={t('map.pins.select', { rank: p.rank })}
                onClick={() => onSelect?.(p.rank)}
              >
                <PinBadge shape={pins.shape} rank={p.rank} selected={selected} />
                <span className="pw-map-pin-row-body">
                  <span className="pw-map-pin-row-values">
                    <span className="pw-label">NDCI</span>
                    <Value value={p.ndci.raw} spec={p.ndci.spec} />
                    {p.z && (
                      <>
                        <span className="pw-label">robust z</span>
                        <Value value={p.z.raw} spec={p.z.spec} />
                      </>
                    )}
                  </span>
                  <span className="pw-map-pin-row-meta">
                    <Value value={p.date.raw} spec={p.date.spec} />
                    {p.edge && <span className="pw-map-pin-edge">{t('map.pins.edge')}</span>}
                  </span>
                </span>
              </button>
              {p.chip && <StatusChip chip={p.chip} className="pw-map-pin-chip" />}
            </li>
          )
        })}
      </ol>
      <Notes notes={pins.notes} />
      <ServerText labelKey="overview.server_reason" text={pins.serverReason} />
      <p className="pw-map-note">{t('map.pin.caveat')}</p>
      <CountsBlock counts={pins.counts} />
    </div>
  )
}
