import type { HealthStatus } from '../../types/dashboard'
import { formatScore } from '../../utils/format'
import { StatusBadge } from '../common/StatusBadge'

export function HealthScore({score,status,size='large'}:{score:number|null;status:HealthStatus;size?:'large'|'compact'}){return <div className={`health-score ${size}`}><div className="score-ring" style={{'--score':score??0} as React.CSSProperties}><div><strong>{formatScore(score)}</strong><small>/ 100</small></div></div><StatusBadge status={status}/></div>}
