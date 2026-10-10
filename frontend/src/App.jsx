import { useCallback, useMemo, useState } from 'react'
import { Outlet, useLocation, useMatch } from 'react-router-dom'
import NavBar from './components/ui/NavBar.jsx'
import BaselineBanner from './components/ui/BaselineBanner.jsx'
import TruthFooter from './components/ui/TruthFooter.jsx'
import { loadBaseline, useBaseline } from './hooks/useBaseline.js'
import { useLang } from './i18n/useLang.js'

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
        <NavBar />
        <BaselineBanner baseline={baseline} onRetry={() => loadBaseline()} />
        <main id="main" className="pw-main" tabIndex={-1}>
          <Outlet context={outletContext} />
        </main>
      </div>
      <TruthFooter disclaimer={disclaimer} disclaimerSource={disclaimerSource} isTest={baseline.isTest} />
    </div>
  )
}
