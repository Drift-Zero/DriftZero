import { Check,Loader2 } from 'lucide-react'
import { useCallback,useEffect,useState } from 'react'
import { api } from '../../api/endpoints'
import type { ApiModel } from '../../api/types'
import { useDashboard } from '../../context/DashboardContext'
import { labelize } from '../../utils/format'
import { Note,SelectField,SettingsPanel } from './controls'
import { GroqWorkbench } from './GroqWorkbench'

const LIFECYCLE:Array<ApiModel['status']>=['active','paused','retired']

/* Keyed on the stored retention below, so a value changed elsewhere replaces the field rather
   than leaving a stale draft sitting over it. */
function ModelRow({model,busy,onLifecycle,onRetention}:{model:ApiModel;busy:boolean;onLifecycle:(status:ApiModel['status'])=>void;onRetention:(days:number)=>void}){
  const[days,setDays]=useState(model.retention_days)
  const valid=Number.isFinite(days)&&days>=1&&days<=3650
  const dirty=valid&&days!==model.retention_days
  const retired=model.status==='retired'
  return <li className={retired?'retired':''}>
    <div className="model-row-identity">
      <div className="model-glyph small">{model.name[0]}</div>
      <div><strong>{model.name}</strong><p>{model.provider} · {model.environment}</p></div>
    </div>
    <label className="model-row-control"><span>Lifecycle</span>
      <SelectField value={model.status} ariaLabel={`Lifecycle for ${model.name}`} disabled={busy||retired}
        options={LIFECYCLE.map(value=>({value,label:labelize(value)}))} onChange={onLifecycle}/>
    </label>
    <label className="model-row-control"><span>Trace retention</span>
      <span className="retention-input">
        <input className="settings-input number" type="number" min={1} max={3650} value={days} disabled={busy}
          aria-label={`Trace retention in days for ${model.name}`} onChange={event=>{setDays(Number(event.target.value))}}/>
        <small>days</small>
        <button type="button" className="button primary" disabled={!dirty||busy} onClick={()=>{onRetention(days)}}>{busy?<Loader2 size={13} className="spin"/>:<Check size={13}/>}Save</button>
      </span>
    </label>
  </li>
}

function ModelRegistry(){
  const[models,setModels]=useState<ApiModel[]>([])
  const[loading,setLoading]=useState(true)
  const[error,setError]=useState<string|null>(null)
  const[busyId,setBusyId]=useState<string|null>(null)

  useEffect(()=>{
    let active=true
    void api.models()
      .then(result=>{if(active){setModels(result);setError(null)}})
      .catch((err:unknown)=>{if(active)setError(err instanceof Error?err.message:'Models could not be loaded.')})
      .finally(()=>{if(active)setLoading(false)})
    return()=>{active=false}
  },[])

  const reload=useCallback(async()=>{setModels(await api.models())},[])
  const run=async(id:string,action:()=>Promise<unknown>)=>{
    setBusyId(id);setError(null)
    try{await action();await reload()}
    catch(err){setError(err instanceof Error?err.message:'The change could not be saved.')}
    finally{setBusyId(null)}
  }

  return <>
    <GroqWorkbench models={models} onImported={reload}/>
    {error&&<Note tone="danger">{error}</Note>}
    {loading&&<p className="settings-loading"><Loader2 size={14} className="spin"/>Loading models…</p>}
    {!loading&&!models.length&&!error&&<Note>No models are registered yet. Register one through the API or a telemetry integration.</Note>}
    <ul className="model-admin-list">
      {models.map(model=><ModelRow key={`${model.id}:${model.retention_days}`} model={model} busy={busyId===model.id}
        onLifecycle={status=>{
          if(status==='retired'&&!window.confirm(`Retire ${model.name}? A retired model cannot be reactivated.`))return
          void run(model.id,()=>api.setModelLifecycle(model.id,status))
        }}
        onRetention={retentionDays=>{void run(model.id,()=>api.updateModel(model.id,{retention_days:retentionDays}))}}/>)}
    </ul>
    <Note>Retention governs stored request traces, which hold the redacted evidence behind a diagnosis. The retention worker deletes traces older than the window; health snapshots, incidents, and audit events are kept.</Note>
    <Note tone="warn">Pausing a model stops evaluation-driven detection for it. Retiring is permanent — the API refuses to reactivate a retired model.</Note>
  </>
}

export function ModelsSection(){
  const{isDemo}=useDashboard()
  return <SettingsPanel label="Registry" title="Monitored models" description="Lifecycle state and evidence retention for each registered model. Every change is written to the audit trail.">
    {isDemo
      ?<Note tone="warn">The model registry lives in the DriftZero API. Switch the data source to the live API under Connection to manage it.</Note>
      :<ModelRegistry/>}
  </SettingsPanel>
}
