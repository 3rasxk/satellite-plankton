/**
 * BaselineBanner: the full-width strip under the header that says a TEST
 * baseline is in force (test-baseline spec §5; dashboard plan Global
 * Constraints). Shown on every page by the shell.
 *
 * Data source: the `useBaseline()` state (GET /methods -> `baseline`),
 * passed in as `baseline` so the component renders without a network.
 *
 * States:
 *   - valid TEST baseline (`isTest`): the fixed TEST text (i18n
 *     `truth.test_banner`), the baseline version and a link to its method;
 *   - TEST mode switched on but unusable (`mode 'test'`, `valid false`): says
 *     so with the server's reason, verbatim -- never presented as in force;
 *   - the /methods read failed: a quiet note that the baseline mode is
 *     unknown (with a retry when `onRetry` is given);
 *   - mode off, still loading, or no state: nothing.
 * Calm by design: warm neutral paper and an ink hatch, never a warning or
 * risk colour.
 */
import Icon from '../Icon.jsx'
import RouteLink from './RouteLink.jsx'
import { NULL_TEXT } from '../../lib/format.js'
import { useLang } from '../../i18n/useLang.js'

const isObject = (v) => v !== null && typeof v === 'object'

export default function BaselineBanner({ baseline, onRetry }) {
  const { t } = useLang()
  if (!isObject(baseline)) return null

  if (baseline.isTest === true) {
    return (
      <div className="pw-baseline" data-state="test" role="note" aria-label={t('baseline.label')}>
        <div className="pw-container pw-baseline-inner">
          <span className="pw-baseline-badge">{t('baseline.badge')}</span>
          <p className="pw-baseline-text">{t('truth.test_banner')}</p>
          <p className="pw-baseline-meta">
            <span>
              {t('baseline.version')} <code className="pw-mono">{typeof baseline.version === 'string' && baseline.version ? baseline.version : NULL_TEXT}</code>
            </span>
            <RouteLink to="/methods#baseline">{t('baseline.methods_link')}</RouteLink>
          </p>
        </div>
      </div>
    )
  }

  if (baseline.mode === 'test' && baseline.valid === false) {
    return (
      <div className="pw-baseline" data-state="invalid" role="note" aria-label={t('baseline.label')}>
        <div className="pw-container pw-baseline-inner">
          <p className="pw-baseline-text">{t('banner.test_baseline_invalid', { reason: baseline.reason })}</p>
        </div>
      </div>
    )
  }

  if (baseline.status === 'error') {
    return (
      <div className="pw-baseline" data-state="unknown" role="note" aria-label={t('baseline.label')}>
        <div className="pw-container pw-baseline-inner">
          <p className="pw-baseline-text">{t('baseline.unknown')}</p>
          {typeof onRetry === 'function' && (
            <button type="button" className="pw-btn pw-btn--quiet pw-btn--small" onClick={onRetry}>
              <Icon name="refresh" size={14} strokeWidth={2} />
              {t('common.retry')}
            </button>
          )}
        </div>
      </div>
    )
  }

  return null
}
