/* eslint-disable react-refresh/only-export-components -- provider and its typed hook intentionally share one context */
import { createContext,useCallback,useContext,useEffect,useMemo,useRef,useState,type ReactNode } from 'react'
import { loadLiveDashboard } from '../api/adapter'
import { api } from '../api/endpoints'
import { createDemoData } from '../demo/data'
import type { DashboardData,DemoStage } from '../types/dashboard'
import { useSettings } from './SettingsContext'

type Connection='demo'|'connected'|'offline'
export type RecoveryPhase='approving'|'queued'|'running'|'verifying'|'done'|'failed'
export interface RecoveryProgress{planId:string;phase:RecoveryPhase;message:string}
interface Value{data:DashboardData|null;loading:boolean;error:string|null;connection:Connection;isDemo:boolean;demoStage:DemoStage;setDemoStage:(stage:DemoStage)=>void;refresh:()=>Promise<void>;lastUpdated:number|null;runRecovery:(planId:string)=>Promise<void>;trackRecovery:(planId:string)=>void;recovery:RecoveryProgress|null;dismissRecovery:()=>void}
const Context=createContext<Value|null>(null)

/* The API hands execution to the recovery worker and answers 202, so the plan is still
   'queued' when the call returns. Poll until the worker moves it somewhere the operator
   can act on rather than leaving the panel showing the button they just pressed. */
const POLL_MS=1500,POLL_ATTEMPTS=60
const settled=new Set(['recovered','failed','rejected','canceled','rolled_back','verifying'])
const phaseFor=(state:string):RecoveryPhase=>state==='recovered'?'done':state==='verifying'?'verifying':state==='executing'?'running':['failed','rejected','canceled','rolled_back'].includes(state)?'failed':'queued'
const phaseMessage:Record<RecoveryPhase,string>={approving:'Approving recovery plan…',queued:'Queued for the recovery worker…',running:'Applying recovery actions…',verifying:'Actions applied. Verifying model health…',done:'Recovery verified.',failed:'Recovery did not complete.'}
const wait=(ms:number)=>new Promise(resolve=>{setTimeout(resolve,ms)})
const reason=(err:unknown,fallback:string)=>err instanceof Error?err.message:fallback

/* `key` records which API base the rest of this state describes. Comparing it to the base the
   settings currently name is what makes 'loading' derivable: repointing the dashboard, or
   switching back to live data, invalidates the snapshot without anyone having to remember to
   raise a flag first. */
interface LiveState{key:string;data:DashboardData|null;error:string|null;lastUpdated:number|null}
const emptyLive:LiveState={key:'',data:null,error:null,lastUpdated:null}

export function DashboardProvider({children}:{children:ReactNode}){
  /* Demo mode and the API base are settings rather than build-time constants, so the source the
     dashboard reads can change while it is open. Everything below keys off the live value. */
  const{settings}=useSettings()
  const isDemo=settings.connection.mode==='demo'
  const{baseUrl,autoRefreshSeconds}=settings.connection
  const[demoStage,setDemoStage]=useState<DemoStage>('healthy')
  const[live,setLive]=useState<LiveState>(emptyLive)
  const[refreshing,setRefreshing]=useState(false)
  const[recovery,setRecovery]=useState<RecoveryProgress|null>(null)
  const running=useRef(false)

  /* Demo data is derived rather than stored: the scenario is a pure function of the stage, and
     holding a copy in state only creates a second thing that can be out of date. */
  const demoData=useMemo(()=>createDemoData(demoStage),[demoStage])
  const data=isDemo?demoData:live.data
  const error=isDemo?null:live.error
  const lastUpdated=isDemo?null:live.lastUpdated
  const stale=live.key!==baseUrl
  const loading=!isDemo&&(stale||refreshing)
  const connection:Connection=isDemo?'demo':!stale&&!live.error?'connected':'offline'

  /* Reloading in the background keeps the incident the operator is reading on screen;
     it never raises `refreshing`, so the page is not swapped for the skeleton mid-recovery. */
  const load=useCallback(async()=>{
    try{const result=await loadLiveDashboard();setLive({key:baseUrl,data:result,error:null,lastUpdated:Date.now()})}
    catch(err){setLive(current=>({...current,key:baseUrl,error:reason(err,'The DriftZero API is unavailable.')}));throw err}
  },[baseUrl])

  const refresh=useCallback(async()=>{
    if(isDemo)return
    setRefreshing(true)
    try{await load()}catch{/* the error is already on screen */}finally{setRefreshing(false)}
  },[isDemo,load])

  /* Re-runs whenever the operator switches between demo and live, or repoints the dashboard at
     another API, so a settings change takes effect without a reload. */
  useEffect(()=>{
    if(isDemo)return
    let active=true
    void loadLiveDashboard()
      .then(result=>{if(active)setLive({key:baseUrl,data:result,error:null,lastUpdated:Date.now()})})
      .catch((err:unknown)=>{if(active)setLive(current=>({...current,key:baseUrl,error:reason(err,'The DriftZero API is unavailable.')}))})
    return()=>{active=false}
  },[isDemo,baseUrl])

  /* Background polling for live deployments. It stands down while a recovery is being followed
     so the two are not refetching over each other. */
  useEffect(()=>{
    if(isDemo||!autoRefreshSeconds)return
    const timer=setInterval(()=>{if(!running.current)void load().catch(()=>undefined)},autoRefreshSeconds*1000)
    return()=>{clearInterval(timer)}
  },[isDemo,autoRefreshSeconds,load])

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
      if(plan.state!==state){state=plan.state;await load().catch(()=>undefined)}
      const phase=phaseFor(plan.state)
      setRecovery({planId,phase,message:phase==='failed'?plan.failure_reason??phaseMessage.failed:phaseMessage[phase]})
      if(settled.has(plan.state))break
    }
    await load().catch(()=>undefined)
  },[load])

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
      setRecovery({planId,phase:'failed',message:reason(err,'Recovery action failed.')})
    }finally{running.current=false}
  },[isDemo,poll])

  const trackRecovery=useCallback((planId:string)=>{
    if(isDemo||running.current)return
    running.current=true
    setRecovery({planId,phase:'queued',message:phaseMessage.queued})
    void poll(planId,'').catch(err=>{
      setRecovery({planId,phase:'failed',message:reason(err,'Recovery status is unavailable.')})
    }).finally(()=>{running.current=false})
  },[isDemo,poll])

  const value={data,loading,error,connection,isDemo,demoStage,setDemoStage,refresh,lastUpdated,runRecovery,trackRecovery,recovery,dismissRecovery}
  return <Context.Provider value={value}>{children}</Context.Provider>
}
export function useDashboard(){const value=useContext(Context);if(!value)throw new Error('useDashboard must be used inside DashboardProvider');return value}
