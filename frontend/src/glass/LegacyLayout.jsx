/**
 * Frame for the pages that are not part of the design's three screens
 * (Methods, Data & limits, Monitoring sites, a site's page): scrollable
 * under the floating top bar, with the truth-boundary footer. Their content
 * is unchanged.
 */
import { Outlet, useOutletContext } from 'react-router-dom'
import TruthFooter from '../components/ui/TruthFooter.jsx'

export default function LegacyLayout() {
  const ctx = useOutletContext()
  const { baseline, disclaimer } = ctx
  return (
    <div className="gl-scroll gl-legacy-scroll">
      <div className="pw-shell" data-layout="page" style={{ minHeight: 0 }}>
        <main id="main" className="pw-main" tabIndex={-1}>
          <Outlet context={ctx} />
        </main>
        <TruthFooter disclaimer={disclaimer} disclaimerSource={baseline.disclaimer ? '/methods' : null} isTest={baseline.isTest} />
      </div>
    </div>
  )
}
