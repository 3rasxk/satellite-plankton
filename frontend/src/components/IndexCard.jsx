/**
 * IndexCard: one spectral index on the Methods page, anchored at its key
 * (`/methods#ndci`, `#2bda`, `#3bda`, `#b2_b3_ratio`).
 *
 * Data source: one `indices[]` entry of `GET /methods` (MethodsIndex),
 * through src/lib/methodsModel.js `indexCard`: name, formula and note as
 * the server wrote them (verbatim, English), the bands with only the
 * wavelengths the API documents, the role, the raster band name, the
 * overlay display domain, and the worked example -- the sample digital
 * numbers of the bands the index uses and the value the server's own index
 * function returned for them. Nothing is computed here.
 *
 * Rules: a wavelength the API does not document is "—" with that reason,
 * never filled in; a null display domain says the index is never rendered
 * on the overlay; the role label is a plain tag, not a status chip and not
 * a colour.
 */
import SourceChip from './ui/SourceChip.jsx'
import Value from './ui/Value.jsx'
import { NULL_TEXT } from '../lib/format.js'
import { useLang } from '../i18n/useLang.js'

export function RoleTag({ role, roleKey }) {
  const { t } = useLang()
  if (!role) return null
  return (
    <span className="pw-role-tag" data-role={role}>
      {roleKey ? t(roleKey) : <code className="pw-mono">{role}</code>}
    </span>
  )
}

function Wavelength({ entry }) {
  const { t } = useLang()
  if (entry.wavelengthDocumented) {
    return <Value value={entry.wavelength.raw} spec={entry.wavelength.spec} source={entry.wavelength.source} />
  }
  return <Value value={null} spec={entry.wavelength.spec} source={entry.wavelength.source} reasonText={t('methods.wavelength_none')} />
}

export default function IndexCard({ card }) {
  const { t } = useLang()
  const titleId = `${card.anchor}-title`
  return (
    <article className="pw-card pw-index-card" id={card.anchor} aria-labelledby={titleId} data-role={card.role ?? undefined}>
      <header className="pw-index-head">
        <h3 className="pw-index-title" id={titleId}>
          <span className="pw-index-symbol">{card.symbol}</span>
          {card.name && <span className="pw-index-name" lang="en">{card.name}</span>}
        </h3>
        <RoleTag role={card.role} roleKey={card.roleKey} />
      </header>

      <dl className="pw-kv">
        <div data-row="formula">
          <dt>{t('methods.index.formula')}</dt>
          <dd>
            <span className="pw-value">
              <code className="pw-formula">{card.formula ?? NULL_TEXT}</code>
              <SourceChip source={card.formulaSource} />
            </span>
          </dd>
        </div>
        <div data-row="bands">
          <dt>{t('methods.index.bands')}</dt>
          <dd>
            <ul className="pw-band-list" role="list">
              {card.bands.map((b) => (
                <li key={b.band}>
                  <code className="pw-mono">{b.band}</code>{' '}
                  <Wavelength entry={b} />
                </li>
              ))}
            </ul>
          </dd>
        </div>
        <div data-row="raster_band">
          <dt>{t(card.rasterBand.labelKey)}</dt>
          <dd>
            <span className="pw-value">
              <code className="pw-mono">{card.rasterBand.text}</code>
              <SourceChip source={card.rasterBand.source} />
            </span>
          </dd>
        </div>
        <div data-row="display_domain">
          <dt>{t('methods.index.domain')}</dt>
          <dd>
            {card.domain ? (
              <span className="pw-value">
                <Value value={card.domain.min.raw} spec={card.domain.min.spec} source={card.domain.min.source} />
                <span aria-hidden="true">{' – '}</span>
                <span className="pw-sr-only">{` ${t('methods.index.to')} `}</span>
                <Value value={card.domain.max.raw} spec={card.domain.max.spec} source={card.domain.max.source} />
              </span>
            ) : (
              <span className="pw-value">
                <span>{t('methods.index.domain_none')}</span>
                <SourceChip source={card.domainSource} />
              </span>
            )}
          </dd>
        </div>
      </dl>

      {card.note && (
        <div className="pw-index-note">
          <p className="pw-label">{t('methods.server_note')}</p>
          <p className="pw-server-text" lang="en">{card.note}</p>
        </div>
      )}

      <figure className="pw-index-example">
        <figcaption className="pw-card-title">{t('methods.index.example_heading')}</figcaption>
        <div className="pw-table-wrap">
          <table className="pw-table pw-example-table">
            <thead>
              <tr>
                {card.example.bands.map((b) => <th key={b.id} scope="col" className="num"><code>{b.band}</code></th>)}
                <th scope="col" className="num">{`${card.symbol} (${t('methods.index.server_value')})`}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                {card.example.bands.map((b) => (
                  <td key={b.id} className="num"><Value value={b.raw} spec={b.spec} source={b.source} /></td>
                ))}
                <td className="num">
                  <Value value={card.example.value.raw} spec={card.example.value.spec} source={card.example.value.source} />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="pw-index-example-how">{t('methods.index.example_how', { formula: card.formula ?? NULL_TEXT })}</p>
        {card.example.note && <p className="pw-server-text" lang="en">{card.example.note}</p>}
      </figure>
    </article>
  )
}
