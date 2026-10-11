/**
 * UpdatedChip: the top bar's data-freshness chip -- a dot and a short
 * phrase ("Updated 25 min ago"), opening onto the Overview's own poll and
 * latest-scene lines.
 *
 * Data source: `chip` from src/lib/mapListModel.js `buildUpdateChip` over
 * `GET /raster-scan` (`poll`, `latest_scene`), fetched once by the shell.
 * The dot reads "ok" only for a healthy newer-scene poll (last success
 * under 3 h old, no current error); otherwise it is the attention dot and
 * the wording is the Overview banner's ("newer scenes may exist that were
 * not checked"). Nothing here says that no newer scene exists.
 *
 * The dot is system health, never a data colour: it is paired with words
 * (never colour alone) and does not reuse the NDCI ramp or any risk token.
 */
import Icon from '../Icon.jsx'
import RouteLink from './RouteLink.jsx'
import { renderMessage } from '../../lib/overviewModel.js'
import { useLang } from '../../i18n/useLang.js'

export default function UpdatedChip({ chip }) {
  const { t } = useLang()
  if (!chip) return null
  const short = renderMessage(t, chip.short)
  return (
    <details
      className="pw-updated"
      data-tone={chip.tone}
      data-state={chip.state}
      onKeyDown={(event) => {
        // Esc closes the popover and returns focus to its summary.
        if (event.key === 'Escape' && event.currentTarget.open) {
          event.stopPropagation()
          event.currentTarget.open = false
          event.currentTarget.querySelector('summary')?.focus()
        }
      }}
    >
      <summary aria-label={`${t('glass.updated.label')}: ${short}`}>
        <span className="pw-updated-dot" aria-hidden="true" />
        <span className="pw-updated-text">{short}</span>
        <Icon name="chevronDown" size={12} strokeWidth={2} className="pw-updated-caret" />
      </summary>
      <div className="pw-updated-pop" role="note">
        <p className="pw-label">{t('glass.updated.poll_heading')}</p>
        <p>{renderMessage(t, chip.detail)}</p>
        {chip.scene && (
          <>
            <p className="pw-label">{t('glass.updated.scene_heading')}</p>
            <p>{renderMessage(t, chip.scene)}</p>
          </>
        )}
        <RouteLink to="/">{t('glass.updated.more')}</RouteLink>
      </div>
    </details>
  )
}
