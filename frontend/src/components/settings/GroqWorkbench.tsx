import { Bot,Download,Loader2,Play,ShieldCheck } from 'lucide-react'
import { useMemo,useState } from 'react'
import { api } from '../../api/endpoints'
import type { ApiGroqEvaluation,ApiModel } from '../../api/types'
import { labelize } from '../../utils/format'
import { Note,SelectField } from './controls'

const lines=(value:string)=>value.split(/[,\n]/).map(item=>item.trim()).filter(Boolean)

function MetricGrid({result}:{result:ApiGroqEvaluation}){
  return <div className="groq-metric-grid">
    {Object.entries(result.dimensions).filter(([,value])=>value!=null).map(([name,value])=><div key={name}>
      <span>{labelize(name)}</span><strong>{Number(value).toFixed(1)}</strong>
    </div>)}
  </div>
}

export function GroqWorkbench({models,onImported}:{models:ApiModel[];onImported:()=>Promise<void>}){
  const[catalog,setCatalog]=useState<string[]>([])
  const[selected,setSelected]=useState('')
  const[name,setName]=useState('')
  const[registeredId,setRegisteredId]=useState('')
  const[prompt,setPrompt]=useState('What storage does the Premium plan include?')
  const[expected,setExpected]=useState('500 GB')
  const[facts,setFacts]=useState('Premium plan includes 500 GB')
  const[forbidden,setForbidden]=useState('unlimited storage')
  const[repeat,setRepeat]=useState(2)
  const[expectedJson,setExpectedJson]=useState(false)
  const[busy,setBusy]=useState<'discover'|'import'|'evaluate'|null>(null)
  const[error,setError]=useState<string|null>(null)
  const[result,setResult]=useState<ApiGroqEvaluation|null>(null)
  const groqModels=useMemo(()=>models.filter(model=>model.provider.toLowerCase()==='groq'&&model.status==='active'),[models])

  const discover=async()=>{
    setBusy('discover');setError(null)
    try{const response=await api.groqModels();setCatalog(response.models);setSelected(current=>current||response.models[0]||'')}
    catch(err){setError(err instanceof Error?err.message:'Groq models could not be loaded.')}
    finally{setBusy(null)}
  }
  const importModel=async()=>{
    if(!selected||!name.trim())return
    setBusy('import');setError(null)
    try{
      const model=await api.importGroqModel({name:name.trim(),model_identifier:selected,environment:'development',prompt_version:'prompt-v1',description:'Imported from Groq for deterministic DriftZero evaluation.'})
      await onImported();setRegisteredId(model.id)
    }catch(err){setError(err instanceof Error?err.message:'The model could not be imported.')}
    finally{setBusy(null)}
  }
  const evaluate=async()=>{
    if(!registeredId||!prompt.trim())return
    setBusy('evaluate');setError(null);setResult(null)
    try{setResult(await api.evaluateGroqModel(registeredId,{prompt:prompt.trim(),repeat,temperature:0,profile:{expected_terms:lines(expected),trusted_facts:lines(facts),forbidden_terms:lines(forbidden),expected_json:expectedJson,latency_target_ms:2000,input_cost_per_million:0,output_cost_per_million:0}}))}
    catch(err){setError(err instanceof Error?err.message:'The evaluation could not be completed.')}
    finally{setBusy(null)}
  }

  return <section className="groq-workbench">
    <div className="groq-heading"><div className="settings-icon"><Bot size={17}/></div><div><strong>Groq model workbench</strong><p>The backend calls Groq once per run. DriftZero calculates every displayed metric locally.</p></div></div>
    {error&&<Note tone="danger">{error}</Note>}
    <div className="groq-step">
      <div className="groq-step-title"><span>1</span><strong>Discover and import</strong></div>
      <div className="groq-form-row">
        <button type="button" className="button secondary" disabled={busy!==null} onClick={()=>void discover()}>{busy==='discover'?<Loader2 size={14} className="spin"/>:<Download size={14}/>}Load Groq models</button>
        <SelectField value={selected} ariaLabel="Groq model" disabled={!catalog.length||busy!==null} options={catalog.map(value=>({value,label:value}))} onChange={setSelected}/>
        <input className="settings-input" value={name} maxLength={120} placeholder="DriftZero model name" aria-label="Imported model name" onChange={event=>setName(event.target.value)}/>
        <button type="button" className="button primary" disabled={!selected||!name.trim()||busy!==null} onClick={()=>void importModel()}>{busy==='import'?<Loader2 size={14} className="spin"/>:<Download size={14}/>}Import</button>
      </div>
      <small>The Groq key stays in the backend environment and is never returned to this page.</small>
    </div>
    <div className="groq-step">
      <div className="groq-step-title"><span>2</span><strong>Run a deterministic evaluation</strong></div>
      <label><span>Registered Groq model</span><SelectField value={registeredId} ariaLabel="Registered Groq model" options={[{value:'',label:'Select a model'},...groqModels.map(model=>({value:model.id,label:model.name}))]} onChange={setRegisteredId}/></label>
      <label><span>Prompt</span><textarea className="settings-input groq-textarea" value={prompt} onChange={event=>setPrompt(event.target.value)}/></label>
      <div className="groq-profile-grid">
        <label><span>Expected terms</span><textarea className="settings-input" value={expected} onChange={event=>setExpected(event.target.value)} placeholder="Comma or line separated"/></label>
        <label><span>Trusted facts</span><textarea className="settings-input" value={facts} onChange={event=>setFacts(event.target.value)} placeholder="Exact evidence phrases"/></label>
        <label><span>Forbidden terms</span><textarea className="settings-input" value={forbidden} onChange={event=>setForbidden(event.target.value)} placeholder="Safety or policy violations"/></label>
      </div>
      <div className="groq-run-row">
        <label><span>Responses</span><input className="settings-input number" type="number" min={1} max={20} value={repeat} onChange={event=>setRepeat(Math.max(1,Math.min(20,Number(event.target.value))))}/></label>
        <label className="groq-check"><input type="checkbox" checked={expectedJson} onChange={event=>setExpectedJson(event.target.checked)}/>Require valid JSON</label>
        <button type="button" className="button primary" disabled={!registeredId||!prompt.trim()||busy!==null} onClick={()=>void evaluate()}>{busy==='evaluate'?<Loader2 size={14} className="spin"/>:<Play size={14}/>}Run evaluation</button>
      </div>
    </div>
    {result&&<div className="groq-result">
      <div className="groq-result-head"><div><span>Local health score</span><strong>{result.health_score?.toFixed(1)??'Insufficient evidence'}</strong></div><div><ShieldCheck size={17}/><span>{Math.round(result.confidence*100)}% confidence · {result.formula}</span></div></div>
      <MetricGrid result={result}/>
      <details><summary>Provider responses and evidence</summary>{result.responses.map((response,index)=><div className="groq-response" key={`${index}:${response.latency_ms}`}><small>Response {index+1} · {response.latency_ms} ms · {response.output_tokens} output tokens</small><p>{response.text}</p></div>)}<pre>{JSON.stringify(result.evidence,null,2)}</pre></details>
    </div>}
  </section>
}
