export type HealthStatus = 'healthy' | 'warning' | 'critical' | 'insufficient_data'
export type DemoStage = 'healthy' | 'degraded' | 'recovering' | 'verified'

export interface MetricValue { key:string; label:string; value:number|null; previous?:number|null; suffix?:string }
export interface HealthPoint { time:string; score:number|null; groundedness?:number|null; quality?:number|null; safety?:number|null; stability?:number|null; drift?:number|null }
export interface ModelView {
  id:string; name:string; provider:string; environment:string; lifecycle:string; description?:string|null
  status:HealthStatus; score:number|null; metrics:MetricValue[]; trend:HealthPoint[]; lastEvaluation:string|null
  requestId?:string|null; sampleSize?:number; coverage?:number; activeIncidents:number
  forecast?:{score:number;direction:string;horizonMinutes:number}|null
}
export interface RecoveryView {
  id:string; state:string; risk:string; requiresApproval:boolean; version?:number; approvalLevel?:string; failureReason?:string|null
  actions:Array<{code:string;title:string;description:string;risk:string;reversible:boolean}>
  verification?:{baselineScore?:number|null;postScore?:number|null;passed?:boolean|null;observedRequests:number;requiredRequests:number}|null
}
export interface IncidentView {
  id:string; modelId:string; modelName:string; provider:string; title:string; state:string; severity:string; openedAt:string
  closedAt?:string|null; baselineScore?:number|null; troughScore?:number|null; summary?:string|null; probableCause?:string|null; confidence?:number|null
  evidence:Array<{metric:string;summary:string;baseline?:number|null;current?:number|null}>; recovery?:RecoveryView|null
}
export interface EventView { id:string; modelId?:string|null; modelName:string; type:string; title:string; detail?:string|null; timestamp:string; status:'success'|'warning'|'critical'|'info' }
export interface DashboardData { models:ModelView[]; incidents:IncidentView[]; events:EventView[]; latestSampleSize:number }
