import type { ReactNode } from 'react'
import { Activity, BellRing, Boxes, CircleGauge, Radio, Settings } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { useDashboard } from '../../context/DashboardContext'
import { useSettings } from '../../context/SettingsContext'
import { DemoControls } from '../demo/DemoControls'

const links = [
  { to: '/', label: 'Overview', icon: CircleGauge },
  { to: '/models', label: 'Models', icon: Boxes },
  { to: '/incidents', label: 'Incidents', icon: BellRing },
  { to: '/events', label: 'Events', icon: Radio },
]

export function AppShell({ children }: { children: ReactNode }) {
  const { connection } = useDashboard()
  const { settings } = useSettings()
  const { name, environmentLabel } = settings.workspace
  const connectionLabel = connection === 'demo' ? 'Demo mode' : connection === 'connected' ? 'API connected' : 'API offline'
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark"><Activity size={17} /></span><span>DriftZero</span></div>
        <nav aria-label="Primary navigation">
          {links.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              <Icon size={17} strokeWidth={1.8} /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="connection-pill"><span className={`status-dot ${connection}`} /> {connectionLabel}</div>
          <NavLink to="/settings" className={({ isActive }) => isActive ? 'nav-link settings-link active' : 'nav-link settings-link'}><Settings size={17} /><span>Settings</span></NavLink>
          <div className="workspace"><span>{name.slice(0, 2).toUpperCase()}</span><div><strong>{name}</strong><small>{environmentLabel}</small></div></div>
        </div>
      </aside>
      <main className="main-content">{children}<DemoControls /></main>
    </div>
  )
}
