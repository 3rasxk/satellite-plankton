/**
 * Segmented: the iOS-style segmented control (a grey track; the selected
 * segment is a white pill with a small shadow) used for the map layer, the
 * number of pins and every tab row.
 *
 * Two semantics, one look:
 *   - `kind="toggle"` (default): a labelled group of buttons with
 *     `aria-pressed` -- for choices that change a view (layer, pin count);
 *   - `kind="tabs"`: a WAI-ARIA tab list -- `role="tab"`, `aria-selected`,
 *     `aria-controls={panelId(value)}`, roving tabindex, and Left/Right/
 *     Home/End move between tabs. The caller renders the matching
 *     `role="tabpanel"` with `id={panelId(value)}`.
 *
 * Data source: none; labels are passed in already translated.
 * Limitations: presentation and keyboard behaviour only.
 */
import { useRef } from 'react'
import { panelId, tabId } from '../../lib/segmentIds.js'

export default function Segmented({
  label, options, value, onChange, kind = 'toggle', idBase = 'seg', className = '', size = 'regular', shield,
}) {
  const listRef = useRef(null)
  const list = Array.isArray(options) ? options : []
  const tabs = kind === 'tabs'
  const enabled = list.filter((o) => !o.disabled)

  const onKeyDown = (event) => {
    if (!tabs) return
    const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End']
    if (!keys.includes(event.key) || enabled.length === 0) return
    event.preventDefault()
    const at = Math.max(0, enabled.findIndex((o) => o.value === value))
    let next = at
    if (event.key === 'ArrowLeft') next = (at - 1 + enabled.length) % enabled.length
    if (event.key === 'ArrowRight') next = (at + 1) % enabled.length
    if (event.key === 'Home') next = 0
    if (event.key === 'End') next = enabled.length - 1
    const target = enabled[next]
    onChange?.(target.value)
    // Focus follows the selection (automatic activation).
    setTimeout(() => {
      listRef.current?.querySelector(`[data-value="${CSS.escape(String(target.value))}"]`)?.focus()
    }, 0)
  }

  const setRef = (el) => {
    listRef.current = el
    if (typeof shield === 'function') shield(el)
  }

  return (
    <div
      ref={setRef}
      className={`pw-seg ${className}`.trim()}
      data-size={size}
      role={tabs ? 'tablist' : 'group'}
      aria-label={label}
      onKeyDown={onKeyDown}
    >
      {list.map((o) => {
        const selected = o.value === value
        const common = {
          type: 'button',
          className: 'pw-seg-btn',
          'data-value': String(o.value),
          disabled: o.disabled || undefined,
          title: o.title,
          'aria-label': o.ariaLabel,
          onClick: () => {
            if (!o.disabled && !selected) onChange?.(o.value)
          },
        }
        return tabs ? (
          <button
            key={o.value}
            {...common}
            role="tab"
            id={tabId(idBase, o.value)}
            aria-selected={selected}
            aria-controls={panelId(idBase, o.value)}
            tabIndex={selected ? 0 : -1}
          >
            {o.label}
          </button>
        ) : (
          <button key={o.value} {...common} aria-pressed={selected}>
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
