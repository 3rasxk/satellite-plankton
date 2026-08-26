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
import SummaryPage from './pages/SummaryPage.jsx'
import ValidationPage from './pages/ValidationPage.jsx'

// Temporary placeholders for routes whose real pages land in later tasks
// of this plan (Task 5: /ndci, Task 7: /aquaculture) — keeps the app
// buildable and click-through-able at every step.
function NdciStub() {
  return <div className="page"><h1>Sentinel-2 NDCI</h1><p className="no-rules">Coming in Task 5.</p></div>
}
function AquacultureStub() {
  return <div className="page"><h1>พื้นที่เพาะเลี้ยงสัตว์น้ำ</h1><p className="no-rules">Coming in Task 7.</p></div>
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<OverviewPage />} />
          <Route path="ndci" element={<NdciStub />} />
          <Route path="anomaly" element={<SummaryPage />} />
          <Route path="aquaculture" element={<AquacultureStub />} />
          <Route path="reports" element={<ValidationPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
