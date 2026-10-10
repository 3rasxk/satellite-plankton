/**
 * LimitationsList: the content of LIMITATIONS.md summarised in the reader's
 * language, plus the TEST-baseline limits (dashboard spec §4.5 item 4;
 * test-baseline spec §8).
 *
 * Data source: static i18n text, indexed by src/lib/limitationsMap.js (one
 * entry per `##` heading of LIMITATIONS.md; tests/data_model.test.js fails
 * when a heading has no summary). Prose is set in the serif `.prose` class.
 * No numbers are stated here: values are on /methods and in the file.
 *
 * Rules: the wording never presents a risk level except to deny one, and
 * never says a bloom is present or absent (tests/i18n.test.js).
 */
import RouteLink from './ui/RouteLink.jsx'
import { LIMITATIONS_FILE, LIMITATIONS_SECTIONS } from '../lib/limitationsMap.js'
import { useLang } from '../i18n/useLang.js'

export default function LimitationsList() {
  const { t } = useLang()
  return (
    <div className="pw-data-limits">
      <p className="prose">{t('limits.intro')}</p>
      {LIMITATIONS_SECTIONS.map((s) => (
        <article className="pw-card pw-data-limit" key={s.id} id={`limits-${s.id}`} aria-labelledby={`limits-${s.id}-title`}>
          <h3 className="pw-card-title" id={`limits-${s.id}-title`}>{t(s.titleKey)}</h3>
          <p className="pw-label">
            {s.source === LIMITATIONS_FILE
              ? t('limits.summarises', { heading: s.heading, file: LIMITATIONS_FILE })
              : t('limits.from_spec')}
          </p>
          <div className="prose">
            <ul>
              {s.pointKeys.map((k) => <li key={k}>{t(k)}</li>)}
            </ul>
          </div>
        </article>
      ))}
      <p><RouteLink to="/methods">{t('limits.see_methods')}</RouteLink></p>
    </div>
  )
}
