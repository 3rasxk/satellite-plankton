/**
 * TruthFooter: the persistent truth-boundary footer on every page
 * (dashboard spec §2 point 6).
 *
 * Data source:
 *   - the three binding points and the null rule from i18n `truth.*`
 *     (point 3 in its TEST wording while a valid TEST baseline is in force);
 *   - `disclaimer`: the server's `disclaimer` field, shown verbatim and
 *     labelled as server text, never re-translated; `disclaimerSource`
 *     names the endpoint it came with (e.g. '/methods');
 *   - app version and commit from src/lib/buildInfo.js (build-time).
 *
 * Without a disclaimer (nothing loaded yet, backend down) it says none was
 * received rather than inventing one; the three points always show.
 * The server text is English (backend/src/schemas.py DisclaimerMixin), so
 * it is marked `lang="en"` for screen readers on the Thai page.
 */
import { useId } from 'react'
import RouteLink from './RouteLink.jsx'
import { appVersion, gitSha } from '../../lib/buildInfo.js'
import { useLang } from '../../i18n/useLang.js'

export default function TruthFooter({ disclaimer, disclaimerSource, isTest = false }) {
  const { t } = useLang()
  const truthId = useId()
  const serverId = useId()
  const server = typeof disclaimer === 'string' && disclaimer.trim() !== '' ? disclaimer : null
  const source = typeof disclaimerSource === 'string' && disclaimerSource !== '' ? disclaimerSource : null

  return (
    <footer className="pw-footer">
      <div className="pw-container pw-footer-grid">
        <section className="pw-footer-truth" aria-labelledby={truthId}>
          <h2 className="pw-footer-heading" id={truthId}>{t('truth.heading')}</h2>
          <ol className="pw-truth-list" role="list">
            <li>{t('truth.point_1')}</li>
            <li>{t('truth.point_2')}</li>
            <li>{t(isTest ? 'truth.point_3_test' : 'truth.point_3')}</li>
          </ol>
          <p className="pw-truth-null">{t('truth.null_rule')}</p>
        </section>

        <section className="pw-footer-server" aria-labelledby={serverId}>
          <h2 className="pw-footer-heading" id={serverId}>{t('truth.server_disclaimer')}</h2>
          {server ? (
            <>
              <blockquote className="pw-server-text" lang="en">{server}</blockquote>
              {source && <p className="pw-footer-note">{t('truth.disclaimer_source', { endpoint: `GET ${source}` })}</p>}
            </>
          ) : (
            <p className="pw-footer-note">{t('truth.no_server_disclaimer')}</p>
          )}
        </section>

        <div className="pw-footer-meta">
          <nav className="pw-footer-links" aria-label={t('footer.reproduce')}>
            <RouteLink to="/methods">{t('nav.methods')}</RouteLink>
            <RouteLink to="/data">{t('nav.data')}</RouteLink>
          </nav>
          <span>
            {t('footer.version')} <code className="pw-mono">{appVersion}</code>
            {' · '}
            {t('footer.commit')} <code className="pw-mono">{gitSha}</code>
          </span>
          <span>{t('common.utc')}</span>
        </div>
      </div>
    </footer>
  )
}
