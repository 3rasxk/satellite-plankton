/**
 * SourceChip: the small (i) button next to a number that says where it came
 * from (dashboard spec §5).
 *
 * Data source: a `sourceRef(...)` result (src/lib/provenance.js) --
 * `{endpoint, field, url, rows[]}`. The popover shows exactly those rows
 * (endpoint and query, field path, the value as returned, unit, observation
 * date, run, scene id, formula link) and an "Open raw JSON" link to `url`.
 * Nothing is fabricated: a row the response does not carry is "—", and
 * without a URL there is no raw-JSON link.
 *
 * Interaction: a real <button> (keyboard focusable, `aria-expanded`,
 * accessible name naming the field). Opening moves focus into the popover;
 * Esc or the close button closes it and returns focus to the button; a
 * click outside, tabbing away, scrolling the page or resizing closes it.
 *
 * Placement: the popover stays next to its button in the DOM (so Tab order
 * is natural) but is positioned against the viewport (`position: fixed`,
 * coordinates from the button), so a scrolling table wrapper or a card with
 * hidden overflow cannot clip it. It opens below the button, or above when
 * there is more room there; on narrow screens it is a bottom sheet
 * (stylesheet). Inside an ancestor with a transform/filter (e.g. a glass
 * panel over the map) `fixed` is relative to that ancestor; the measured
 * offset is corrected after the first paint.
 *
 * `headingKey` replaces the popover heading (e.g. a table column's source
 * rather than one value's).
 *
 * `defaultOpen` renders it open (tests, print previews). `SourceRows` is the
 * same row list for inline use (e.g. a provenance table in an inspector).
 */
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import Icon from '../Icon.jsx'
import RouteLink from './RouteLink.jsx'
import { NULL_TEXT } from '../../lib/format.js'
import { useLang } from '../../i18n/useLang.js'

const POPOVER_WIDTH_PX = 360
const EDGE_PX = 16
const GAP_PX = 6
const MIN_ROOM_BELOW_PX = 240

const isObject = (v) => v !== null && typeof v === 'object'
const useClientLayoutEffect = typeof window !== 'undefined' ? useLayoutEffect : useEffect

/** Viewport coordinates for the popover next to `button`. */
function placementFor(button) {
  const rect = button.getBoundingClientRect()
  const vw = window.innerWidth
  const vh = window.innerHeight
  const width = Math.min(POPOVER_WIDTH_PX, vw - 2 * EDGE_PX)
  const left = Math.max(EDGE_PX, Math.min(rect.left - 8, vw - width - EDGE_PX))
  const roomBelow = vh - rect.bottom - GAP_PX - EDGE_PX
  const roomAbove = rect.top - GAP_PX - EDGE_PX
  if (roomBelow >= MIN_ROOM_BELOW_PX || roomBelow >= roomAbove) {
    return { left, top: rect.bottom + GAP_PX, bottom: null, width, maxHeight: Math.max(120, roomBelow) }
  }
  return { left, top: null, bottom: vh - rect.top + GAP_PX, width, maxHeight: Math.max(120, roomAbove) }
}

function placementStyle(p) {
  if (!p) return undefined
  const px = (v) => `${Math.round(v)}px`
  return {
    '--pw-pop-left': px(p.left),
    '--pw-pop-top': p.top === null ? 'auto' : px(p.top),
    '--pw-pop-bottom': p.bottom === null ? 'auto' : px(p.bottom),
    '--pw-pop-w': px(p.width),
    '--pw-pop-max-h': px(p.maxHeight),
  }
}

export function SourceRows({ rows }) {
  const { t } = useLang()
  const list = Array.isArray(rows) ? rows.filter(isObject) : []
  return (
    <dl className="pw-source-rows">
      {list.map((row) => {
        const raw = row.textKey ? t(row.textKey) : row.text
        const value = typeof raw === 'string' && raw !== '' ? raw : NULL_TEXT
        const isNull = value === NULL_TEXT
        return (
          <div className="pw-source-row" data-row={row.id} key={row.id}>
            <dt>{t(row.labelKey)}</dt>
            <dd className={isNull ? 'is-null' : undefined}>
              {row.href && !isNull ? <RouteLink to={row.href}>{value}</RouteLink> : value}
            </dd>
          </div>
        )
      })}
    </dl>
  )
}

export default function SourceChip({ source, defaultOpen = false, className = '', headingKey = 'source.heading' }) {
  const { t } = useLang()
  const ref = isObject(source) ? source : null
  const [open, setOpen] = useState(Boolean(defaultOpen))
  const [placement, setPlacement] = useState(null)
  const wrapRef = useRef(null)
  const buttonRef = useRef(null)
  const popRef = useRef(null)
  const openedByUser = useRef(false)
  const popId = useId()

  const close = useCallback((returnFocus) => {
    setOpen(false)
    if (returnFocus) buttonRef.current?.focus()
  }, [])

  const toggle = () => {
    if (!open && buttonRef.current && typeof window !== 'undefined') setPlacement(placementFor(buttonRef.current))
    openedByUser.current = !open
    setOpen(!open)
  }

  // Correct for an ancestor that makes `fixed` relative to itself, then focus.
  useClientLayoutEffect(() => {
    if (!open || !popRef.current || !buttonRef.current) return
    if (!placement) {
      // Opened without a click (defaultOpen): place it now.
      setPlacement(placementFor(buttonRef.current))
    } else {
      const actual = popRef.current.getBoundingClientRect()
      const dx = actual.left - placement.left
      const dy = placement.top === null ? 0 : actual.top - placement.top
      if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
        setPlacement({ ...placement, left: placement.left - dx, top: placement.top === null ? null : placement.top - dy })
      }
    }
    if (openedByUser.current) {
      openedByUser.current = false
      popRef.current.focus({ preventScroll: true })
    }
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    const inside = (node) => (wrapRef.current && wrapRef.current.contains(node))
    const onPointer = (event) => {
      if (!inside(event.target)) setOpen(false)
    }
    const onKey = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        close(true)
      }
    }
    // A fixed popover would drift from its button when anything scrolls.
    const onScroll = (event) => {
      if (popRef.current && event.target instanceof Node && popRef.current.contains(event.target)) return
      setOpen(false)
    }
    const onResize = () => setOpen(false)
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onResize)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onResize)
    }
  }, [open, close])

  const onBlur = (event) => {
    if (open && wrapRef.current && event.relatedTarget && !wrapRef.current.contains(event.relatedTarget)) setOpen(false)
  }

  const field = ref?.field ?? t('source.unknown_field')
  return (
    <span className={`pw-source ${className}`.trim()} ref={wrapRef} onBlur={onBlur}>
      <button
        type="button"
        ref={buttonRef}
        className="pw-source-btn"
        aria-label={t('source.show', { field })}
        aria-expanded={open}
        aria-controls={open ? popId : undefined}
        onClick={toggle}
      >
        <Icon name="source" size={14} strokeWidth={1.9} />
      </button>
      {open && (
        <div
          className="pw-source-pop"
          id={popId}
          role="dialog"
          aria-label={t(headingKey)}
          tabIndex={-1}
          ref={popRef}
          style={placementStyle(placement)}
        >
          <div className="pw-source-head">
            <span className="pw-source-title">{t(headingKey)}</span>
            <button type="button" className="pw-icon-btn" aria-label={t('common.close')} onClick={() => close(true)}>
              <Icon name="close" size={14} strokeWidth={2} />
            </button>
          </div>
          <SourceRows rows={ref?.rows} />
          {typeof ref?.url === 'string' && ref.url !== '' && (
            <a className="pw-source-raw" href={ref.url} target="_blank" rel="noopener noreferrer">
              {t('action.open_raw_json')}
              <Icon name="external" size={12} strokeWidth={2} />
            </a>
          )}
        </div>
      )}
    </span>
  )
}
