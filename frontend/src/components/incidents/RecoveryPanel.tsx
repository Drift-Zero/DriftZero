import { AlertTriangle,Check,ChevronRight,LoaderCircle,Play,ShieldCheck,X } from 'lucide-react'
import { useEffect } from 'react'
import { useDashboard } from '../../context/DashboardContext'
import type { RecoveryView } from '../../types/dashboard'
import { StatusBadge } from '../common/StatusBadge'

const inFlight=new Set(['approved','queued','executing'])

export function RecoveryPanel({recovery}:{recovery:RecoveryView}){
  const{runRecovery,trackRecovery,isDemo,setDemoStage,recovery:progress,dismissRecovery}=useDashboard()
  const active=progress?.planId===recovery.id?progress:null
  const stranded=progress===null&&inFlight.has(recovery.state)
  /* A plan can already be with the worker when this page loads — queued by another operator,
     or by a session that has since gone away. Without this the panel would show a disabled
     button forever, because nothing was polling for the outcome. */
  useEffect(()=>{if(stranded)trackRecovery(recovery.id)},[stranded,recovery.id,trackRecovery])
  const verified=recovery.state==='recovered'
  const verifying=recovery.state==='verifying'
  const failed=recovery.state==='failed'||active?.phase==='failed'
  /* The plan reaches the worker before it reaches the operator's next render, so treat the
     in-flight plan states and the live progress as one "applying" condition. */
  const applying=(active!==null&&['approving','queued','running'].includes(active.phase))||inFlight.has(recovery.state)
  const applied=verifying||verified
  /* A worker-side failure does not always record a reason on the plan, so never leave the
     operator with a bare 'failed' badge and no explanation. */
  const failureMessage=active?.phase==='failed'?active.message
    :recovery.state==='failed'?recovery.failureReason??'The recovery worker could not complete this plan. Its verification did not pass.'
    :recovery.failureReason
  return <section className={`recovery-panel ${verified?'verified':''}`}>
  <div className="section-heading"><div><span className="panel-label">Recommended recovery</span><h3>{verified?'Recovery verified':verifying?'Verification in progress':failed?'Recovery failed':recovery.actions[0]?.title??'Recovery plan'}</h3></div><StatusBadge status={recovery.state}/></div>
  {verified&&recovery.verification?<div className="verification-result"><div className="verify-icon"><ShieldCheck size={25}/></div><div><strong>Model health restored</strong><p>New evaluations passed the recovery threshold with no safety regression.</p></div><div className="score-change"><span>Health</span><strong>{recovery.verification.baselineScore} <i>→</i> {recovery.verification.postScore}</strong></div></div>:<div className="recovery-actions">{recovery.actions.map((action,i)=><div key={action.code}><span>{i+1}</span><div><strong>{action.title}</strong><p>{action.description}</p></div><small>{action.reversible?'Reversible':'Permanent'}</small></div>)}</div>}
  <div className="recovery-flow"><span className="done"><Check size={11}/>Detected</span><ChevronRight/><span className={applied?'done':applying?'current':''}>{applied?<Check size={11}/>:applying?<LoaderCircle size={11}/>:null}Recovery applied</span><ChevronRight/><span className={verifying?'current':verified?'done':''}>{verifying?<LoaderCircle size={11}/>:verified?<Check size={11}/>:null}Verifying</span><ChevronRight/><span className={verified?'done':''}>{verified?<Check size={11}/>:null}Recovered</span></div>
  {failureMessage&&<div className="recovery-error"><AlertTriangle size={14}/><p>{failureMessage}</p><button type="button" onClick={dismissRecovery} aria-label="Dismiss recovery error"><X size={13}/></button></div>}
  {!verified&&<div className="recovery-footer">{verifying?<><div><span>Verification requests</span><strong>{recovery.verification?.observedRequests??12} / {recovery.verification?.requiredRequests??20}</strong></div><div className="progress"><i style={{width:`${((recovery.verification?.observedRequests??12)/(recovery.verification?.requiredRequests??20))*100}%`}}/></div>{isDemo&&<button className="button primary" onClick={()=>setDemoStage('verified')}><Check size={15}/>Complete verification</button>}</>:<>{active&&applying&&<div><span>Recovery status</span><strong>{active.message}</strong></div>}<button className="button primary" disabled={applying} onClick={()=>void runRecovery(recovery.id)}>{applying?<><LoaderCircle size={14} className="spin"/>Applying recovery…</>:<><Play size={14}/>{failed?'Retry recovery':'Approve & apply recovery'}</>}</button></>}</div>}
  </section>}
