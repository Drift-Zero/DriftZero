import { apiRequest,recoveryActor,recoveryHeaders,recoveryRole } from './client'
import type { ApiAlertFeed,ApiAlertRule,ApiAlertRuleInput,ApiAuditEvent,ApiDiagnosis,ApiGroqCatalog,ApiGroqEvaluation,ApiGroqEvaluationProfile,ApiHealthTimeline,ApiIncident,ApiModel,ApiRecovery,ApiRecoveryCommand } from './types'
const v1='/api/v1'
const actor=()=>({actor:recoveryActor(),role:recoveryRole()})
const send=(method:string,body:Record<string,unknown>):RequestInit=>({method,headers:recoveryHeaders(),body:JSON.stringify({...actor(),...body})})
const mutate=(body:Record<string,unknown>):RequestInit=>send('POST',body)
export const api={
  healthcheck:()=>apiRequest<{status:string;environment:string}>('/healthz'),
  models:()=>apiRequest<ApiModel[]>(`${v1}/models`),
  groqModels:()=>apiRequest<ApiGroqCatalog>(`${v1}/integrations/groq/models`),
  importGroqModel:(body:{name:string;model_identifier:string;environment:string;description?:string;prompt_version:string})=>apiRequest<ApiModel>(`${v1}/integrations/groq/models`,mutate(body)),
  evaluateGroqModel:(modelId:string,body:{prompt:string;repeat:number;temperature:number;profile:ApiGroqEvaluationProfile})=>apiRequest<ApiGroqEvaluation>(`${v1}/models/${modelId}/evaluations/groq`,mutate(body)),
  health:(modelId:string)=>apiRequest<ApiHealthTimeline>(`${v1}/models/${modelId}/health`),
  incidents:(modelId:string)=>apiRequest<ApiIncident[]>(`${v1}/models/${modelId}/incidents?limit=100`),
  diagnosis:(modelId:string)=>apiRequest<ApiDiagnosis>(`${v1}/models/${modelId}/diagnoses/latest`),
  recovery:(modelId:string)=>apiRequest<ApiRecovery>(`${v1}/models/${modelId}/recovery/latest`),
  audit:(modelId:string)=>apiRequest<ApiAuditEvent[]>(`${v1}/models/${modelId}/audit`),
  alerts:()=>apiRequest<ApiAlertFeed>(`${v1}/alerts?limit=100`),
  recoveryPlan:(planId:string)=>apiRequest<ApiRecovery>(`${v1}/recovery/${planId}`),
  approveRecovery:(planId:string,expectedVersion?:number)=>apiRequest<ApiRecovery>(`${v1}/recovery/${planId}/approve`,mutate({reason:'Approved from the DriftZero dashboard.',...(expectedVersion?{expected_version:expectedVersion}:{})})),
  /* Keying on the approved plan version makes a double-click idempotent — the API replays the
     command already queued — while a genuinely new attempt on a re-approved plan gets its own key.
     No expected_version here: queuing bumps the plan version, so the guard would reject the
     very replay the idempotency key exists to serve. */
  executeRecovery:(planId:string,approvedVersion:number)=>apiRequest<ApiRecoveryCommand>(`${v1}/recovery/${planId}/execute`,mutate({idempotency_key:`dashboard-${planId}-v${approvedVersion}`})),

  alertRules:(modelId:string)=>apiRequest<ApiAlertRule[]>(`${v1}/models/${modelId}/alert-rules`),
  createAlertRule:(modelId:string,rule:ApiAlertRuleInput)=>apiRequest<ApiAlertRule>(`${v1}/models/${modelId}/alert-rules`,mutate({...rule})),
  updateAlertRule:(ruleId:string,patch:Partial<ApiAlertRuleInput>)=>apiRequest<ApiAlertRule>(`${v1}/alert-rules/${ruleId}`,send('PATCH',{...patch})),
  /* The API takes the actor in the body even on a delete, so this cannot be a bare DELETE. */
  deleteAlertRule:(ruleId:string)=>apiRequest<void>(`${v1}/alert-rules/${ruleId}`,send('DELETE',{})),

  updateModel:(modelId:string,patch:{name?:string;provider?:string;environment?:string;description?:string|null;retention_days?:number})=>apiRequest<ApiModel>(`${v1}/models/${modelId}`,send('PATCH',{...patch})),
  setModelLifecycle:(modelId:string,status:ApiModel['status'])=>apiRequest<ApiModel>(`${v1}/models/${modelId}/lifecycle`,mutate({status})),
}
