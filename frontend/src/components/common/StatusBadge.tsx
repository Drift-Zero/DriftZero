import type { HealthStatus } from '../../types/dashboard'
import { labelize } from '../../utils/format'

export function StatusBadge({status,label}:{status:HealthStatus|string;label?:string}){const tone=status==='healthy'||status==='resolved'||status==='recovered'||status==='success'?'healthy':status==='warning'||status==='verifying'||status==='recovering'||status==='medium'?'warning':status==='critical'||status==='failed'||status==='open'||status==='high'?'critical':'neutral';return <span className={`badge ${tone}`}><span />{label??labelize(status)}</span>}
