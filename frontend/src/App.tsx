import { Navigate, Route, Routes } from 'react-router-dom'
import { NotificationBridge } from './components/common/NotificationBridge'
import { AppShell } from './components/layout/AppShell'
import { DashboardProvider } from './context/DashboardContext'
import { SettingsProvider } from './context/SettingsContext'
import { EventsPage } from './pages/EventsPage'
import { IncidentsPage } from './pages/IncidentsPage'
import { ModelDetailPage } from './pages/ModelDetailPage'
import { ModelsPage } from './pages/ModelsPage'
import { OverviewPage } from './pages/OverviewPage'
import { SettingsPage } from './pages/SettingsPage'

export default function App() {
  return (
    <SettingsProvider>
      <DashboardProvider>
        <NotificationBridge />
        <AppShell>
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/models" element={<ModelsPage />} />
            <Route path="/models/:modelId" element={<ModelDetailPage />} />
            <Route path="/incidents" element={<IncidentsPage />} />
            <Route path="/incidents/:incidentId" element={<IncidentsPage />} />
            <Route path="/events" element={<EventsPage />} />
            <Route path="/settings" element={<Navigate to="/settings/workspace" replace />} />
            <Route path="/settings/:section" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppShell>
      </DashboardProvider>
    </SettingsProvider>
  )
}
