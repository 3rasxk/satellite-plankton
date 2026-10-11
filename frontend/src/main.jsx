import { StrictMode, Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
// Single most common Leaflet setup mistake is forgetting this import —
// without it the map renders with misaligned/broken tiles.
import 'leaflet/dist/leaflet.css'
import './styles/tokens.css'
import './styles/global.css'
// The dashboard system (shell, type, cards, chips, print). After global.css
// so it can scope over it; it adds classes and never restyles the map's.
import './styles/dashboard.css'
// Glass layer (2026-10 restyle): tokens-driven surfaces, the top bar, the
// segmented controls and the map's floating panels. Last, so it can scope
// over both sheets above.
import './styles/glass.css'
import App from './App.jsx'
import { LangProvider } from './i18n/LangContext.jsx'
import OverviewPage from './pages/OverviewPage.jsx'
import RasterPage from './pages/RasterPage.jsx'
import SitesPage from './pages/SitesPage.jsx'
import SiteDetailPage from './pages/SiteDetailPage.jsx'
import MethodsPage from './pages/MethodsPage.jsx'
import DataPage from './pages/DataPage.jsx'
import NotFoundPage from './pages/NotFoundPage.jsx'
import LegacyRasterRedirect from './pages/LegacyRasterRedirect.jsx'

// Design-review page of every system state, with fixture data. Development
// builds only: in a production build `import.meta.env.DEV` is false, the
// route is not registered and the page is not bundled.
const StatesPage = import.meta.env.DEV ? lazy(() => import('./pages/StatesPage.jsx')) : null

// Routes (dashboard spec §3). PlaceholderPage marks the pages later plan
// tasks build; each task replaces its route's element here. /raster (the
// map's old address) redirects to /map, keeping its query and hash.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <LangProvider>
        <Routes>
          <Route element={<App />}>
            <Route index element={<OverviewPage />} />
            <Route path="map" element={<RasterPage />} />
            <Route path="raster" element={<LegacyRasterRedirect />} />
            <Route path="sites" element={<SitesPage />} />
            <Route path="sites/:siteId" element={<SiteDetailPage />} />
            <Route path="methods" element={<MethodsPage />} />
            <Route path="data" element={<DataPage />} />
            {StatesPage && (
              <Route path="states" element={<Suspense fallback={null}><StatesPage /></Suspense>} />
            )}
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </LangProvider>
    </BrowserRouter>
  </StrictMode>,
)
