import type { HealthStatus } from '../../types/dashboard'
import { StatusBadge } from '../common/StatusBadge'

export function HealthScore({score,status,size='large'}:{score:number|null;status:HealthStatus;size?:'large'|'compact'}){return <div className={`health-score ${size}`}><div className="score-ring" style={{'--score':score??0} as React.CSSProperties}><div><strong>{score===null?'—':Math.round(score)}</strong><small>/ 100</small></div></div><StatusBadge status={status}/></div>}
