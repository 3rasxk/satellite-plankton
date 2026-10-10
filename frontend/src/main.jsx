import { StrictMode } from 'react'
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
import App from './App.jsx'
import { LangProvider } from './i18n/LangContext.jsx'
import OverviewPage from './pages/OverviewPage.jsx'
import RasterPage from './pages/RasterPage.jsx'
import PlaceholderPage from './pages/PlaceholderPage.jsx'
import NotFoundPage from './pages/NotFoundPage.jsx'
import LegacyRasterRedirect from './pages/LegacyRasterRedirect.jsx'

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
            <Route path="sites" element={<PlaceholderPage titleKey="nav.sites" />} />
            <Route path="sites/:siteId" element={<PlaceholderPage titleKey="nav.sites" />} />
            <Route path="methods" element={<PlaceholderPage titleKey="nav.methods" />} />
            <Route path="data" element={<PlaceholderPage titleKey="nav.data" />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </LangProvider>
    </BrowserRouter>
  </StrictMode>,
)
