import { apiRequest } from './client'
import type { ApiAlertFeed,ApiAuditEvent,ApiDiagnosis,ApiHealthTimeline,ApiIncident,ApiModel,ApiRecovery } from './types'
const v1='/api/v1'
export const api={
  healthcheck:()=>apiRequest<{status:string;environment:string}>('/healthz'),
  models:()=>apiRequest<ApiModel[]>(`${v1}/models`),
  health:(modelId:string)=>apiRequest<ApiHealthTimeline>(`${v1}/models/${modelId}/health`),
  incidents:(modelId:string)=>apiRequest<ApiIncident[]>(`${v1}/models/${modelId}/incidents?limit=100`),
  diagnosis:(modelId:string)=>apiRequest<ApiDiagnosis>(`${v1}/models/${modelId}/diagnoses/latest`),
  recovery:(modelId:string)=>apiRequest<ApiRecovery>(`${v1}/models/${modelId}/recovery/latest`),
  audit:(modelId:string)=>apiRequest<ApiAuditEvent[]>(`${v1}/models/${modelId}/audit`),
  alerts:()=>apiRequest<ApiAlertFeed>(`${v1}/alerts?limit=100`),
  approveRecovery:(planId:string)=>apiRequest<ApiRecovery>(`${v1}/recovery/${planId}/approve`,{method:'POST',body:JSON.stringify({actor:'dashboard-operator',role:'operator'})}),
  executeRecovery:(planId:string)=>apiRequest<ApiRecovery>(`${v1}/recovery/${planId}/execute`,{method:'POST',body:JSON.stringify({actor:'dashboard-operator',role:'operator',idempotency_key:`dashboard-${Date.now()}`})}),
}
