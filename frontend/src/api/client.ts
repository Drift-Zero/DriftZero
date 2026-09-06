const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message:string, public status?:number) { super(message); this.name='ApiError' }
}

export async function apiRequest<T>(path:string, options:RequestInit={}):Promise<T> {
  const response=await fetch(`${API_BASE_URL}${path}`,{...options,headers:{'Content-Type':'application/json',Accept:'application/json',...options.headers}})
  if(!response.ok){let message=`DriftZero API returned ${response.status}`;try{const body=await response.json() as {detail?:string};if(body.detail)message=body.detail}catch{/* fallback */}throw new ApiError(message,response.status)}
  if(response.status===204)return undefined as T
  return response.json() as Promise<T>
}
export const apiBaseUrl=API_BASE_URL
