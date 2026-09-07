import { AUTO_REFRESH_CHOICES,CONNECTION_MODES,DENSITIES,NOTIFY_SEVERITIES,OPERATOR_ROLES,TIMESTAMP_FORMATS,TIME_ZONES } from '../types/settings'
import type { AppSettings,ConnectionMode,Density,NotifySeverity,OperatorRole,TimeZoneMode,TimestampFormat } from '../types/settings'

const STORAGE_KEY='driftzero.dashboard.settings.v1'
/* The recovery key authenticates privileged mutations, so it is deliberately kept out of the
   persisted settings blob: it lives in sessionStorage and dies with the tab. */
const API_KEY_STORAGE_KEY='driftzero.dashboard.recovery-key'

const env=import.meta.env
const trimmed=(value:unknown,fallback:string)=>typeof value==='string'&&value.trim()?value.trim():fallback
const envRole=trimmed(env.VITE_RECOVERY_ROLE,'operator')
export const envDefaults={
  baseUrl:trimmed(env.VITE_API_BASE_URL,'http://127.0.0.1:8000').replace(/\/$/,''),
  mode:(trimmed(env.VITE_DEMO_MODE,'true').toLowerCase()==='true'?'demo':'live') as ConnectionMode,
  actor:trimmed(env.VITE_RECOVERY_ACTOR,'dashboard-operator'),
  role:(OPERATOR_ROLES.includes(envRole as OperatorRole)?envRole:'operator') as OperatorRole,
  apiKey:trimmed(env.VITE_RECOVERY_API_KEY,''),
}

export const DEFAULT_SETTINGS:AppSettings={
  workspace:{name:'DriftZero',environmentLabel:'Production workspace',actor:envDefaults.actor,role:envDefaults.role},
  appearance:{density:'comfortable',reducedMotion:false,timestampFormat:'relative',timeZone:'local',scoreDecimals:0,showDemoControls:true},
  connection:{mode:envDefaults.mode,baseUrl:envDefaults.baseUrl,autoRefreshSeconds:0},
  notifications:{desktop:false,minimumSeverity:'high',incidents:true,recovery:true},
}

const clone=(value:AppSettings):AppSettings=>({workspace:{...value.workspace},appearance:{...value.appearance},connection:{...value.connection},notifications:{...value.notifications}})
const pick=<T extends string>(value:unknown,allowed:readonly T[],fallback:T):T=>allowed.includes(value as T)?value as T:fallback
const bool=(value:unknown,fallback:boolean)=>typeof value==='boolean'?value:fallback
const text=(value:unknown,fallback:string,max:number)=>typeof value==='string'&&value.trim()?value.trim().slice(0,max):fallback
const clampInt=(value:unknown,min:number,max:number,fallback:number)=>typeof value==='number'&&Number.isFinite(value)?Math.min(max,Math.max(min,Math.round(value))):fallback

/* Only absolute http(s) origins are accepted: a relative or javascript: value would be pasted
   straight into fetch() for every request the dashboard makes. */
export function isValidBaseUrl(value:string):boolean{
  try{const url=new URL(value.trim());return url.protocol==='http:'||url.protocol==='https:'}catch{return false}
}
export function normalizeBaseUrl(value:unknown):string{
  if(typeof value!=='string'||!isValidBaseUrl(value))return DEFAULT_SETTINGS.connection.baseUrl
  const url=new URL(value.trim())
  return (url.origin+url.pathname).replace(/\/$/,'')
}

/* A stored blob can be older than this build, hand-edited, or simply corrupt. Rebuild every
   field against the defaults rather than trusting the parsed shape, so one bad key cannot put
   the dashboard into a state its own controls can no longer describe. */
export function normalize(raw:unknown):AppSettings{
  const source=(typeof raw==='object'&&raw!==null?raw:{}) as Partial<Record<keyof AppSettings,Record<string,unknown>>>
  const workspace=source.workspace??{},appearance=source.appearance??{},connection=source.connection??{},notifications=source.notifications??{}
  const refresh=clampInt(connection.autoRefreshSeconds,0,3600,DEFAULT_SETTINGS.connection.autoRefreshSeconds)
  return{
    workspace:{
      name:text(workspace.name,DEFAULT_SETTINGS.workspace.name,60),
      environmentLabel:text(workspace.environmentLabel,DEFAULT_SETTINGS.workspace.environmentLabel,60),
      actor:text(workspace.actor,DEFAULT_SETTINGS.workspace.actor,120),
      role:pick<OperatorRole>(workspace.role,OPERATOR_ROLES,DEFAULT_SETTINGS.workspace.role),
    },
    appearance:{
      density:pick<Density>(appearance.density,DENSITIES,DEFAULT_SETTINGS.appearance.density),
      reducedMotion:bool(appearance.reducedMotion,DEFAULT_SETTINGS.appearance.reducedMotion),
      timestampFormat:pick<TimestampFormat>(appearance.timestampFormat,TIMESTAMP_FORMATS,DEFAULT_SETTINGS.appearance.timestampFormat),
      timeZone:pick<TimeZoneMode>(appearance.timeZone,TIME_ZONES,DEFAULT_SETTINGS.appearance.timeZone),
      scoreDecimals:clampInt(appearance.scoreDecimals,0,2,DEFAULT_SETTINGS.appearance.scoreDecimals),
      showDemoControls:bool(appearance.showDemoControls,DEFAULT_SETTINGS.appearance.showDemoControls),
    },
    connection:{
      mode:pick<ConnectionMode>(connection.mode,CONNECTION_MODES,DEFAULT_SETTINGS.connection.mode),
      baseUrl:normalizeBaseUrl(connection.baseUrl),
      autoRefreshSeconds:AUTO_REFRESH_CHOICES.includes(refresh)?refresh:DEFAULT_SETTINGS.connection.autoRefreshSeconds,
    },
    notifications:{
      desktop:bool(notifications.desktop,DEFAULT_SETTINGS.notifications.desktop),
      minimumSeverity:pick<NotifySeverity>(notifications.minimumSeverity,NOTIFY_SEVERITIES,DEFAULT_SETTINGS.notifications.minimumSeverity),
      incidents:bool(notifications.incidents,DEFAULT_SETTINGS.notifications.incidents),
      recovery:bool(notifications.recovery,DEFAULT_SETTINGS.notifications.recovery),
    },
  }
}

function read():AppSettings{
  try{const stored=localStorage.getItem(STORAGE_KEY);return normalize(stored?JSON.parse(stored):null)}
  catch{return clone(DEFAULT_SETTINGS)}
}

let current=read()
const listeners=new Set<()=>void>()
const notify=()=>{listeners.forEach(listener=>{listener()})}
function persist(next:AppSettings){
  current=next
  try{localStorage.setItem(STORAGE_KEY,JSON.stringify(next))}catch{/* private mode or a full quota: keep the in-memory value */}
  notify()
}

export const getSettings=()=>current
export const subscribe=(listener:()=>void)=>{listeners.add(listener);return()=>{listeners.delete(listener)}}
export function patchSettings<K extends keyof AppSettings>(section:K,patch:Partial<AppSettings[K]>):void{persist(normalize({...current,[section]:{...current[section],...patch}}))}
export function replaceSettings(next:unknown):AppSettings{const normalized=normalize(next);persist(normalized);return normalized}
export function resetSettings():AppSettings{const defaults=clone(DEFAULT_SETTINGS);persist(defaults);return defaults}
export const exportSettings=()=>JSON.stringify(current,null,2)
export function importSettings(json:string):AppSettings{
  let parsed:unknown
  try{parsed=JSON.parse(json)}catch{throw new Error('That is not valid JSON.')}
  if(typeof parsed!=='object'||parsed===null||Array.isArray(parsed))throw new Error('Settings must be a JSON object.')
  return replaceSettings(parsed)
}

let apiKey=(()=>{try{return sessionStorage.getItem(API_KEY_STORAGE_KEY)??envDefaults.apiKey}catch{return envDefaults.apiKey}})()
export const getApiKey=()=>apiKey
export function setApiKey(value:string):void{
  apiKey=value.trim()
  try{if(apiKey)sessionStorage.setItem(API_KEY_STORAGE_KEY,apiKey);else sessionStorage.removeItem(API_KEY_STORAGE_KEY)}catch{/* keep the in-memory value */}
  notify()
}

/* Settings are shared by every tab on this origin, so a change made in one has to reach the
   others; otherwise a second tab keeps talking to the old API base until it is reloaded. */
if(typeof window!=='undefined')window.addEventListener('storage',event=>{
  if(event.key===STORAGE_KEY){current=read();notify()}
  if(event.key===API_KEY_STORAGE_KEY){apiKey=event.newValue??''; notify()}
})
