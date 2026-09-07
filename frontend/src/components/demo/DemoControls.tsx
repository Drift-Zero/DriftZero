import { CircleCheck,RotateCcw,ShieldAlert,Sparkles } from 'lucide-react'
import { useDashboard } from '../../context/DashboardContext'
import { useSettings } from '../../context/SettingsContext'
import type { DemoStage } from '../../types/dashboard'

const controls:Array<{stage:DemoStage;label:string;icon:typeof RotateCcw}>=[{stage:'healthy',label:'Reset',icon:RotateCcw},{stage:'degraded',label:'Inject failure',icon:ShieldAlert},{stage:'recovering',label:'Apply recovery',icon:Sparkles},{stage:'verified',label:'Verify',icon:CircleCheck}]
export function DemoControls(){const{isDemo,demoStage,setDemoStage}=useDashboard();const{settings}=useSettings();if(!isDemo||!settings.appearance.showDemoControls)return null;return <div className="demo-controls"><div><span className="status-dot demo"/><div><strong>Demo controls</strong><small>{demoStage} state</small></div></div><div>{controls.map(({stage,label,icon:Icon})=><button key={stage} className={demoStage===stage?'active':''} onClick={()=>{setDemoStage(stage)}} type="button"><Icon size={13}/>{label}</button>)}</div></div>}
