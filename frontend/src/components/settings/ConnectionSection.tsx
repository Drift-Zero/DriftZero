import { Check,KeyRound,Loader2,PlugZap,RefreshCw,RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { probeApi,type ProbeResult } from '../../api/client'
import { useDashboard } from '../../context/DashboardContext'
import { useSettings } from '../../context/SettingsContext'
import { envDefaults,isValidBaseUrl,normalizeBaseUrl } from '../../settings/store'
import { AUTO_REFRESH_CHOICES } from '../../types/settings'
import { fullDate } from '../../utils/format'
import { Field,Note,Segmented,SelectField,SettingsPanel,TextField } from './controls'

const refreshLabel=(seconds:number)=>seconds===0?'Off':seconds<60?`Every ${seconds} seconds`:`Every ${seconds/60} minute${seconds===60?'':'s'}`

export function ConnectionSection(){
  const{settings,update,apiKey,setApiKey}=useSettings()
  const{connection}=settings
  const{connection:state,loading,error,lastUpdated,refresh}=useDashboard()
  const[baseUrl,setBaseUrl]=useState(connection.baseUrl)
  const[keyDraft,setKeyDraft]=useState('')
  const[probe,setProbe]=useState<ProbeResult|null>(null)
  const[probing,setProbing]=useState(false)

  const urlValid=isValidBaseUrl(baseUrl)
  const urlDirty=urlValid&&normalizeBaseUrl(baseUrl)!==connection.baseUrl
  const test=async()=>{
    if(!urlValid)return
    setProbing(true);setProbe(null)
    /* Probe the field, not the saved value: the point is to check a candidate endpoint before
       the whole dashboard is pointed at it. */
    try{setProbe(await probeApi(normalizeBaseUrl(baseUrl)))}finally{setProbing(false)}
  }

  const demo=connection.mode==='demo'
  const statusLabel=demo?'Demo data':state==='connected'?'Connected':'Offline'

  return <>
    <SettingsPanel label="Source" title="Data source" description="Where the dashboard reads models, health, incidents, and events from.">
      <Field label="Mode" hint={demo?'Deterministic sample data. Nothing is read from or written to an API.':'Live telemetry from the DriftZero API.'}>
        <Segmented label="Data source" value={connection.mode} onChange={mode=>{update('connection',{mode})}}
          options={[{value:'demo',label:'Demo data'},{value:'live',label:'Live API'}]}/>
      </Field>
      <Field label="Status" hint={demo?'Demo data is generated in the browser and never refreshes.':error??(lastUpdated?`Last updated ${fullDate(new Date(lastUpdated).toISOString())}.`:'Not loaded yet.')}>
        <div className="settings-status"><span className={`status-dot ${state}`}/>{loading?'Loading…':statusLabel}
          <button type="button" className="button" onClick={()=>{void refresh()}} disabled={loading||demo}><RefreshCw size={13} className={loading?'spin':''}/>Refresh now</button>
        </div>
      </Field>
      <Field label="Auto refresh" hint="Reloads live data in the background. It pauses while a recovery plan is being followed.">
        <SelectField value={String(connection.autoRefreshSeconds)} ariaLabel="Auto refresh interval" disabled={demo}
          options={AUTO_REFRESH_CHOICES.map(seconds=>({value:String(seconds),label:refreshLabel(seconds)}))}
          onChange={value=>{update('connection',{autoRefreshSeconds:Number(value)})}}/>
      </Field>
    </SettingsPanel>

    <SettingsPanel label="Endpoint" title="DriftZero API" description="Repoints the dashboard without a rebuild. The build was configured for the address below.">
      <Field label="Base URL" hint={`Build default: ${envDefaults.baseUrl}`}>
        <TextField value={baseUrl} onChange={value=>{setBaseUrl(value);setProbe(null)}} ariaLabel="API base URL" invalid={!urlValid} width={320} placeholder="https://api.example.com"/>
      </Field>
      {!urlValid&&<Note tone="danger">Enter an absolute http:// or https:// URL.</Note>}
      {probe&&<Note tone={probe.ok?'info':'danger'}>{probe.ok?`Reachable in ${probe.latencyMs}ms · status ${probe.status??'unknown'} · environment ${probe.environment??'unknown'}.`:`Could not reach the API. ${probe.detail??''}`}</Note>}
      <div className="settings-actions">
        <button type="button" className="button" onClick={()=>{void test()}} disabled={!urlValid||probing}>{probing?<Loader2 size={14} className="spin"/>:<PlugZap size={14}/>}Test connection</button>
        <button type="button" className="button" onClick={()=>{setBaseUrl(connection.baseUrl);setProbe(null)}} disabled={!urlDirty}><RotateCcw size={14}/>Discard</button>
        <button type="button" className="button primary" onClick={()=>{update('connection',{baseUrl:normalizeBaseUrl(baseUrl)})}} disabled={!urlDirty}><Check size={14}/>Save and reload data</button>
      </div>
    </SettingsPanel>

    <SettingsPanel label="Credentials" title="Recovery API key" description="Sent as a bearer token on privileged mutations when the API requires authentication.">
      <Field label="API key" hint={apiKey?'A key is set for this browser tab.':'No key set. The API must allow local identity.'}>
        <TextField value={keyDraft} onChange={setKeyDraft} type="password" ariaLabel="Recovery API key" width={320} placeholder={apiKey?'••••••••••••':'Paste a key'}/>
      </Field>
      <Note tone="warn"><KeyRound size={12}/> Kept in this tab&apos;s session storage only — never written to the settings file, and cleared when the tab closes. A key that must survive a reload belongs in the deployment&apos;s environment.</Note>
      <div className="settings-actions">
        <button type="button" className="button" onClick={()=>{setApiKey('');setKeyDraft('')}} disabled={!apiKey}>Clear key</button>
        <button type="button" className="button primary" onClick={()=>{setApiKey(keyDraft);setKeyDraft('')}} disabled={!keyDraft.trim()}><Check size={14}/>Use key</button>
      </div>
    </SettingsPanel>
  </>
}
