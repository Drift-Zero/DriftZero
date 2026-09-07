const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message:string, public status?:number) { super(message); this.name='ApiError' }
}

/* The API derives the audit actor from server-controlled credentials, so recovery mutations
   must carry them as headers. Without a key the backend falls back to local identity, which
   it only permits outside production. */
const recoveryApiKey=(import.meta.env.VITE_RECOVERY_API_KEY??'').trim()
export const recoveryActor=(import.meta.env.VITE_RECOVERY_ACTOR??'dashboard-operator').trim()
export const recoveryRole=(import.meta.env.VITE_RECOVERY_ROLE??'operator').trim()
export function recoveryHeaders():Record<string,string>{return{...(recoveryApiKey?{Authorization:`Bearer ${recoveryApiKey}`}:{}),'X-DriftZero-Actor':recoveryActor,'X-DriftZero-Role':recoveryRole}}

/* The session cookie is HttpOnly. Only the non-secret CSRF value is held in memory and it is
   deliberately lost on refresh, forcing the app to establish a fresh authenticated context. */
let csrfToken=''
export function setCsrfToken(value:string):void{csrfToken=value}
export function clearCsrfToken():void{csrfToken=''}

export async function apiRequest<T>(path:string, options:RequestInit={}):Promise<T> {
  const method=(options.method??'GET').toUpperCase()
  const mutating=!['GET','HEAD','OPTIONS'].includes(method)
  const response=await fetch(`${API_BASE_URL}${path}`,{...options,credentials:'include',headers:{'Content-Type':'application/json',Accept:'application/json',...(mutating&&csrfToken?{'X-CSRF-Token':csrfToken}:{}),...options.headers}})
  if(!response.ok){let message=`DriftZero API returned ${response.status}`;try{const body=await response.json() as {detail?:string};if(body.detail)message=body.detail}catch{/* fallback */}throw new ApiError(message,response.status)}
  if(response.status===204)return undefined as T
  return response.json() as Promise<T>
}
export const apiBaseUrl=API_BASE_URL
