import { BellRing,Boxes,Plug,SlidersHorizontal,TerminalSquare,UserRound } from 'lucide-react'
import { NavLink,Navigate,useParams } from 'react-router-dom'
import { AdvancedSection } from '../components/settings/AdvancedSection'
import { AlertsSection } from '../components/settings/AlertsSection'
import { AppearanceSection } from '../components/settings/AppearanceSection'
import { ConnectionSection } from '../components/settings/ConnectionSection'
import { ModelsSection } from '../components/settings/ModelsSection'
import { WorkspaceSection } from '../components/settings/WorkspaceSection'
import { useDashboard } from '../context/DashboardContext'

const sections=[
  {id:'workspace',label:'Workspace',hint:'Identity and operator role',icon:UserRound,render:()=><WorkspaceSection/>},
  {id:'appearance',label:'Appearance',hint:'Density, motion, and formats',icon:SlidersHorizontal,render:()=><AppearanceSection/>},
  {id:'alerts',label:'Alerts',hint:'Notifications and alert rules',icon:BellRing,render:()=><AlertsSection/>},
  {id:'models',label:'Models',hint:'Lifecycle and retention',icon:Boxes,render:()=><ModelsSection/>},
  {id:'connection',label:'Connection',hint:'Data source and API',icon:Plug,render:()=><ConnectionSection/>},
  {id:'advanced',label:'Advanced',hint:'Export, reset, diagnostics',icon:TerminalSquare,render:()=><AdvancedSection/>},
]

export function SettingsPage(){
  const{section}=useParams()
  const{connection,isDemo}=useDashboard()
  const active=sections.find(item=>item.id===section)
  if(!active)return <Navigate to="/settings/workspace" replace/>
  return <div className="page settings-page">
    <header className="page-header">
      <div><p className="eyebrow">Configuration</p><h1>Settings</h1><p>Preferences are stored in this browser. Alert rules and model changes are written to the DriftZero API.</p></div>
      <div className="header-meta"><span className={`status-dot ${connection}`}/> {isDemo?'Demo data':connection==='connected'?'API connected':'API offline'}</div>
    </header>
    <div className="settings-layout">
      <nav className="settings-nav" aria-label="Settings sections">
        {sections.map(({id,label,hint,icon:Icon})=>
          <NavLink key={id} to={`/settings/${id}`} className={({isActive})=>isActive?'settings-nav-link active':'settings-nav-link'}>
            <Icon size={16} strokeWidth={1.8}/><div><strong>{label}</strong><small>{hint}</small></div>
          </NavLink>)}
      </nav>
      <div className="settings-body">{active.render()}</div>
    </div>
  </div>
}
