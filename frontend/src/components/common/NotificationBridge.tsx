import { useEffect,useRef } from 'react'
import { useDashboard } from '../../context/DashboardContext'
import { useSettings } from '../../context/SettingsContext'
import { NOTIFY_SEVERITIES } from '../../types/settings'

const rank=(severity:string)=>{const index=NOTIFY_SEVERITIES.indexOf(severity as (typeof NOTIFY_SEVERITIES)[number]);return index===-1?NOTIFY_SEVERITIES.indexOf('medium'):index}
const canNotify=()=>typeof window!=='undefined'&&'Notification' in window&&Notification.permission==='granted'

function raise(title:string,body:string,tag:string){
  if(!canNotify())return
  try{const notification=new Notification(title,{body,tag});notification.onclick=()=>{window.focus();notification.close()}}
  catch{/* Some browsers reject constructed notifications outside a service worker; the in-app feed still has it. */}
}

/* Turns dashboard state into desktop notifications. Rendered once, near the root, so a single
   subscription covers every page instead of each page racing to announce the same incident. */
export function NotificationBridge(){
  const{data,recovery}=useDashboard()
  const{settings}=useSettings()
  const{desktop,minimumSeverity,incidents,recovery:notifyRecovery}=settings.notifications
  const seenIncidents=useRef<Set<string>|null>(null)
  const seenRecovery=useRef(new Map<string,string>())

  useEffect(()=>{
    if(!data)return
    const open=data.incidents.filter(incident=>incident.state!=='resolved')
    /* The first load establishes a baseline. Without it, opening the dashboard would announce
       every incident that was already open before anyone was watching. */
    if(seenIncidents.current===null){seenIncidents.current=new Set(open.map(incident=>incident.id));return}
    for(const incident of open){
      if(seenIncidents.current.has(incident.id))continue
      seenIncidents.current.add(incident.id)
      if(!desktop||!incidents)continue
      if(rank(incident.severity)<rank(minimumSeverity))continue
      raise(`${incident.modelName}: ${incident.severity} incident`,incident.title,`incident-${incident.id}`)
    }
  },[data,desktop,incidents,minimumSeverity])

  useEffect(()=>{
    if(!recovery)return
    const previous=seenRecovery.current.get(recovery.planId)
    if(previous===recovery.phase)return
    seenRecovery.current.set(recovery.planId,recovery.phase)
    if(!desktop||!notifyRecovery)return
    if(recovery.phase==='done')raise('Recovery verified','The recovery plan completed and health was re-checked.',`recovery-${recovery.planId}`)
    if(recovery.phase==='failed')raise('Recovery did not complete',recovery.message,`recovery-${recovery.planId}`)
  },[recovery,desktop,notifyRecovery])

  return null
}
