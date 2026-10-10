/**
 * PageHeader: the page's single <h1>, an optional eyebrow and lede, and an
 * actions slot (cite, export) aligned to the right on wide screens.
 *
 * Data source: the page's own i18n strings. A string `title` also becomes
 * the document title ("<title> · Plankton Watch"), so each route is
 * distinguishable in tabs, history and screen-reader page announcements.
 */
import { useEffect } from 'react'
import { useLang } from '../../i18n/useLang.js'

export default function PageHeader({ title, lede, eyebrow, actions, children }) {
  const { t } = useLang()

  useEffect(() => {
    if (typeof document !== 'undefined' && typeof title === 'string' && title !== '') {
      document.title = t('page.title', { page: title })
    }
  }, [title, t])

  return (
    <header className="pw-page-head">
      <div className="pw-page-head-text">
        {eyebrow && <p className="pw-eyebrow">{eyebrow}</p>}
        <h1 className="pw-page-title">{title}</h1>
        {lede && <p className="pw-lede">{lede}</p>}
        {children}
      </div>
      {actions && <div className="pw-page-actions">{actions}</div>}
    </header>
  )
}
