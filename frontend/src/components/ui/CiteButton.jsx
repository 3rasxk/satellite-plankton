/**
 * CiteButton: copies a plain-text citation of exactly what is on screen
 * (dashboard spec §5 `CiteButton`).
 *
 * Data source: `buildCitation` (src/lib/citation.js) with the app version
 * and commit (src/lib/buildInfo.js), the raster run and its scene-date
 * span, the TEST baseline version when one is in force, today's UTC date
 * and the permalink (default: the current page URL). Provenance only -- the
 * citation says nothing about what the data show.
 *
 * Behaviour: copies with the Clipboard API, falling back to the legacy copy
 * command; if both fail the citation is shown in a read-only field to copy
 * by hand. The outcome is announced politely (`aria-live`). Never throws.
 */
import { useEffect, useRef, useState } from 'react'
import Icon from '../Icon.jsx'
import { buildCitation } from '../../lib/citation.js'
import { appVersion, gitSha } from '../../lib/buildInfo.js'
import { copyText } from '../../lib/browser.js'
import { useLang } from '../../i18n/useLang.js'

const CONFIRM_MS = 6000

function currentHref() {
  try {
    return typeof window !== 'undefined' ? window.location.href : null
  } catch {
    return null
  }
}

export default function CiteButton({ runId, oldestScene, newestScene, baselineVersion, permalink, className = '' }) {
  const { lang, t } = useLang()
  const [status, setStatus] = useState('idle') // idle | copied | failed
  const [citation, setCitation] = useState('')
  const timer = useRef(null)

  useEffect(() => () => clearTimeout(timer.current), [])

  const onClick = async () => {
    clearTimeout(timer.current)
    setStatus('idle')
    let textValue = ''
    try {
      textValue = buildCitation({
        lang,
        version: appVersion,
        sha: gitSha,
        runId,
        oldestScene,
        newestScene,
        baselineVersion,
        accessedAt: new Date(),
        permalink: typeof permalink === 'string' ? permalink : currentHref(),
      })
    } catch {
      textValue = ''
    }
    setCitation(textValue)
    let ok = false
    try {
      ok = textValue !== '' && (await copyText(textValue))
    } catch {
      ok = false
    }
    setStatus(ok ? 'copied' : 'failed')
    if (ok) timer.current = setTimeout(() => setStatus('idle'), CONFIRM_MS)
  }

  const message = status === 'copied' ? t('cite.copied') : status === 'failed' ? t('cite.failed') : ''
  return (
    <div className={`pw-cite ${className}`.trim()}>
      <button type="button" className="pw-btn" onClick={onClick}>
        <Icon name="quote" size={16} strokeWidth={1.9} />
        {t('action.copy_citation')}
      </button>
      <span className="pw-cite-status" role="status" aria-live="polite">{message}</span>
      {status === 'failed' && citation !== '' && (
        <label className="pw-cite-fallback">
          <span>{t('cite.text_label')}</span>
          <textarea readOnly rows={3} value={citation} onFocus={(event) => event.target.select()} />
        </label>
      )}
    </div>
  )
}
