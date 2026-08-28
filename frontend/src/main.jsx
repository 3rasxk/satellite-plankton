import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
// Single most common Leaflet setup mistake is forgetting this import —
// without it the map renders with misaligned/broken tiles.
import 'leaflet/dist/leaflet.css'
import './styles/tokens.css'
import './styles/global.css'
import App from './App.jsx'
import OverviewPage from './pages/OverviewPage.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<OverviewPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
