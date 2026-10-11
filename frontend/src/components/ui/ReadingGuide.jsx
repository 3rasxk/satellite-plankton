/**
 * ReadingGuide: a centred glass sheet over a blurred backdrop with three
 * steps -- what the colours mean (an NDCI index, not a risk level), select
 * a station or pin to see its readings and sources, and these are index
 * readings and a provisional TEST comparison (estimates, not certainties).
 *
 * Data source: i18n `guide.*` only; no API value is shown. The first-visit
 * rule and the step list live in src/lib/guide.js (pure, tested); the shell
 * (src/App.jsx) decides when it opens and remembers that it was seen.
 *
 * Accessibility: `role="dialog"` with `aria-modal`, labelled by its title
 * and described by the current step; focus moves into the sheet on open,
 * Tab/Shift+Tab are trapped inside it, Esc closes it, and focus returns to
 * the element that had it before (the help button when reopened from
 * there). Motion is a short fade that `prefers-reduced-motion` removes.
 */
import { useEffect, useId, useRef, useState } from 'react'
import Icon from '../Icon.jsx'
import { GUIDE_STEPS, clampStep } from '../../lib/guide.js'
import { useLang } from '../../i18n/useLang.js'

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])'

/** The step illustrations: neutral glyphs, never a data or risk colour --
 * the first shows the API-independent idea of a ramp in ink tints only. */
function StepArt({ id }) {
  if (id === 'colours') {
    return (
      <div className="pw-guide-art" aria-hidden="true" data-art="ramp">
        <span className="pw-guide-ramp" />
        <span className="pw-guide-ramp-ends"><span>−</span><span>+</span></span>
      </div>
    )
  }
  if (id === 'select') {
    return (
      <div className="pw-guide-art" aria-hidden="true" data-art="select">
        <span className="pw-guide-pin">1</span>
        <span className="pw-guide-site" />
        <span className="pw-guide-cursor" />
      </div>
    )
  }
  return (
    <div className="pw-guide-art" aria-hidden="true" data-art="estimate">
      <span className="pw-guide-badge">TEST</span>
      <span className="pw-guide-tilde">≈</span>
    </div>
  )
}

export default function ReadingGuide({ open, onClose }) {
  const { t } = useLang()
  const [step, setStep] = useState(0)
  const titleId = useId()
  const bodyId = useId()
  const sheetRef = useRef(null)
  const returnTo = useRef(null)

  // Open: remember where focus was and focus the sheet. (The shell mounts a
  // fresh guide per opening, so it always starts at step 1.)
  useEffect(() => {
    if (!open || typeof document === 'undefined') return undefined
    returnTo.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const id = setTimeout(() => sheetRef.current?.querySelector('.pw-guide-primary')?.focus(), 0)
    return () => {
      clearTimeout(id)
      const back = returnTo.current
      if (back && typeof back.focus === 'function' && document.contains(back)) back.focus()
    }
  }, [open])

  // A step change can disable the focused Back button: keep focus inside.
  useEffect(() => {
    if (!open || typeof document === 'undefined') return
    const sheet = sheetRef.current
    if (sheet && !sheet.contains(document.activeElement)) sheet.querySelector('.pw-guide-primary')?.focus()
  }, [open, step])

  if (!open) return null

  const last = GUIDE_STEPS.length - 1
  const id = GUIDE_STEPS[step]

  const onKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.stopPropagation()
      onClose?.()
      return
    }
    if (event.key !== 'Tab' || !sheetRef.current) return
    const items = [...sheetRef.current.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement)
    if (items.length === 0) return
    const first = items[0]
    const end = items[items.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      end.focus()
    } else if (!event.shiftKey && document.activeElement === end) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <div className="pw-guide-backdrop" onKeyDown={onKeyDown} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.() }}>
      <div
        ref={sheetRef}
        className="pw-guide pw-glass"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
      >
        <div className="pw-guide-head">
          <p className="pw-guide-progress" aria-live="polite">
            {t('guide.progress', { n: String(step + 1), total: String(GUIDE_STEPS.length) })}
          </p>
          <button type="button" className="pw-icon-btn pw-guide-close" onClick={() => onClose?.()} aria-label={t('guide.close')}>
            <Icon name="close" size={16} strokeWidth={2} />
          </button>
        </div>
        <p className="pw-guide-kicker">{t('guide.title')}</p>
        <StepArt id={id} />
        <h2 className="pw-guide-title" id={titleId}>{t(`guide.steps.${id}.title`)}</h2>
        <p className="pw-guide-body" id={bodyId}>{t(`guide.steps.${id}.body`)}</p>
        <ol className="pw-guide-dots" aria-hidden="true">
          {GUIDE_STEPS.map((s, i) => <li key={s} data-current={i === step ? 'true' : 'false'} />)}
        </ol>
        <div className="pw-guide-actions">
          <button
            type="button"
            className="pw-btn pw-btn--quiet"
            disabled={step === 0}
            onClick={() => setStep((s) => clampStep(s, -1))}
          >
            {t('guide.back')}
          </button>
          <button
            type="button"
            className="pw-btn pw-btn--primary pw-guide-primary"
            onClick={() => (step < last ? setStep((s) => clampStep(s, 1)) : onClose?.())}
          >
            {t(step < last ? 'guide.next' : 'guide.done')}
          </button>
        </div>
      </div>
    </div>
  )
}
