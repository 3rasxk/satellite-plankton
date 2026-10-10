/**
 * StatusChip: one word-and-icon label from the closed status vocabulary
 * (dashboard spec §5; src/lib/statusChip.js).
 *
 * Data source: a chip descriptor `{key, tone, hatch, icon}` returned by
 * `chipForPixelState`, `chipForSite` or `chipForAnomalyLevel`. This file
 * maps nothing: it shows `status.<key>` from i18n, the glyph named by
 * `icon`, and exposes `tone`/`hatch` as data attributes the stylesheet
 * turns into neutral ink/grey emphasis and a hatched tab.
 *
 * Rules: never colour-only (text + icon always), never a risk colour (the
 * `--risk-*` tokens stay unused), and a missing descriptor reads as "no
 * usable data" -- never as a reading.
 */
import Icon from '../Icon.jsx'
import { chipForPixelState } from '../../lib/statusChip.js'
import { useLang } from '../../i18n/useLang.js'

export default function StatusChip({ chip, className = '' }) {
  const { t } = useLang()
  const c = chip !== null && typeof chip === 'object' && typeof chip.key === 'string' ? chip : chipForPixelState(null)
  return (
    <span
      className={`pw-chip ${className}`.trim()}
      data-status={c.key}
      data-tone={c.tone}
      data-hatch={c.hatch ? 'true' : 'false'}
    >
      <Icon name={c.icon} size={14} strokeWidth={2} className="pw-chip-icon" />
      <span className="pw-chip-text">{t(`status.${c.key}`)}</span>
    </span>
  )
}
