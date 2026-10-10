/**
 * Value: one API number or date on screen (dashboard spec §5 `Value`).
 *
 * Data source: the value exactly as the API returned it, formatted only by
 * `formatValue` (src/lib/format.js): fixed decimals per kind, U+2212 for
 * negatives, units, ISO dates. Numerals are set in IBM Plex Mono with
 * tabular figures so columns line up.
 *
 * Unknown (null, undefined, NaN, ±Infinity, unparseable) renders "—" and
 * the reason in words: as a tooltip, as visually hidden text for screen
 * readers, or visibly with `showReason`. The reason is the i18n text for a
 * known code (`reason.<code>`); an API code this UI does not know is shown
 * verbatim, never replaced by a guess. A real zero stays "0.000".
 *
 * `source` (a `sourceRef(...)` result) adds a SourceChip.
 * `reasonText` overrides the reason with API free text (shown verbatim).
 */
import SourceChip from './SourceChip.jsx'
import { formatValue, reasonKey } from '../../lib/format.js'
import { useLang } from '../../i18n/useLang.js'

/** "reason text" for a code, keeping any ":detail" the API appended. */
function reasonLabel(code, t) {
  const key = reasonKey(code)
  if (!key) return typeof code === 'string' && code !== '' ? code : t('reason.not_available')
  const detail = code.includes(':') ? code.slice(code.indexOf(':') + 1).trim() : ''
  return detail ? `${t(key)} (${detail})` : t(key)
}

export default function Value({ value, spec, source, reasonText, showReason = false, className = '' }) {
  const { t } = useLang()
  const result = formatValue(value, spec)
  const chip = source ? <SourceChip source={source} /> : null

  if (result.isNull) {
    const reason = typeof reasonText === 'string' && reasonText.trim() !== '' ? reasonText : reasonLabel(result.reason, t)
    const sentence = t('value.unknown', { reason })
    return (
      <span className={`pw-value ${className}`.trim()} data-null="true">
        <span className="pw-null" title={sentence} aria-hidden="true">{result.text}</span>
        {showReason
          ? <span className="pw-null-reason"><span className="pw-sr-only">{`${t('common.unknown')}: `}</span>{reason}</span>
          : <span className="pw-sr-only">{sentence}</span>}
        {chip}
      </span>
    )
  }

  return (
    <span className={`pw-value ${className}`.trim()} data-null="false">
      <span className="pw-num">{result.text}</span>
      {chip}
    </span>
  )
}
