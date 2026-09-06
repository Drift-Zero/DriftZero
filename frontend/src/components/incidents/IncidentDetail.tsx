import { Activity,BrainCircuit,TrendingDown,X } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { IncidentView } from '../../types/dashboard'
import { fullDate,labelize } from '../../utils/format'
import { StatusBadge } from '../common/StatusBadge'
import { RecoveryPanel } from './RecoveryPanel'

export function IncidentDetail({incident}:{incident:IncidentView}){return <article className="incident-detail"><div className="detail-header"><div><div className="detail-kicker"><StatusBadge status={incident.severity}/><span>{incident.state.toUpperCase()}</span></div><h2>{incident.title}</h2><p>{incident.modelName} / {incident.provider} · detected {fullDate(incident.openedAt)}</p></div><Link to="/incidents" aria-label="Close incident details"><X size={18}/></Link></div>
  <div className="incident-score"><div><span>Health score</span><strong>{incident.baselineScore??'—'} <i>→</i> {incident.troughScore??'—'}</strong></div><TrendingDown/><div><span>Impact</span><strong>{incident.baselineScore&&incident.troughScore?`−${incident.baselineScore-incident.troughScore} points`:'Unavailable'}</strong></div></div>
  <section className="cause-section"><div className="section-heading"><div><span className="panel-label">Likely root cause</span><h3>{incident.probableCause??'Diagnosis unavailable'}</h3></div>{incident.confidence!=null&&<span className="confidence">{Math.round(incident.confidence*100)}% confidence</span>}</div><p>{incident.summary??'The backend has not supplied an incident explanation.'}</p></section>
  <section className="evidence-section"><span className="panel-label">Affected metrics</span><div className="evidence-grid">{incident.evidence.length?incident.evidence.map(item=><article key={item.metric}><div><Activity size={15}/><span>{labelize(item.metric)}</span></div><strong>{item.baseline??'—'} <i>→</i> {item.current??'—'}</strong><p>{item.summary}</p></article>):<p className="muted-copy">No diagnosis evidence is available for this incident.</p>}</div></section>
  {incident.recovery?<RecoveryPanel recovery={incident.recovery}/>:<div className="state-card compact"><BrainCircuit/><div><strong>No recovery plan yet</strong><p>DriftZero has not supplied a supported recovery action.</p></div></div>}
  </article>}
