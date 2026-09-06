import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { DashboardProvider } from './context/DashboardContext'
import { EventsPage } from './pages/EventsPage'
import { IncidentsPage } from './pages/IncidentsPage'
import { ModelDetailPage } from './pages/ModelDetailPage'
import { ModelsPage } from './pages/ModelsPage'
import { OverviewPage } from './pages/OverviewPage'

export default function App() {
  return (
    <DashboardProvider>
      <AppShell>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/models" element={<ModelsPage />} />
          <Route path="/models/:modelId" element={<ModelDetailPage />} />
          <Route path="/incidents" element={<IncidentsPage />} />
          <Route path="/incidents/:incidentId" element={<IncidentsPage />} />
          <Route path="/events" element={<EventsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
    </DashboardProvider>
  )
}
