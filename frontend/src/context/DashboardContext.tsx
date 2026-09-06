/* eslint-disable react-refresh/only-export-components -- provider and its typed hook intentionally share one context */
import { createContext,useCallback,useContext,useEffect,useRef,useState,type ReactNode } from 'react'
import { loadLiveDashboard } from '../api/adapter'
import { api } from '../api/endpoints'
import { createDemoData } from '../demo/data'
import type { DashboardData,DemoStage } from '../types/dashboard'

type Connection='demo'|'connected'|'offline'
export type RecoveryPhase='approving'|'queued'|'running'|'verifying'|'done'|'failed'
export interface RecoveryProgress{planId:string;phase:RecoveryPhase;message:string}
interface Value{data:DashboardData|null;loading:boolean;error:string|null;connection:Connection;isDemo:boolean;demoStage:DemoStage;setDemoStage:(stage:DemoStage)=>void;refresh:()=>Promise<void>;runRecovery:(planId:string)=>Promise<void>;trackRecovery:(planId:string)=>void;recovery:RecoveryProgress|null;dismissRecovery:()=>void}
const Context=createContext<Value|null>(null)
const isDemo=(import.meta.env.VITE_DEMO_MODE??'true').toLowerCase()==='true'

/* The API hands execution to the recovery worker and answers 202, so the plan is still
   'queued' when the call returns. Poll until the worker moves it somewhere the operator
   can act on rather than leaving the panel showing the button they just pressed. */
const POLL_MS=1500,POLL_ATTEMPTS=60
const settled=new Set(['recovered','failed','rejected','canceled','rolled_back','verifying'])
const phaseFor=(state:string):RecoveryPhase=>state==='recovered'?'done':state==='verifying'?'verifying':state==='executing'?'running':['failed','rejected','canceled','rolled_back'].includes(state)?'failed':'queued'
const phaseMessage:Record<RecoveryPhase,string>={approving:'Approving recovery plan…',queued:'Queued for the recovery worker…',running:'Applying recovery actions…',verifying:'Actions applied. Verifying model health…',done:'Recovery verified.',failed:'Recovery did not complete.'}
const wait=(ms:number)=>new Promise(resolve=>{setTimeout(resolve,ms)})

export function DashboardProvider({children}:{children:ReactNode}){
  const[data,setData]=useState<DashboardData|null>(isDemo?createDemoData('healthy'):null);const[loading,setLoading]=useState(!isDemo);const[error,setError]=useState<string|null>(null);const[connection,setConnection]=useState<Connection>(isDemo?'demo':'offline');const[demoStage,setStage]=useState<DemoStage>('healthy');const[recovery,setRecovery]=useState<RecoveryProgress|null>(null);const running=useRef(false)
  /* Reloading in the background keeps the incident the operator is reading on screen;
     flipping `loading` would swap the whole page for the full-page spinner mid-recovery. */
  const reload=useCallback(async()=>{const result=await loadLiveDashboard();setData(result);setConnection('connected');setError(null)},[])
  const refresh=useCallback(async()=>{if(isDemo)return;setLoading(true);setError(null);try{await reload()}catch(err){setConnection('offline');setError(err instanceof Error?err.message:'The DriftZero API is unavailable.')}finally{setLoading(false)}},[reload])
  useEffect(()=>{if(isDemo)return;let active=true;void loadLiveDashboard().then(result=>{if(active){setData(result);setConnection('connected')}}).catch(err=>{if(active){setConnection('offline');setError(err instanceof Error?err.message:'The DriftZero API is unavailable.')}}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[])
  const setDemoStage=(stage:DemoStage)=>{setStage(stage);setData(createDemoData(stage))}
  const dismissRecovery=useCallback(()=>{setRecovery(null)},[])

  /* Follow a plan the worker already holds until it settles, refreshing the dashboard on each
     transition. Used both after this session queues a recovery and when the page loads onto a
     plan someone else left in flight, which would otherwise render a stale, permanently
     disabled button. */
  const poll=useCallback(async(planId:string,from:string)=>{
    let state=from
    for(let attempt=0;attempt<POLL_ATTEMPTS;attempt+=1){
      await wait(POLL_MS)
      const plan=await api.recoveryPlan(planId)
      if(plan.state!==state){state=plan.state;await reload().catch(()=>undefined)}
      const phase=phaseFor(plan.state)
      setRecovery({planId,phase,message:phase==='failed'?plan.failure_reason??phaseMessage.failed:phaseMessage[phase]})
      if(settled.has(plan.state))break
    }
    await reload().catch(()=>undefined)
  },[reload])

  const runRecovery=useCallback(async(planId:string)=>{
    if(isDemo){setDemoStage('recovering');return}
    if(running.current)return
    running.current=true
    setRecovery({planId,phase:'approving',message:phaseMessage.approving})
    try{
      const approved=await api.approveRecovery(planId)
      if(approved.state!=='recovered')await api.executeRecovery(planId,approved.version)
      setRecovery({planId,phase:'queued',message:phaseMessage.queued})
      await poll(planId,approved.state)
    }catch(err){
      setRecovery({planId,phase:'failed',message:err instanceof Error?err.message:'Recovery action failed.'})
    }finally{running.current=false}
  },[poll])

  const trackRecovery=useCallback((planId:string)=>{
    if(isDemo||running.current)return
    running.current=true
    setRecovery({planId,phase:'queued',message:phaseMessage.queued})
    void poll(planId,'').catch(err=>{
      setRecovery({planId,phase:'failed',message:err instanceof Error?err.message:'Recovery status is unavailable.'})
    }).finally(()=>{running.current=false})
  },[poll])

  const value={data,loading,error,connection,isDemo,demoStage,setDemoStage,refresh,runRecovery,trackRecovery,recovery,dismissRecovery}
  return <Context.Provider value={value}>{children}</Context.Provider>
}
export function useDashboard(){const value=useContext(Context);if(!value)throw new Error('useDashboard must be used inside DashboardProvider');return value}
