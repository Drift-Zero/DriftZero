import { AlertTriangle,RefreshCw,ShieldCheck } from 'lucide-react'

export function LoadingState(){return <div className="skeleton-layout"><div className="skeleton wide"/><div className="skeleton-grid"><div className="skeleton tall"/><div className="skeleton tall"/><div className="skeleton tall"/></div><div className="skeleton chart"/></div>}
export function ErrorState({message,onRetry}:{message:string;onRetry:()=>void}){return <div className="state-card error-state"><AlertTriangle/><h2>API unavailable</h2><p>{message}</p><button className="button secondary" onClick={onRetry}><RefreshCw size={15}/>Try again</button></div>}
export function EmptyState({title,detail}:{title:string;detail:string}){return <div className="empty-state"><ShieldCheck size={24}/><div><strong>{title}</strong><p>{detail}</p></div></div>}
