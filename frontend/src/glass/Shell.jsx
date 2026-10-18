/**
 * App shell of the glass UI: the TEST-baseline strip (always visible while
 * the TEST baseline is in force), the floating top bar and the routed page,
 * plus the reading guide.
 *
 * Outlet context (for pages): { baseline, reportDisclaimer, setView,
 * openGuide, riskMapClassified } -- `setView({basemap, selected})` lets the
 * map page tell the shell which basemap/selection is showing, so panels turn
 * solid white over True Color and the controls make room for the right
 * panel.
 *
 * Data source: GET /raster-scan (freshness chip, re-read every 10 minutes),
 * GET /methods via useBaseline().
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import TopBar from './TopBar.jsx'
import GuideSheet from './GuideSheet.jsx'
import { getRasterScan, getRiskMap } from '../api/client.js'
import { useApi } from '../hooks/useApi.js'
import { useBaseline } from '../hooks/useBaseline.js'
import { browserStorage, markGuideSeen, shouldAutoOpenGuide } from '../lib/guide.js'
import { buildUpdateChip } from '../lib/mapListModel.js'

const MINUTE_MS = 60000

export default function Shell() {
  const baseline = useBaseline()
  const { pathname } = useLocation()
  const [view, setViewState] = useState({ basemap: 'true_color', selected: false })
  const setView = useCallback((next) => setViewState((p) => (p.basemap === next.basemap && p.selected === next.selected ? p : next)), [])

  const scan = useApi(getRasterScan, [])
  const risk = useApi(getRiskMap, [])
  const refetchScan = scan.refetch
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), MINUTE_MS)
    const reload = setInterval(() => refetchScan(), 10 * MINUTE_MS)
    return () => { clearInterval(tick); clearInterval(reload) }
  }, [refetchScan])
  const status = useMemo(
    () => buildUpdateChip({ raster: scan.data, request: { loading: scan.loading, error: scan.error }, now }),
    [scan.data, scan.loading, scan.error, now],
  )
  const classified = Array.isArray(risk.data?.features) && risk.data.features.some((f) => f?.properties?.risk_level)

  const [guideOpen, setGuideOpen] = useState(() => shouldAutoOpenGuide(browserStorage()))
  const openGuide = useCallback(() => setGuideOpen(true), [])
  const closeGuide = useCallback(() => { setGuideOpen(false); markGuideSeen(browserStorage()) }, [])

  const [reported, setReported] = useState(null)
  const reportDisclaimer = useCallback((text, endpoint) => {
    setReported((p) => (p && p.pathname === pathname && p.text === text && p.endpoint === endpoint ? p : { pathname, text, endpoint }))
  }, [pathname])
  const ctx = useMemo(
    () => ({ baseline, reportDisclaimer, setView, openGuide, scan, risk }),
    [baseline, reportDisclaimer, setView, openGuide, scan, risk],
  )
  const onMap = pathname === '/' || pathname.startsWith('/map')
  const disclaimer = reported && reported.pathname === pathname ? reported.text : baseline.disclaimer

  return (
    <div className="gl-root" data-basemap={onMap ? view.basemap : 'page'} data-sel={onMap && view.selected ? 'true' : 'false'}>
      <div className="gl-stage">
        <Outlet context={{ ...ctx, disclaimer }} />
        <TopBar status={status} onHelp={openGuide} />
      </div>
      <GuideSheet open={guideOpen} onClose={closeGuide} classified={classified} />
    </div>
  )
}
