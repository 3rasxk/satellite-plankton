/**
 * ErrorState: a data block whose request failed (dashboard spec §10).
 *
 * Data source: the axios error -- `response.status` (shown as HTTP n) and
 * `response.data.detail` (the API's own message, shown verbatim and labelled
 * as server text; a 503 for missing Earth Engine configuration reads exactly
 * as the server wrote it) -- plus the endpoint the block asked
 * (`endpoint`, e.g. '/raster-scan'). No response at all says the server did
 * not answer. A retry button appears when `onRetry` is given.
 *
 * Limitations: describes the failure only; it never implies the data would
 * have been empty, low or normal.
 */
import Icon from '../Icon.jsx'
import { useLang } from '../../i18n/useLang.js'

const HEADING_TAGS = Object.freeze({ 2: 'h2', 3: 'h3', 4: 'h4' })

function detailText(detail) {
  if (typeof detail === 'string') return detail.trim() !== '' ? detail : null
  if (detail === null || detail === undefined) return null
  try {
    return JSON.stringify(detail)
  } catch {
    return null
  }
}

export default function ErrorState({ error, endpoint, onRetry, title, level = 2 }) {
  const { t } = useLang()
  const Heading = HEADING_TAGS[level] ?? 'h2'
  const response = error !== null && typeof error === 'object' ? error.response : null
  const status = Number.isInteger(response?.status) ? response.status : null
  const detail = detailText(response?.data?.detail)
  const noResponse = error !== null && typeof error === 'object' && !response

  return (
    <section className="pw-state" data-kind="error" role="status">
      <span className="pw-state-icon"><Icon name="alert" size={20} strokeWidth={1.7} /></span>
      <div className="pw-state-body">
        <Heading className="pw-state-title">{title ?? t(noResponse ? 'error.unreachable' : 'common.error')}</Heading>
        {(status !== null || endpoint) && (
          <p className="pw-state-facts">
            {status !== null && <span className="pw-mono">{t('error.http', { status })}</span>}
            {endpoint && (
              <span>
                {t('error.request')}: <code className="pw-mono">{`GET ${endpoint}`}</code>
              </span>
            )}
          </p>
        )}
        {noResponse && <p>{t('error.no_response')}</p>}
        {detail && (
          <>
            <p className="pw-label">{t('error.server_detail')}</p>
            <blockquote className="pw-server-text" lang="en">{detail}</blockquote>
          </>
        )}
        {typeof onRetry === 'function' && (
          <div className="pw-state-actions">
            <button type="button" className="pw-btn" onClick={() => onRetry()}>
              <Icon name="refresh" size={16} strokeWidth={1.9} />
              {t('common.retry')}
            </button>
          </div>
        )}
      </div>
    </section>
  )
}
