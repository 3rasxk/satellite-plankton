import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
// Single most common Leaflet setup mistake is forgetting this import —
// without it the map renders with misaligned/broken tiles.
import 'leaflet/dist/leaflet.css'
import './styles/tokens.css'
import './styles/global.css'
import App from './App.jsx'
import RiskMapPage from './pages/RiskMapPage.jsx'
import SummaryPage from './pages/SummaryPage.jsx'
import ValidationPage from './pages/ValidationPage.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<RiskMapPage />} />
          <Route path="summary" element={<SummaryPage />} />
          <Route path="validation" element={<ValidationPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
