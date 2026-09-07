import { ClipboardCopy,Download,RotateCcw,Upload } from 'lucide-react'
import { useState } from 'react'
import { useDashboard } from '../../context/DashboardContext'
import { useSettings } from '../../context/SettingsContext'
import { envDefaults } from '../../settings/store'
import { timeZoneLabel } from '../../utils/format'
import { Note,SettingsPanel } from './controls'

const storageWorks=()=>{try{const probe='driftzero.probe';localStorage.setItem(probe,'1');localStorage.removeItem(probe);return true}catch{return false}}

export function AdvancedSection(){
  const{settings,exportSettings,importSettings,reset}=useSettings()
  const{connection,isDemo}=useDashboard()
  const[draft,setDraft]=useState('')
  const[status,setStatus]=useState<{tone:'info'|'danger';text:string}|null>(null)

  const download=()=>{
    const url=URL.createObjectURL(new Blob([exportSettings()],{type:'application/json'}))
    const anchor=document.createElement('a')
    anchor.href=url;anchor.download='driftzero-settings.json'
    anchor.click()
    URL.revokeObjectURL(url)
  }
  const copy=async()=>{
    try{await navigator.clipboard.writeText(exportSettings());setStatus({tone:'info',text:'Settings copied to the clipboard.'})}
    catch{setStatus({tone:'danger',text:'The browser refused clipboard access. Use Download instead.'})}
  }
  const apply=()=>{
    try{importSettings(draft);setDraft('');setStatus({tone:'info',text:'Settings imported.'})}
    catch(err){setStatus({tone:'danger',text:err instanceof Error?err.message:'Those settings could not be read.'})}
  }

  const diagnostics:Array<[string,string]>=[
    ['Build',import.meta.env.MODE],
    ['Data source',isDemo?'Demo data':'Live API'],
    ['Connection',connection],
    ['API base URL',settings.connection.baseUrl],
    ['Build-time API base',envDefaults.baseUrl],
    ['Time zone',timeZoneLabel()],
    ['Settings storage',storageWorks()?'Available':'Unavailable — settings last only for this tab'],
    ['Desktop notifications',typeof window!=='undefined'&&'Notification' in window?Notification.permission:'Unsupported'],
  ]

  return <>
    <SettingsPanel label="Portability" title="Export and import" description="Settings are stored in this browser only. Move them between machines as JSON.">
      <div className="settings-actions start">
        <button type="button" className="button" onClick={download}><Download size={14}/>Download JSON</button>
        <button type="button" className="button" onClick={()=>{void copy()}}><ClipboardCopy size={14}/>Copy to clipboard</button>
      </div>
      <label className="settings-textarea">
        <span>Paste settings to import</span>
        <textarea value={draft} rows={6} spellCheck={false} placeholder="Paste a settings file exported from another browser" onChange={event=>{setDraft(event.target.value)}}/>
      </label>
      {status&&<Note tone={status.tone}>{status.text}</Note>}
      <Note tone="warn">Importing replaces every setting at once rather than merging: anything the file leaves out, or sets to a value this build does not recognise, returns to its default.</Note>
      <div className="settings-actions">
        <button type="button" className="button primary" onClick={apply} disabled={!draft.trim()}><Upload size={14}/>Import settings</button>
      </div>
      <Note>An import never carries the recovery API key: it is held in session storage and is deliberately excluded from the exported file.</Note>
    </SettingsPanel>

    <SettingsPanel label="Reset" title="Restore defaults" description="Returns every setting on this screen to the values this build was compiled with.">
      <Note tone="danger">This clears the workspace name, appearance choices, data source, API base URL, and notification preferences. Alert rules and models are stored in the API and are not affected.</Note>
      <div className="settings-actions">
        <button type="button" className="button" onClick={()=>{if(window.confirm('Restore every dashboard setting to its default?')){reset();setStatus({tone:'info',text:'Settings restored to defaults.'})}}}><RotateCcw size={14}/>Restore defaults</button>
      </div>
    </SettingsPanel>

    <SettingsPanel label="Support" title="Diagnostics" description="What this dashboard build is doing right now. Useful when reporting a problem.">
      <dl className="diagnostics">{diagnostics.map(([term,value])=><div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}</dl>
    </SettingsPanel>
  </>
}
