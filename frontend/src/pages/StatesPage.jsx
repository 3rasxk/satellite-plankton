/**
 * StatesPage (`/states`, development builds only): every loading, error,
 * empty and stale state of the glass restyle, rendered with fixture data
 * for design review -- skeleton, "Couldn't reach the data service" + Retry,
 * no usable observation (cloud), not checked yet, stale reading, the
 * freshness chip in each state, the station-list rows and markers of each
 * kind, the status chips, the colour bar and a station detail panel.
 *
 * Data source: the fixtures below, run through the same model functions
 * as the real pages (src/lib/mapListModel.js, src/lib/sitesModel.js), so
 * the states shown are the states the pages can reach. NOTHING here is a
 * reading, and the page says so. The route is registered only when
 * `import.meta.env.DEV` (src/main.jsx), so production builds do not ship it.
 *
 * Limitations: the station panel's Trend tab asks the real API for the
 * MODIS series at the fixture coordinate (a real point in the upper Gulf).
 */
import { useMemo } from 'react'
import Icon from '../components/Icon.jsx'
import { NdciScaleBar } from '../components/RasterLegend.jsx'
import { SiteDetailPanel } from '../components/MapDetailPanel.jsx'
import EmptyState from '../components/ui/EmptyState.jsx'
import ErrorState from '../components/ui/ErrorState.jsx'
import PageHeader from '../components/ui/PageHeader.jsx'
import StatusChip from '../components/ui/StatusChip.jsx'
import UpdatedChip from '../components/ui/UpdatedChip.jsx'
import Value from '../components/ui/Value.jsx'
import { buildSiteListModel, buildUpdateChip } from '../lib/mapListModel.js'
import { ANOMALY_CHIP_KEYS, STATUS, chipForAnomalyLevel, chipForStatus } from '../lib/statusChip.js'
import { useLang } from '../i18n/useLang.js'

const NOW = Date.parse('2026-10-11T08:00:00Z')
const POLL_OK = { last_poll_ok_at: '2026-10-11T07:35:00Z', last_error: null, last_error_at: null, last_error_kind: null }
const RASTER = { run_id: 1, newest_scene_date: '2026-10-07', latest_scene: null, poll: POLL_OK }

const FIXTURE_FEATURES = [
  ['fx_reading', 'Fixture station A', 'ok', { index_values: { ndci: 0.0612, '2bda': 1.08, '3bda': 0.11, b2_b3_ratio: 0.9 }, actual_date: '2026-10-07', cloud_fraction: 0.02 }],
  ['fx_cloud', 'Fixture station B', 'no_imagery', {}],
  ['fx_unchecked', 'Fixture station C', 'no_data_yet', {}],
  ['fx_stale', 'Fixture station D', 'ok', { stale: true, index_values: { ndci: -0.0201, '2bda': 0.95, '3bda': -0.02, b2_b3_ratio: 0.81 }, actual_date: '2026-09-29', cloud_fraction: 0.1 }],
].map(([id, name, status, over]) => ({
  type: 'Feature',
  geometry: { type: 'Point', coordinates: [100.88, 13.26] },
  properties: {
    site_id: id, name, status, risk_level: null, stale: false, error: null,
    index_values: null, actual_date: null, cloud_fraction: null, fetched_at: '2026-10-10T14:25:49+00:00',
    signal_anomaly_level: null, signal_robust_z: null, signal_anomaly_reason: null,
    true_color_image_url: null, ndci_heatmap_image_url: null, image_status: null,
    ...over,
  },
}))
const RISK_MAP = { type: 'FeatureCollection', features: FIXTURE_FEATURES, baseline: null, disclaimer: 'Fixture disclaimer: not a server response.' }

// Neutral fixture swatches: the real ramp is the API's, never this file's.
const LEGEND = { value: { domain: [-0.05, 0.15], swatches: ['#e5e5ea', '#aeaeb2', '#6e6e73', '#3a3a3c', '#1d1d1f'].map((hex, i) => ({ hex, value: i })) } }

function Block({ title, children }) {
  return (
    <section className="pw-section pw-states-block">
      <h2 className="pw-section-title">{title}</h2>
      <div className="pw-card pw-states-card">{children}</div>
    </section>
  )
}

export default function StatesPage() {
  const { t } = useLang()
  const sites = useMemo(() => buildSiteListModel({ riskMap: RISK_MAP, request: {} }), [])
  const chips = useMemo(() => [
    buildUpdateChip({ raster: null, request: { loading: true }, now: NOW }),
    buildUpdateChip({ raster: RASTER, request: {}, now: NOW }),
    buildUpdateChip({ raster: RASTER, request: {}, now: NOW + 5 * 3600000 }),
    buildUpdateChip({ raster: { ...RASTER, poll: { ...POLL_OK, last_error: 'fixture', last_error_kind: 'fixture', last_error_at: '2026-10-11T07:50:00Z' } }, request: {}, now: NOW }),
    buildUpdateChip({ raster: { ...RASTER, poll: null }, request: {}, now: NOW }),
    buildUpdateChip({ raster: null, request: { error: new Error('fixture') }, now: NOW }),
  ], [])

  return (
    <div className="pw-page pw-states-page">
      <PageHeader eyebrow={t('states.eyebrow')} title={t('states.title')} lede={t('states.lede')} />

      <Block title={t('states.loading')}>
        <div aria-busy="true">
          <span className="pw-skeleton" style={{ width: '60%' }} />
          <span className="pw-skeleton" style={{ width: '90%' }} />
          <span className="pw-skeleton" style={{ width: '40%' }} />
        </div>
        <p className="pw-ov-loading">{t('common.loading')}</p>
      </Block>

      <Block title={t('states.error')}>
        <ErrorState error={{ message: 'Network Error' }} endpoint="/raster-scan" onRetry={() => {}} title={t('states.unreachable_title')} level={3} />
        <ErrorState error={{ response: { status: 503, data: { detail: 'Fixture detail: Earth Engine is not configured on this server.' } } }} endpoint="/raster-scan" onRetry={() => {}} level={3} />
      </Block>

      <Block title={t('states.cloud_title')}>
        <EmptyState title={t('states.cloud_title')} body={t('states.cloud_body')} icon="slash" level={3} />
        <EmptyState title={t('states.not_checked_title')} body={t('states.not_checked_body')} icon="clock" level={3} />
        <EmptyState title={t('states.stale_title')} body={t('states.stale_body')} icon="history" kind="stale" level={3}>
          <StatusChip chip={chipForStatus(STATUS.STALE)} />
        </EmptyState>
      </Block>

      <Block title={t('states.updated')}>
        <div className="pw-states-row">
          {chips.map((c, i) => <UpdatedChip key={i} chip={c} />)}
        </div>
      </Block>

      <Block title={t('states.markers')}>
        <ul className="pw-map-site-list pw-states-sites" role="list">
          {sites.items.map((s) => (
            <li key={s.id}>
              <div className="pw-map-site-row">
                <span className="pw-site-glyph" data-kind={s.kind} aria-hidden="true" />
                <span className="pw-map-site-body">
                  <span className="pw-map-site-name">{s.name}</span>
                  <span className="pw-map-site-meta">
                    {t(`status.${s.primaryChip.key}`)}
                    {s.stale && ` · ${t('status.stale')}`}
                  </span>
                </span>
                <span className="pw-map-site-values"><Value value={s.ndci.raw} spec={s.ndci.spec} /></span>
              </div>
            </li>
          ))}
        </ul>
        <div className="pw-states-row pw-states-markers" aria-hidden="true">
          {['reading', 'no_data', 'not_checked'].map((kind, i) => (
            <span key={kind} className="pw-site-marker" data-kind={kind} data-selected={i === 0 ? 'true' : undefined}>
              <span className="pw-site-dot" />
              <span className="pw-site-label">{`${t('states.fixture')} · ${kind}`}</span>
            </span>
          ))}
          <span className="pw-map-pin" data-shape="square"><span>1</span></span>
          <span className="pw-map-pin" data-shape="diamond"><span>2</span></span>
        </div>
        <p className="pw-map-note"><Icon name="alert" size={12} /> {t('states.fixture')}</p>
      </Block>

      <Block title={t('states.chips')}>
        <div className="pw-states-row">
          {Object.values(STATUS).map((k) => <StatusChip key={k} chip={chipForStatus(k)} />)}
          {ANOMALY_CHIP_KEYS.filter((k) => k.endsWith('_test')).map((k) => (
            <StatusChip key={k} chip={chipForAnomalyLevel(k.replace(/^anomaly_|_test$/g, ''), true)} />
          ))}
        </div>
        <div className="pw-states-scale">
          <NdciScaleBar legend={LEGEND} />
        </div>
      </Block>

      <Block title={t('glass.detail.label')}>
        <div className="pw-states-panel">
          <SiteDetailPanel riskMap={RISK_MAP} riskMapRequest={{ loading: false, error: null }} siteId="fx_reading" methods={null} onClose={() => {}} />
          <SiteDetailPanel riskMap={RISK_MAP} riskMapRequest={{ loading: false, error: null }} siteId="fx_cloud" methods={null} onClose={() => {}} />
        </div>
      </Block>
    </div>
  )
}
