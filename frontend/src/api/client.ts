import { getApiKey,getSettings } from '../settings/store'

export class ApiError extends Error {
  constructor(message:string, public status?:number) { super(message); this.name='ApiError' }
}

/* Read through to the settings store on every call rather than snapshotting at module load:
   the Settings screen can repoint the dashboard at another API, or change who the audit trail
   records as the actor, without a rebuild or a reload. */
export const apiBaseUrl=():string=>getSettings().connection.baseUrl
export const recoveryActor=():string=>getSettings().workspace.actor
export const recoveryRole=():string=>getSettings().workspace.role

/* The API derives the audit actor from server-controlled credentials, so recovery mutations
   must carry them as headers. Without a key the backend falls back to local identity, which
   it only permits outside production. */
export function recoveryHeaders():Record<string,string>{
  const key=getApiKey()
  return{...(key?{Authorization:`Bearer ${key}`}:{}),'X-DriftZero-Actor':recoveryActor(),'X-DriftZero-Role':recoveryRole()}
}

/* The session cookie is HttpOnly. Only the non-secret CSRF value is held in memory and it is
   deliberately lost on refresh, forcing the app to establish a fresh authenticated context. */
let csrfToken=''
export function setCsrfToken(value:string):void{csrfToken=value}
export function clearCsrfToken():void{csrfToken=''}

export async function apiRequest<T>(path:string, options:RequestInit={}):Promise<T> {
  const method=(options.method??'GET').toUpperCase()
  const mutating=!['GET','HEAD','OPTIONS'].includes(method)
  const response=await fetch(`${apiBaseUrl()}${path}`,{...options,credentials:'include',headers:{'Content-Type':'application/json',Accept:'application/json',...(mutating&&csrfToken?{'X-CSRF-Token':csrfToken}:{}),...options.headers}})
  if(!response.ok){let message=`DriftZero API returned ${response.status}`;try{const body=await response.json() as {detail?:string};if(body.detail)message=body.detail}catch{/* fallback */}throw new ApiError(message,response.status)}
  if(response.status===204)return undefined as T
  return response.json() as Promise<T>
}

export interface ProbeResult{ok:boolean;status?:string;environment?:string;latencyMs:number;detail?:string}

/* Used by the Settings connection check. It targets an explicit URL instead of the stored one so
   an operator can validate a candidate endpoint before committing the dashboard to it. */
export async function probeApi(baseUrl:string,timeoutMs=6000):Promise<ProbeResult>{
  const started=performance.now()
  const controller=new AbortController()
  const timer=setTimeout(()=>{controller.abort()},timeoutMs)
  try{
    const response=await fetch(`${baseUrl.replace(/\/$/,'')}/healthz`,{credentials:'include',headers:{Accept:'application/json'},signal:controller.signal})
    const latencyMs=Math.round(performance.now()-started)
    if(!response.ok)return{ok:false,latencyMs,detail:`The API answered ${response.status}.`}
    const body=await response.json() as {status?:string;environment?:string}
    return{ok:true,latencyMs,status:body.status,environment:body.environment}
  }catch(error){
    const latencyMs=Math.round(performance.now()-started)
    if(error instanceof DOMException&&error.name==='AbortError')return{ok:false,latencyMs,detail:`No response within ${Math.round(timeoutMs/1000)}s.`}
    return{ok:false,latencyMs,detail:error instanceof Error?error.message:'The request failed.'}
  }finally{clearTimeout(timer)}
}
