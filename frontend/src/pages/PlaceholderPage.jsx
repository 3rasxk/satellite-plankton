/**
 * PlaceholderPage: a clearly labelled stand-in for a route whose page is
 * built in a later step of the dashboard plan (Overview, Sites, Methods,
 * Data & limits), so the shell, routes and language toggle can be checked
 * in a browser now. Each route's later task replaces its element in
 * main.jsx; delete this file when none uses it (plan Task 8).
 *
 * Data source: none. It states that nothing on it is data, so its emptiness
 * cannot be read as "no bloom" or "nothing measured".
 */
import { useParams } from 'react-router-dom'
import Icon from '../components/Icon.jsx'
import EmptyState from '../components/ui/EmptyState.jsx'
import PageHeader from '../components/ui/PageHeader.jsx'
import RouteLink from '../components/ui/RouteLink.jsx'
import { useLang } from '../i18n/useLang.js'

export default function PlaceholderPage({ titleKey }) {
  const { t } = useLang()
  const { siteId } = useParams()
  return (
    <div className="pw-page">
      <PageHeader eyebrow={t('placeholder.eyebrow')} title={t(titleKey)} />
      <EmptyState
        kind="placeholder"
        title={t('placeholder.title')}
        body={t('placeholder.body')}
        action={(
          <RouteLink to="/map" className="pw-btn">
            {t('placeholder.go_map')}
            <Icon name="arrow-right" size={16} strokeWidth={1.9} />
          </RouteLink>
        )}
      >
        {siteId && <p>{t('placeholder.site_label')}: <code className="pw-mono">{siteId}</code></p>}
      </EmptyState>
    </div>
  )
}
