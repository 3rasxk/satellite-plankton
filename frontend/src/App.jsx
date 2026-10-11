import { useCallback, useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation, useMatch } from 'react-router-dom'
import NavBar from './components/ui/NavBar.jsx'
import BaselineBanner from './components/ui/BaselineBanner.jsx'
import ReadingGuide from './components/ui/ReadingGuide.jsx'
import TruthFooter from './components/ui/TruthFooter.jsx'
import { getRasterScan } from './api/client.js'
import { useApi } from './hooks/useApi.js'
import { loadBaseline, useBaseline } from './hooks/useBaseline.js'
import { browserStorage, markGuideSeen, shouldAutoOpenGuide } from './lib/guide.js'
import { buildUpdateChip } from './lib/mapListModel.js'
import { useLang } from './i18n/useLang.js'

const MINUTE_MS = 60000
// The freshness chip re-reads /raster-scan (a stored snapshot; no Earth
// Engine call) this often, so a long-open tab does not show an old status.
const STATUS_REFRESH_MS = 10 * MINUTE_MS

/**
 * The dashboard shell around every route: skip link, header with the five
 * nav links and TH|EN toggle, the TEST-baseline strip (whenever
 * `useBaseline().isTest`), the page, and the truth-boundary footer.
 *
 * Layout: `data-layout="map"` on /map -- the header, strip and map fill
 * exactly one viewport height and the footer follows below the fold, so the
 * Leaflet map keeps its full height; every other route is a normal
 * scrolling page with a sticky header.
 *
 * Footer disclaimer: the server's `disclaimer` from GET /methods (fetched
 * once by useBaseline) unless the current page reports the disclaimer of
 * the response it is showing, through the outlet context:
 *   const { reportDisclaimer } = useOutletContext() ?? {}
 *   useEffect(() => reportDisclaimer?.(data?.disclaimer, '/raster-scan'), [data])
 * A report is tied to the path it was made on, so it never follows the
 * reader to another page.
 *
 * Top bar extras (2026-10 glass restyle): the data-freshness chip from
 * `GET /raster-scan` (`poll`, `latest_scene`; src/lib/mapListModel.js
 * `buildUpdateChip`), re-read every 10 minutes, its ages re-computed each
 * minute; and the reading guide (src/components/ui/ReadingGuide.jsx),
 * opened by itself on a first visit only (src/lib/guide.js; without a
 * window there is no storage, so server-rendered markup never contains it)
 * and from the help button.
 */
export default function App() {
  const { t } = useLang()
  const baseline = useBaseline()
  const { pathname } = useLocation()
  const isMap = useMatch('/map') !== null
  const [reported, setReported] = useState(null)

  const reportDisclaimer = useCallback((text, endpoint) => {
    setReported((prev) => (
      prev && prev.pathname === pathname && prev.text === text && prev.endpoint === endpoint
        ? prev
        : { pathname, text, endpoint }
    ))
  }, [pathname])
  const outletContext = useMemo(() => ({ reportDisclaimer, baseline }), [reportDisclaimer, baseline])

  // --- data freshness chip (top bar).
  const scan = useApi(getRasterScan, [])
  const refetchScan = scan.refetch
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), MINUTE_MS)
    const reload = setInterval(() => refetchScan(), STATUS_REFRESH_MS)
    return () => {
      clearInterval(tick)
      clearInterval(reload)
    }
  }, [refetchScan])
  const status = useMemo(
    () => buildUpdateChip({ raster: scan.data, request: { loading: scan.loading, error: scan.error }, now }),
    [scan.data, scan.loading, scan.error, now],
  )

  // --- reading guide: first visit only, reopened from the help button.
  // Read once on mount; without a window (server rendering, tests) storage
  // is null and the guide stays closed.
  const [guideOpen, setGuideOpen] = useState(() => shouldAutoOpenGuide(browserStorage()))
  const [guideKey, setGuideKey] = useState(0)
  const openGuide = useCallback(() => {
    setGuideKey((k) => k + 1)
    setGuideOpen(true)
  }, [])
  const closeGuide = useCallback(() => {
    setGuideOpen(false)
    markGuideSeen(browserStorage())
  }, [])

  const pageReport = reported && reported.pathname === pathname && typeof reported.text === 'string' && reported.text !== ''
    ? reported
    : null
  const disclaimer = pageReport ? pageReport.text : baseline.disclaimer
  const disclaimerSource = pageReport ? pageReport.endpoint : baseline.disclaimer ? '/methods' : null

  const skipToMain = (event) => {
    const main = typeof document !== 'undefined' ? document.getElementById('main') : null
    if (!main) return
    event.preventDefault()
    main.focus()
    main.scrollIntoView({ block: 'start' })
  }

  return (
    <div className="pw-shell" data-layout={isMap ? 'map' : 'page'}>
      <a className="pw-skip" href="#main" onClick={skipToMain}>{t('nav.skip_to_content')}</a>
      <div className="pw-viewport">
        <NavBar status={status} onHelp={openGuide} />
        <BaselineBanner baseline={baseline} onRetry={() => loadBaseline()} />
        <main id="main" className="pw-main" tabIndex={-1}>
          <Outlet context={outletContext} />
        </main>
      </div>
      <TruthFooter disclaimer={disclaimer} disclaimerSource={disclaimerSource} isTest={baseline.isTest} />
      <ReadingGuide key={guideKey} open={guideOpen} onClose={closeGuide} />
    </div>
  )
}
