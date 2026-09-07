import { ArrowRight,Clock3,ShieldAlert,ShieldCheck,Sparkles,TriangleAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { HealthChart } from '../components/charts/HealthChart'
import { EmptyState,ErrorState,LoadingState } from '../components/common/PageState'
import { StatusBadge } from '../components/common/StatusBadge'
import { EventTimeline } from '../components/events/EventTimeline'
import { useDashboard } from '../context/DashboardContext'
import type { HealthStatus,ModelView } from '../types/dashboard'
import { formatScore,timeAgo } from '../utils/format'
import { WARNING_SCORE } from '../utils/health'

const labels:Record<HealthStatus,string>={healthy:'Healthy',warning:'Warning',critical:'Critical',insufficient_data:'Insufficient data'}
const severity=(value:number|null)=>value==null?'unknown':value<65?'critical':value<80?'warning':'healthy'

function fleetStatus(models:ModelView[]):HealthStatus|null{
  if(!models.length)return null
  if(models.some(model=>model.status==='critical'))return'critical'
  if(models.some(model=>model.status==='warning'))return'warning'
  if(models.some(model=>model.status==='insufficient_data'))return'insufficient_data'
  return'healthy'
}

function latestEvaluation(models:ModelView[]):string|null{
  return models.reduce<string|null>((latest,model)=>!model.lastEvaluation?latest:!latest||Date.parse(model.lastEvaluation)>Date.parse(latest)?model.lastEvaluation:latest,null)
}

export function OverviewPage(){
  const{data,loading,error,refresh}=useDashboard()
  if(loading)return <div className="page"><LoadingState/></div>
  if(error||!data)return <div className="page"><ErrorState message={error??'Dashboard data could not be loaded.'} onRetry={()=>void refresh()}/></div>

  const primary=data.models.find(model=>model.status==='critical')??data.models.find(model=>model.status==='warning')??data.models[0]
  const active=data.incidents.filter(incident=>incident.state!=='resolved')
  const incident=active.find(item=>item.modelId===primary?.id)??active[0]
  const average=data.models.length?data.models.reduce((sum,model)=>sum+(model.score??0),0)/data.models.length:null
  const status=fleetStatus(data.models)
  const updatedAt=latestEvaluation(data.models)
  const degraded=primary?[...primary.metrics].filter(metric=>metric.value!=null).sort((left,right)=>(left.value??100)-(right.value??100)).slice(0,3):[]
  const modelRoute=primary?`/models/${primary.id}`:'/models'
  const incidentRoute=incident?`/incidents/${incident.id}`:'/incidents'

  return <div className="page overview-page">
    <header className="page-header"><div><p className="eyebrow">Reliability command center</p><h1>Know what needs attention.</h1><p>One view from degradation to diagnosis and safe recovery.</p></div><div className="header-meta"><span className="pulse-dot"/>Monitoring {data.models.length} models <span className="divider"/> {updatedAt?`Updated ${timeAgo(updatedAt)}`:'No evaluations yet'}</div></header>

    {primary&&<section className={`command-hero ${primary.status}`}>
      <div className="command-health"><span>Current priority</span><div><strong>{primary.name}</strong><StatusBadge status={primary.status}/></div><p>{primary.environment} · {primary.provider}</p></div>
      <div className="command-score"><small>Health score</small><strong>{formatScore(primary.score)}</strong><span>/100</span></div>
      <div className="command-forecast"><small>Expected in {primary.forecast?.horizonMinutes??30} min</small><strong>{formatScore(primary.forecast?.score)}</strong><span className={primary.forecast?.direction==='deteriorating'?'negative':'positive'}>{primary.forecast?.direction??'Forecast unavailable'}</span></div>
      <div className="command-actions"><Link className="button" to={modelRoute}>View health</Link>{incident&&<Link className="button primary" to={incidentRoute}>Start recovery <ArrowRight size={14}/></Link>}</div>
    </section>}

    {primary&&<section className="decision-grid">
      <article className="panel diagnosis-summary"><div className="panel-heading"><div><span className="panel-label">Probable cause</span><h2>{incident?.probableCause?.replaceAll('_',' ')??(primary.status==='healthy'?'No degradation detected':'Evaluation signals need review')}</h2></div><Sparkles size={17}/></div><p>{incident?.summary??(primary.status==='healthy'?'The latest evaluation is within the healthy operating range.':'DriftZero found a material change in the latest model window.')}</p><div className="diagnosis-confidence"><span>Root-cause confidence</span><strong>{incident?.confidence!=null?`${Math.round(incident.confidence*100)}%`:'Pending'}</strong></div>{incident&&<Link className="text-link" to={incidentRoute}>Open diagnosis and evidence <ArrowRight size={13}/></Link>}</article>
      <article className="panel degraded-summary"><div className="panel-heading"><div><span className="panel-label">What changed</span><h2>Lowest health dimensions</h2></div><TriangleAlert size={17}/></div><div className="degraded-list">{degraded.map(metric=><div key={metric.key}><span>{metric.label}</span><div><i className={severity(metric.value)} style={{width:`${metric.value??0}%`}}/></div><strong>{formatScore(metric.value)}</strong></div>)}</div><Link className="text-link" to={modelRoute}>See score calculation <ArrowRight size={13}/></Link></article>
      <article className="panel recovery-summary"><div className="panel-heading"><div><span className="panel-label">Safest next action</span><h2>{incident?.recovery?.actions[0]?.title??(primary.status==='healthy'?'Keep monitoring':'Review recovery options')}</h2></div><ShieldCheck size={17}/></div><p>{incident?.recovery?.actions[0]?.description??'DriftZero will continue evaluating new traffic and alert when the trajectory changes.'}</p>{incident?.recovery&&<><div className="recovery-meta"><span>{incident.recovery.risk} risk</span><span>{incident.recovery.requiresApproval?'Approval required':'Auto-recovery eligible'}</span></div><Link className="button primary full" to={incidentRoute}>Review recovery playbook <ArrowRight size={14}/></Link></>}</article>
    </section>}

    <section className="stat-grid compact"><article className={`stat-card featured ${status==='critical'?'danger':status==='warning'?'warn':''}`}><div className="stat-icon">{status==='critical'||status==='warning'?<ShieldAlert size={18}/>:<ShieldCheck size={18}/>}</div><div><span>Fleet health</span><strong>{formatScore(average)}</strong><small>{status?labels[status]:'No data'}</small></div></article><article className="stat-card"><div><span>Models monitored</span><strong>{data.models.length}</strong><small>{data.models.filter(model=>model.environment.toLowerCase()==='production').length} production</small></div></article><article className="stat-card"><div><span>Open incidents</span><strong>{active.length}</strong><small className={active.length?'negative':'positive'}>{active.length?'Needs attention':'All clear'}</small></div></article><article className="stat-card"><div><span>Latest evidence</span><strong>{data.latestSampleSize.toLocaleString()}</strong><small>requests evaluated</small></div></article></section>

    {primary&&<section className="dashboard-grid trend-first"><article className="panel trend-card"><div className="panel-heading"><div><span className="panel-label">Model health trajectory</span><h2>{primary.name} · {labels[primary.status]}</h2></div><span className="range-select">Last 3 hours</span></div><HealthChart data={primary.trend}/><div className="chart-caption"><span><i className="legend health"/>Health score</span><span className="threshold"><i/>Warning threshold · {WARNING_SCORE}</span>{primary.forecast&&<strong>Forecast: {formatScore(primary.forecast.score)} · {primary.forecast.direction}</strong>}</div></article><article className="panel"><div className="panel-heading"><div><span className="panel-label">Live event stream</span><h2>Latest activity</h2></div><Link className="text-link" to="/events">View all <ArrowRight size={13}/></Link></div>{data.events.length?<EventTimeline events={data.events} limit={4}/>:<EmptyState title="No events yet" detail="Evaluation and recovery activity will appear here."/>}</article></section>}

    {active.length>0&&<section className="panel compact-active-incidents"><div className="panel-heading"><div><span className="panel-label">Open incidents</span><h2>Items requiring attention</h2></div><Link className="text-link" to="/incidents">View all <ArrowRight size={13}/></Link></div><div className="compact-incidents">{active.slice(0,3).map(item=><Link to={`/incidents/${item.id}`} key={item.id}><StatusBadge status={item.severity}/><div><strong>{item.title}</strong><p>{item.modelName} · Health {item.baselineScore} → {item.troughScore}</p></div><span><Clock3 size={12}/>{timeAgo(item.openedAt)}</span></Link>)}</div></section>}
  </div>
}
