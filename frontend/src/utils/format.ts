import { getSettings } from '../settings/store'

/* Display preferences are read per call rather than passed down: these helpers are used by
   almost every component, and threading a preference through all of them would be a far larger
   change than the preference is worth. */
const zone=()=>getSettings().appearance.timeZone==='utc'?'UTC':undefined

export function shortTime(value:string){return new Intl.DateTimeFormat('en',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false,timeZone:zone()}).format(new Date(value))}
export function fullDate(value:string){return new Intl.DateTimeFormat('en',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',timeZone:zone()}).format(new Date(value))}
export function timeAgo(value:string|null|undefined){
  if(!value)return'No evaluations'
  if(getSettings().appearance.timestampFormat==='absolute')return fullDate(value)
  const seconds=Math.max(0,Math.round((Date.now()-Date.parse(value))/1000))
  if(seconds<60)return'just now'
  if(seconds<3600)return`${Math.floor(seconds/60)}m ago`
  if(seconds<86400)return`${Math.floor(seconds/3600)}h ago`
  return`${Math.floor(seconds/86400)}d ago`
}
export function labelize(value:string){return value.replaceAll('_',' ').replace(/\b\w/g,letter=>letter.toUpperCase())}
/* Health scores are rounded for display only. The precision is a preference because one decimal
   is the difference between watching a score drift and watching it sit still. */
export function formatScore(value:number|null|undefined,placeholder='—'){
  if(value===null||value===undefined||!Number.isFinite(value))return placeholder
  return value.toFixed(getSettings().appearance.scoreDecimals)
}
export function timeZoneLabel(){return getSettings().appearance.timeZone==='utc'?'UTC':Intl.DateTimeFormat().resolvedOptions().timeZone}
