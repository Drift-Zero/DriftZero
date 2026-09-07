import { BellPlus,Check,Loader2,Pencil,Trash2,X } from 'lucide-react'
import { useCallback,useEffect,useState } from 'react'
import { api } from '../../api/endpoints'
import type { ApiAlertMetric,ApiAlertRule,ApiAlertRuleInput,ApiAlertRuleType,ApiComparator,ApiSeverity } from '../../api/types'
import { useDashboard } from '../../context/DashboardContext'
import { labelize } from '../../utils/format'
import { Field,Note,SelectField,SettingsPanel,TextField } from './controls'

const RULE_TYPES:ApiAlertRuleType[]=['threshold','transition','trajectory','coverage','evaluation_freshness']
const DIMENSION_METRICS:ApiAlertMetric[]=['score','quality','groundedness','semantic_stability','temporal_stability','safety','drift','reliability','latency','cost']
/* Mirrors AlertRuleDefinition.validate_strategy in backend/app/schemas.py. Keeping the pairing
   here means an impossible combination cannot be built in the form at all, rather than being
   assembled and then rejected by the API. */
const METRICS_FOR:Record<ApiAlertRuleType,ApiAlertMetric[]>={threshold:DIMENSION_METRICS,transition:['state'],trajectory:['forecast_score','forecast_change_per_hour'],coverage:['coverage'],evaluation_freshness:['evaluation_age_minutes']}
const COMPARATORS:ApiComparator[]=['lt','lte','gt','gte']
const COMPARATOR_LABELS:Record<ApiComparator,string>={lt:'is below',lte:'is at or below',gt:'is above',gte:'is at or above'}
const SEVERITIES:ApiSeverity[]=['info','low','medium','high','critical']
const TARGET_STATES=['healthy','warning','critical'] as const
const RULE_TYPE_HINTS:Record<ApiAlertRuleType,string>={
  threshold:'Fires when a health dimension crosses a value.',
  transition:'Fires when the model enters a health state.',
  trajectory:'Fires on the forecast rather than the current score.',
  coverage:'Fires when evaluation coverage of traffic drops.',
  evaluation_freshness:'Fires when telemetry stops arriving.',
}

function boundsFor(metric:ApiAlertMetric){
  if(metric==='coverage')return{min:0,max:1,step:0.05,unit:'0 to 1'}
  if(metric==='evaluation_age_minutes')return{min:0,max:10080,step:5,unit:'minutes'}
  if(metric==='forecast_change_per_hour')return{min:-100,max:100,step:0.5,unit:'points per hour'}
  return{min:0,max:100,step:1,unit:'0 to 100'}
}
const defaultThreshold=(metric:ApiAlertMetric)=>metric==='coverage'?0.6:metric==='evaluation_age_minutes'?60:metric==='forecast_change_per_hour'?-5:metric==='forecast_score'?70:80
const blankRule=():ApiAlertRuleInput=>({name:'',rule_type:'threshold',metric:'score',comparator:'lt',threshold:80,target_state:null,window_minutes:15,cooldown_minutes:30,minimum_consecutive_windows:1,severity:'medium',channel:'in_app',is_enabled:true})

function withRuleType(rule:ApiAlertRuleInput,rule_type:ApiAlertRuleType):ApiAlertRuleInput{
  const metric=METRICS_FOR[rule_type][0]
  if(rule_type==='transition')return{...rule,rule_type,metric,comparator:null,threshold:null,target_state:'critical'}
  return{...rule,rule_type,metric,comparator:rule.comparator??'lt',threshold:defaultThreshold(metric),target_state:null}
}

function validate(rule:ApiAlertRuleInput):string|null{
  if(!rule.name.trim())return'Give the rule a name.'
  if(rule.rule_type==='transition')return rule.target_state?null:'Choose the state the rule watches for.'
  if(rule.threshold===null||!Number.isFinite(rule.threshold))return'Enter a threshold.'
  const bounds=boundsFor(rule.metric)
  if(rule.threshold<bounds.min||rule.threshold>bounds.max)return`Thresholds for ${labelize(rule.metric).toLowerCase()} must be between ${bounds.min} and ${bounds.max}.`
  return null
}

function describeRule(rule:ApiAlertRuleInput):string{
  const scope=`${rule.window_minutes}m window · ${rule.minimum_consecutive_windows} consecutive · ${rule.cooldown_minutes}m cooldown`
  if(rule.rule_type==='transition')return `Health state becomes ${rule.target_state} · ${scope}`
  return `${labelize(rule.metric)} ${COMPARATOR_LABELS[rule.comparator??'lt']} ${rule.threshold} · ${scope}`
}

function RuleForm({initial,busy,onCancel,onSubmit}:{initial:ApiAlertRuleInput;busy:boolean;onCancel:()=>void;onSubmit:(rule:ApiAlertRuleInput)=>void}){
  const[rule,setRule]=useState(initial)
  const bounds=boundsFor(rule.metric)
  const problem=validate(rule)
  const set=(patch:Partial<ApiAlertRuleInput>)=>{setRule(current=>({...current,...patch}))}
  return <form className="rule-form" onSubmit={event=>{event.preventDefault();if(!problem)onSubmit(rule)}}>
    <Field label="Rule name"><TextField value={rule.name} onChange={name=>{set({name})}} ariaLabel="Rule name" width={280} placeholder="Groundedness below 80" invalid={!rule.name.trim()}/></Field>
    <Field label="Rule type" hint={RULE_TYPE_HINTS[rule.rule_type]}>
      <SelectField value={rule.rule_type} ariaLabel="Rule type" options={RULE_TYPES.map(value=>({value,label:labelize(value)}))} onChange={type=>{setRule(current=>withRuleType(current,type))}}/>
    </Field>
    <Field label="Metric">
      <SelectField value={rule.metric} ariaLabel="Metric" disabled={METRICS_FOR[rule.rule_type].length===1}
        options={METRICS_FOR[rule.rule_type].map(value=>({value,label:labelize(value)}))}
        onChange={metric=>{set({metric,threshold:defaultThreshold(metric)})}}/>
    </Field>
    {rule.rule_type==='transition'
      ?<Field label="Target state" hint="Insufficient data is not alertable here — use a coverage rule instead.">
        <SelectField value={rule.target_state??'critical'} ariaLabel="Target state" options={TARGET_STATES.map(value=>({value,label:labelize(value)}))} onChange={target_state=>{set({target_state})}}/>
      </Field>
      :<Field label="Condition" hint={`Threshold is measured in ${bounds.unit}.`}>
        <div className="rule-condition">
          <SelectField value={rule.comparator??'lt'} ariaLabel="Comparator" options={COMPARATORS.map(value=>({value,label:COMPARATOR_LABELS[value]}))} onChange={comparator=>{set({comparator})}}/>
          <input className="settings-input number" type="number" aria-label="Threshold" value={rule.threshold??''} min={bounds.min} max={bounds.max} step={bounds.step}
            onChange={event=>{set({threshold:event.target.value===''?null:Number(event.target.value)})}}/>
        </div>
      </Field>}
    <Field label="Window" hint="Minutes of telemetry each evaluation looks at.">
      <input className="settings-input number" type="number" aria-label="Window minutes" value={rule.window_minutes} min={1} max={10080} onChange={event=>{set({window_minutes:Number(event.target.value)})}}/>
    </Field>
    <Field label="Consecutive windows" hint="How many windows in a row must breach before the rule fires.">
      <input className="settings-input number" type="number" aria-label="Consecutive windows" value={rule.minimum_consecutive_windows} min={1} max={100} onChange={event=>{set({minimum_consecutive_windows:Number(event.target.value)})}}/>
    </Field>
    <Field label="Cooldown" hint="Minutes before the same rule can fire again.">
      <input className="settings-input number" type="number" aria-label="Cooldown minutes" value={rule.cooldown_minutes} min={0} max={10080} onChange={event=>{set({cooldown_minutes:Number(event.target.value)})}}/>
    </Field>
    <Field label="Severity"><SelectField value={rule.severity} ariaLabel="Severity" options={SEVERITIES.map(value=>({value,label:labelize(value)}))} onChange={severity=>{set({severity})}}/></Field>
    {problem&&<Note tone="danger">{problem}</Note>}
    <div className="settings-actions">
      <button type="button" className="button" onClick={onCancel}><X size={14}/>Cancel</button>
      <button type="submit" className="button primary" disabled={Boolean(problem)||busy}>{busy?<Loader2 size={14} className="spin"/>:<Check size={14}/>}Save rule</button>
    </div>
  </form>
}

/* Mounted with the model id as its key, so choosing another model rebuilds this with a fresh
   loading state instead of briefly showing one model's rules under another's name. */
function RulesForModel({modelId}:{modelId:string}){
  const[rules,setRules]=useState<ApiAlertRule[]>([])
  const[loading,setLoading]=useState(true)
  const[error,setError]=useState<string|null>(null)
  const[busyId,setBusyId]=useState<string|null>(null)
  const[editing,setEditing]=useState<ApiAlertRule|'new'|null>(null)

  useEffect(()=>{
    let active=true
    void api.alertRules(modelId)
      .then(result=>{if(active){setRules(result);setError(null)}})
      .catch((err:unknown)=>{if(active)setError(err instanceof Error?err.message:'Alert rules could not be loaded.')})
      .finally(()=>{if(active)setLoading(false)})
    return()=>{active=false}
  },[modelId])

  const reload=useCallback(async()=>{setRules(await api.alertRules(modelId))},[modelId])
  const run=async(id:string,action:()=>Promise<unknown>)=>{
    setBusyId(id);setError(null)
    try{await action();await reload();setEditing(null)}
    catch(err){setError(err instanceof Error?err.message:'The change could not be saved.')}
    finally{setBusyId(null)}
  }

  return <>
    {error&&<Note tone="danger">{error}</Note>}
    {loading&&<p className="settings-loading"><Loader2 size={14} className="spin"/>Loading rules…</p>}
    {!loading&&!rules.length&&!error&&<Note>No rules yet. This model still raises incidents through the built-in health detection, but nothing here is watching individual dimensions.</Note>}
    <ul className="rule-list">
      {rules.map(rule=><li key={rule.id} className={rule.is_enabled?'':'disabled'}>
        <div><strong>{rule.name}</strong><p>{describeRule(rule)}</p></div>
        <span className={`badge ${rule.severity==='critical'||rule.severity==='high'?'critical':rule.severity==='medium'?'warning':'neutral'}`}><span/>{labelize(rule.severity)}</span>
        <button type="button" role="switch" aria-checked={rule.is_enabled} aria-label={`Enable ${rule.name}`} className={`switch${rule.is_enabled?' on':''}`} disabled={busyId===rule.id}
          onClick={()=>{void run(rule.id,()=>api.updateAlertRule(rule.id,{is_enabled:!rule.is_enabled}))}}><i/></button>
        <button type="button" className="icon-button" aria-label={`Edit ${rule.name}`} onClick={()=>{setEditing(rule)}}><Pencil size={14}/></button>
        <button type="button" className="icon-button danger" aria-label={`Delete ${rule.name}`} disabled={busyId===rule.id}
          onClick={()=>{if(window.confirm(`Delete the rule "${rule.name}"? Alerts it raised are resolved.`))void run(rule.id,()=>api.deleteAlertRule(rule.id))}}><Trash2 size={14}/></button>
      </li>)}
    </ul>
    {editing==='new'&&<RuleForm key="new" initial={blankRule()} busy={busyId==='new'} onCancel={()=>{setEditing(null)}} onSubmit={rule=>{void run('new',()=>api.createAlertRule(modelId,rule))}}/>}
    {editing&&editing!=='new'&&<RuleForm key={editing.id} initial={editing} busy={busyId===editing.id} onCancel={()=>{setEditing(null)}} onSubmit={rule=>{void run(editing.id,()=>api.updateAlertRule(editing.id,rule))}}/>}
    {!editing&&<div className="settings-actions"><button type="button" className="button primary" onClick={()=>{setEditing('new')}}><BellPlus size={14}/>New rule</button></div>}
  </>
}

export function AlertRules(){
  const{data,isDemo}=useDashboard()
  const models=data?.models??[]
  const[modelId,setModelId]=useState('')
  const active=models.some(model=>model.id===modelId)?modelId:models[0]?.id??''

  if(isDemo)return <SettingsPanel label="Detection" title="Alert rules" description="Threshold, transition, trajectory, coverage, and freshness rules per model.">
    <Note tone="warn">Alert rules live in the DriftZero API. Switch the data source to the live API under Connection to manage them.</Note>
  </SettingsPanel>

  return <SettingsPanel label="Detection" title="Alert rules" description="Evaluated against each new health snapshot. Firing rules appear in the alert feed and can open an incident."
    actions={models.length>1?<SelectField value={active} ariaLabel="Model" options={models.map(model=>({value:model.id,label:model.name}))} onChange={setModelId}/>:undefined}>
    {active?<RulesForModel key={active} modelId={active}/>:<Note tone="warn">No models are registered, so there is nothing to alert on yet.</Note>}
  </SettingsPanel>
}
