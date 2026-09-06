import { AlertTriangle,Check,Radio,Telescope } from 'lucide-react'
import type { EventView } from '../../types/dashboard'
import { shortTime } from '../../utils/format'

const icon={success:Check,warning:Telescope,critical:AlertTriangle,info:Radio}
export function EventTimeline({events,limit}:{events:EventView[];limit?:number}){return <div className="timeline">{events.slice(0,limit).map(event=>{const Icon=icon[event.status];return <div className="timeline-row" key={event.id}><time>{shortTime(event.timestamp)}</time><span className={`timeline-icon ${event.status}`}><Icon size={13}/></span><div><strong>{event.title}</strong><p>{event.modelName}{event.detail?` · ${event.detail}`:''}</p></div></div>})}</div>}
