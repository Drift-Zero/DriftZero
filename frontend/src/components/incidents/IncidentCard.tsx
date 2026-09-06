import { ArrowRight,Clock3 } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { IncidentView } from '../../types/dashboard'
import { timeAgo } from '../../utils/format'
import { StatusBadge } from '../common/StatusBadge'

export function IncidentCard({incident,selected=false}:{incident:IncidentView;selected?:boolean}){return <Link to={`/incidents/${incident.id}`} className={`incident-card ${selected?'selected':''}`}><div className="incident-top"><StatusBadge status={incident.severity}/><span className="incident-state">{incident.state}</span></div><h3>{incident.title}</h3><p>{incident.modelName} / {incident.provider}</p><div className="impact-row"><div><span>Health impact</span><strong>{incident.baselineScore??'—'} <i>→</i> {incident.troughScore??'—'}</strong></div><div><span>Detected</span><strong className="time"><Clock3 size={13}/>{timeAgo(incident.openedAt)}</strong></div></div><ArrowRight className="card-arrow" size={15}/></Link>}
