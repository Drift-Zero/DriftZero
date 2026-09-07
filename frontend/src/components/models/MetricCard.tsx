import { ArrowDown,ArrowUp,Minus } from 'lucide-react'
import type { MetricValue } from '../../types/dashboard'
import { HEALTHY_SCORE,WARNING_SCORE } from '../../utils/health'

export function MetricCard({metric}:{metric:MetricValue}){const change=metric.value!==null&&metric.previous!=null?metric.value-metric.previous:null;const tone=metric.value===null?'neutral':metric.value>=HEALTHY_SCORE?'positive':metric.value>=WARNING_SCORE?'warning':'negative';
  /* An unchanged metric reads '+0 vs previous', so an up arrow beside it claims a rise that
     did not happen. Round first: a change the caption shows as 0 must not point anywhere. */
  const rounded=change===null?null:Math.round(change)
  const trend=rounded===null||rounded===0?'flat':rounded>0?'up':'down'
  return <article className="metric-card"><div><span>{metric.label}</span><i className={`metric-trend ${trend}`}>{trend==='flat'?<Minus size={13}/>:trend==='up'?<ArrowUp size={13}/>:<ArrowDown size={13}/>}</i></div><strong className={tone}>{metric.value===null?'—':Math.round(metric.value)}{metric.suffix??''}</strong><div className="metric-track"><i className={tone} style={{width:`${metric.value??0}%`}}/></div><small>{rounded===null?'No prior sample':rounded===0?'Unchanged from previous':`${rounded>0?'+':''}${rounded} vs previous`}</small></article>}
