import { Bell } from 'lucide-react'
import { useState } from 'react'
import { useSettings } from '../../context/SettingsContext'
import { NOTIFY_SEVERITIES } from '../../types/settings'
import { labelize } from '../../utils/format'
import { AlertRules } from './AlertRules'
import { Field,Note,SelectField,SettingsPanel,Toggle } from './controls'

const supported=typeof window!=='undefined'&&'Notification' in window
const permissionOf=()=>supported?Notification.permission:'unsupported'

export function AlertsSection(){
  const{settings,update}=useSettings()
  const{notifications}=settings
  const[permission,setPermission]=useState<string>(permissionOf)

  /* The browser only grants permission from a user gesture, so the toggle asks for it at the
     moment it is switched on rather than on page load. */
  const toggleDesktop=async(next:boolean)=>{
    if(!next){update('notifications',{desktop:false});return}
    if(!supported)return
    const granted=Notification.permission==='granted'?'granted':await Notification.requestPermission()
    setPermission(granted)
    update('notifications',{desktop:granted==='granted'})
  }

  const hint=!supported?'This browser does not support desktop notifications.'
    :permission==='denied'?'Blocked for this site. Allow notifications in your browser settings, then switch this back on.'
    :'A notification is raised when a new incident opens, and when a recovery finishes.'

  return <>
    <SettingsPanel label="Delivery" title="Notifications" description="Alerts always appear in the in-app feed. These control what also leaves the tab.">
      <Toggle label="Desktop notifications" hint={hint} checked={notifications.desktop&&permission==='granted'} disabled={!supported||permission==='denied'}
        onChange={next=>{void toggleDesktop(next)}}/>
      <Field label="Minimum severity" hint="Incidents below this are shown in the dashboard but do not raise a notification.">
        <SelectField value={notifications.minimumSeverity} ariaLabel="Minimum severity"
          options={NOTIFY_SEVERITIES.map(value=>({value,label:labelize(value)}))}
          onChange={minimumSeverity=>{update('notifications',{minimumSeverity})}}/>
      </Field>
      <Toggle label="New incidents" hint="Raised when a degradation opens an incident." checked={notifications.incidents} onChange={incidents=>{update('notifications',{incidents})}}/>
      <Toggle label="Recovery outcomes" hint="Raised when a recovery plan is verified or fails." checked={notifications.recovery} onChange={recovery=>{update('notifications',{recovery})}}/>
      {permission==='granted'&&<div className="settings-actions">
        <button type="button" className="button" onClick={()=>{new Notification('DriftZero',{body:'Notifications are working. This is a test.'})}}><Bell size={14}/>Send a test notification</button>
      </div>}
      {supported&&permission==='default'&&<Note>Your browser will ask for permission the first time you switch desktop notifications on.</Note>}
    </SettingsPanel>
    <AlertRules/>
  </>
}
