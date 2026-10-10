/**
 * ReferenceList: the literature the methods rest on, exactly as
 * `GET /methods` returns it.
 *
 * Data source: `references[]` (MethodsReference: `id`, `citation`, `doi`,
 * `note`), which the server takes from LIMITATIONS.md. The citation and
 * the note are shown verbatim as server text (English, never re-translated);
 * the DOI is shown as returned and links to doi.org. Nothing is added: no
 * reference appears here that the API did not send.
 *
 * The note says what the reference does NOT license in this project (e.g.
 * its fitted values are not calibration for Sentinel-2 surface reflectance).
 */
import { useLang } from '../i18n/useLang.js'

export default function ReferenceList({ references }) {
  const { t } = useLang()
  const refs = Array.isArray(references) ? references : []
  if (!refs.length) return <p>{t('methods.refs.none')}</p>
  return (
    <ol className="pw-refs" role="list">
      {refs.map((r) => (
        <li key={r.id} id={`ref-${r.id}`} className="pw-ref">
          {r.citation && <p className="pw-ref-citation" lang="en">{r.citation}</p>}
          {r.doi && (
            <p className="pw-ref-doi">
              <span className="pw-label">DOI</span>{' '}
              {r.href
                ? <a href={r.href} target="_blank" rel="noopener noreferrer" className="pw-mono">{r.doi}</a>
                : <code className="pw-mono">{r.doi}</code>}
            </p>
          )}
          {r.note && (
            <>
              <p className="pw-label">{t('methods.refs.note')}</p>
              <p className="pw-server-text" lang="en">{r.note}</p>
            </>
          )}
        </li>
      ))}
    </ol>
  )
}
