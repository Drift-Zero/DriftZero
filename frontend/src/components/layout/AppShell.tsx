import type { ReactNode } from 'react'
import { Activity, ShieldCheck, BellRing, Boxes, CircleGauge, Database, Radio, Settings } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { useDashboard } from '../../context/DashboardContext'
import { useSettings } from '../../context/SettingsContext'
import { DemoControls } from '../demo/DemoControls'

const links = [
  { to: '/', label: 'Overview', icon: CircleGauge },
  { to: '/models', label: 'Models', icon: Boxes },
  { to: '/incidents', label: 'Incidents', icon: BellRing },
  { to: '/events', label: 'Events', icon: Radio },
  { to: '/verification', label: 'Verification', icon: ShieldCheck },
  { to: '/evidence', label: 'Evidence', icon: Database },
]

export function AppShell({ children }: { children: ReactNode }) {
  const { connection } = useDashboard()
  const { settings } = useSettings()
  const { name, environmentLabel } = settings.workspace
  const connectionLabel = connection === 'demo' ? 'Demo mode' : connection === 'connected' ? 'API connected' : 'API offline'
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand" aria-hidden="true"><span className="brand-mark"><Activity size={19} /></span></div>
        <nav aria-label="Primary navigation">
          {links.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} title={label} aria-label={label} className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              <Icon size={17} strokeWidth={1.8} /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <NavLink to="/settings" title="Settings" aria-label="Settings" className={({ isActive }) => isActive ? 'nav-link settings-link active' : 'nav-link settings-link'}><Settings size={18} /><span>Settings</span></NavLink>
          <div className="workspace" title={`${name} · ${environmentLabel}`}><span>{name.slice(0, 2).toUpperCase()}</span></div>
        </div>
      </aside>
      <main className="main-content">
        <header className="shell-topbar">
          <div className="topbar-identity">
            <strong>DriftZero</strong>
            <i />
            <span>{name}</span>
          </div>
          <div className="topbar-status">
            <small>{environmentLabel}</small>
            <div className="connection-pill"><span className={`status-dot ${connection}`} /> {connectionLabel}</div>
          </div>
        </header>
        {children}
        <DemoControls />
      </main>
    </div>
  )
}
