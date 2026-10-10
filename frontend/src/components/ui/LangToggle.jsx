/**
 * LangToggle: the TH | EN segmented control in the header.
 *
 * Data source: `useLang()` (current language and `setLang`). Each button
 * shows the short code and, for screen readers, the language's own name
 * (autonym, i18n `nav.lang_th`/`nav.lang_en`), so the visible label is part
 * of the accessible name. `aria-pressed` marks the current language; the
 * button's `lang` attribute lets a screen reader pronounce its name in that
 * language.
 */
import { useLang } from '../../i18n/useLang.js'

const OPTIONS = Object.freeze([
  Object.freeze({ code: 'th', short: 'TH', nameKey: 'nav.lang_th' }),
  Object.freeze({ code: 'en', short: 'EN', nameKey: 'nav.lang_en' }),
])

export default function LangToggle() {
  const { lang, setLang, t } = useLang()
  return (
    <div className="pw-lang" role="group" aria-label={t('nav.language')}>
      {OPTIONS.map(({ code, short, nameKey }) => (
        <button
          key={code}
          type="button"
          className="pw-lang-btn"
          aria-pressed={lang === code}
          lang={code}
          onClick={() => {
            if (lang !== code) setLang(code)
          }}
        >
          <span aria-hidden="true">{short}</span>
          <span className="pw-sr-only">{`${t(nameKey)} (${short})`}</span>
        </button>
      ))}
    </div>
  )
}
