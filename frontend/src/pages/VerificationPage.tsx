import { AlertTriangle,CheckCircle2,CircleHelp,Clock3,FileCheck2,LoaderCircle,ShieldCheck,Sparkles } from 'lucide-react'
import { useCallback,useEffect,useState } from 'react'
import { api } from '../api/endpoints'
import type { ApiClaimVerdict,ApiEvaluation,ApiVerificationSource,ClaimVerdictValue } from '../api/types'
import { EmptyState } from '../components/common/PageState'
import { useDashboard } from '../context/DashboardContext'

/* The labels the brief insists on: an unsupported claim is never called a
   hallucination, because the corpus simply may not cover it. */
const VERDICT_LABEL:Record<ClaimVerdictValue,string>={
  supported:'Supported by evidence',
  contradicted:'Confirmed contradiction',
  insufficient_evidence:'Insufficient evidence',
  not_verifiable:'Not currently verifiable',
  not_applicable:'Not applicable',
}
const VERDICT_TONE:Record<ClaimVerdictValue,string>={
  supported:'supported',contradicted:'contradicted',insufficient_evidence:'insufficient',
  not_verifiable:'neutral',not_applicable:'neutral',
}
const METHOD_LABEL:Record<string,string>={
  deterministic:'Deterministic comparison',llm_verifier:'LLM verifier',no_evidence:'No evidence retrieved',
}
const SCENARIOS=[
  {label:'Stale policy answer',question:'Can I return headphones after 20 days?',answer:'Yes. Headphones can be returned within 30 days.'},
  {label:'Recovered answer',question:'Can I return headphones after 20 days?',answer:'Headphones can be returned within 14 days with a receipt.'},
  {label:'Sold-out product',question:'Is the Arc Mini Speaker available?',answer:'The Arc Mini Speaker is in stock and ships today.'},
]

function VerdictIcon({verdict}:{verdict:ClaimVerdictValue}){
  if(verdict==='supported')return <CheckCircle2 size={14}/>
  if(verdict==='contradicted')return <AlertTriangle size={14}/>
  if(verdict==='not_verifiable')return <Clock3 size={14}/>
  return <CircleHelp size={14}/>
}

function ClaimRow({claim}:{claim:ApiClaimVerdict}){
  const tone=VERDICT_TONE[claim.verdict]
  return <li className={`claim-row ${tone}`}>
    <div className="claim-head">
      <span className={`verdict-chip ${tone}`}><VerdictIcon verdict={claim.verdict}/>{VERDICT_LABEL[claim.verdict]}</span>
      <span className={`importance ${claim.importance}`}>{claim.importance}</span>
      <small>{METHOD_LABEL[claim.method]??claim.method}</small>
    </div>
    <p className="claim-text">{claim.text}</p>
    <p className="claim-why">{claim.explanation}</p>
    {claim.evidence.map(item=><blockquote key={item.chunk_id} className="claim-evidence">
      <span>{item.source_name} · v{item.version}{item.exact_fact_match?' · exact fact match':''}</span>
      {item.text}
    </blockquote>)}
  </li>
}

export function VerificationPage(){
  const{data}=useDashboard()
  const[sources,setSources]=useState<ApiVerificationSource[]|null>(null)
  const[evaluation,setEvaluation]=useState<ApiEvaluation|null>(null)
  const[busy,setBusy]=useState<string|null>(null)
  const[error,setError]=useState<string|null>(null)
  const[form,setForm]=useState(SCENARIOS[0])

  const model=data?.models.find(item=>item.name==='ShopAssist')??data?.models[0]

  const refresh=useCallback(async()=>{
    try{setSources(await api.verificationSources())}
    catch(err){setError(err instanceof Error?err.message:'Could not load verification sources.')}
  },[])
  useEffect(()=>{
    let active=true
    void api.verificationSources()
      .then(result=>{if(active)setSources(result)})
      .catch(()=>{if(active)setSources([])})
    return ()=>{active=false}
  },[])

  const run=async(label:string,action:()=>Promise<unknown>)=>{
    setBusy(label);setError(null)
    try{await action();await refresh()}
    catch(err){setError(err instanceof Error?err.message:'That action failed.')}
    finally{setBusy(null)}
  }

  const evaluate=async()=>{
    if(!model)return
    setBusy('evaluate');setError(null)
    try{setEvaluation(await api.evaluateResponse(model.id,form.question,form.answer))}
    catch(err){setError(err instanceof Error?err.message:'Evaluation failed.')}
    finally{setBusy(null)}
  }

  const grounded=evaluation?.groundedness
  const approvedCount=sources?.filter(source=>source.status==='approved').length??0

  return <div className="page verification-page">
    <header className="page-header">
      <div><p className="eyebrow">Evidence-grounded verification</p><h1>Claim Verification</h1>
      <p>Check model answers against sources you have approved, and see exactly how each number was derived.</p></div>
      <div className="header-meta"><FileCheck2 size={14}/> {approvedCount} approved {approvedCount===1?'source':'sources'}</div>
    </header>

    {error&&<div className="recovery-error"><AlertTriangle size={14}/><p>{error}</p></div>}

    <section className="panel">
      <div className="panel-heading">
        <div><span className="panel-label">Trusted sources</span><h2>Verification corpus</h2></div>
        <button className="button secondary" disabled={busy!==null}
          onClick={()=>void run('load',()=>api.loadDemoVerificationSource())}>
          {busy==='load'?<LoaderCircle size={14} className="spin"/>:<Sparkles size={14}/>}Load ShopAssist corpus
        </button>
      </div>
      {sources===null?<p className="muted-note">Loading…</p>
        :sources.length===0?<EmptyState title="No sources connected" detail="Load the built-in ShopAssist corpus to see the flow end to end."/>
        :<table className="source-table"><thead><tr><th>Source</th><th>Version</th><th>Evidence</th><th>Status</th><th>Approved by</th><th/></tr></thead>
          <tbody>{sources.map(source=>{
            const current=source.versions.filter(v=>!v.retired_at).at(-1)??source.versions.at(-1)
            return <tr key={source.id}>
              <td><strong>{source.name}</strong><small>{source.source_type}</small></td>
              <td>v{current?.version??'—'}</td>
              <td>{current?.chunk_count??0} passages · {current?.fact_count??0} facts</td>
              <td><span className={`source-status ${source.status}`}>{source.status.replace('_',' ')}</span></td>
              <td>{current?.approved_by??'—'}</td>
              <td className="source-actions">
                {source.status!=='approved'&&source.status!=='retired'&&<button className="button" disabled={busy!==null}
                  onClick={()=>void run(`approve-${source.id}`,()=>api.decideVerificationSource(source.id,'approve','operator'))}>Approve</button>}
                {source.status==='approved'&&<button className="button" disabled={busy!==null}
                  onClick={()=>void run(`retire-${source.id}`,()=>api.decideVerificationSource(source.id,'retire','operator'))}>Retire</button>}
              </td>
            </tr>})}
          </tbody></table>}
      <p className="muted-note">A source verifies nothing until it is approved. Retired versions stay readable as history but are never used as current truth.</p>
    </section>

    <section className="panel">
      <div className="panel-heading"><div><span className="panel-label">Check an answer</span><h2>Verify a response</h2></div></div>
      <div className="scenario-picker">{SCENARIOS.map(scenario=>
        <button key={scenario.label} type="button" className={form.label===scenario.label?'active':''}
          onClick={()=>{setForm(scenario);setEvaluation(null)}}>{scenario.label}</button>)}</div>
      <label className="verify-field">Question<textarea value={form.question} rows={2}
        onChange={event=>setForm({...form,question:event.target.value})}/></label>
      <label className="verify-field">Assistant answer<textarea value={form.answer} rows={3}
        onChange={event=>setForm({...form,answer:event.target.value})}/></label>
      <button className="button primary" disabled={busy!==null||!model} onClick={()=>void evaluate()}>
        {busy==='evaluate'?<><LoaderCircle size={14} className="spin"/>Verifying…</>:<><ShieldCheck size={14}/>Verify against approved evidence</>}
      </button>
      {!model&&<p className="muted-note">Register a model first.</p>}
    </section>

    {evaluation&&grounded&&<section className="panel">
      <div className="panel-heading"><div><span className="panel-label">How this was calculated</span>
        <h2>Groundedness {grounded.groundedness===null?'unavailable':grounded.groundedness}</h2></div></div>

      <div className="formula-strip">
        <code>{grounded.formula}</code>
        <div className="weight-legend"><span>central ×3</span><span>supporting ×2</span><span>minor ×1</span></div>
      </div>

      <div className="metric-row">
        <div><span>Confirmed contradictions</span><strong className={grounded.confirmed_hallucination_rate?'negative':''}>
          {grounded.confirmed_hallucination_rate===null?'—':`${grounded.confirmed_hallucination_rate}%`}</strong></div>
        <div><span>Evidence coverage</span><strong>{grounded.evidence_coverage===null?'—':`${grounded.evidence_coverage}%`}</strong></div>
        <div><span>Claims checked</span><strong>{evaluation.claims.length}</strong></div>
        <div><span>Verified by</span><strong>{evaluation.evaluator_provider??'Deterministic only'}</strong></div>
      </div>

      {grounded.capped&&<p className="cap-note"><AlertTriangle size={13}/>A central claim is contradicted, so groundedness is capped at 40.</p>}

      <ul className="claim-list">{evaluation.claims.map((claim,index)=><ClaimRow key={index} claim={claim}/>)}</ul>

      <p className="muted-note">Extractor {evaluation.extractor_version} · verifier {evaluation.verifier_version}
        {evaluation.corpus_versions.length?` · ${evaluation.corpus_versions.length} corpus version(s) consulted`:''}</p>
    </section>}
  </div>
}
