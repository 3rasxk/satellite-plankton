/**
 * NotFoundPage: any URL that is not one of the dashboard's routes (spec §3).
 * Rendered inside the shell, so the header navigation stays available.
 *
 * Data source: the router location only (the requested path, shown as
 * text). No API call.
 */
import { useLocation } from 'react-router-dom'
import Icon from '../components/Icon.jsx'
import PageHeader from '../components/ui/PageHeader.jsx'
import RouteLink from '../components/ui/RouteLink.jsx'
import { useLang } from '../i18n/useLang.js'

export default function NotFoundPage() {
  const { t } = useLang()
  const { pathname } = useLocation()
  return (
    <div className="pw-page">
      <PageHeader
        eyebrow="404"
        title={t('notfound.title')}
        lede={t('notfound.body', { path: pathname })}
        actions={(
          <RouteLink to="/" className="pw-btn">
            {t('notfound.home')}
            <Icon name="arrow-right" size={16} strokeWidth={1.9} />
          </RouteLink>
        )}
      />
    </div>
  )
}
