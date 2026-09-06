/* eslint-disable react-refresh/only-export-components -- provider and its typed hook intentionally share one context */
import { createContext,useCallback,useContext,useEffect,useState,type ReactNode } from 'react'
import { loadLiveDashboard } from '../api/adapter'
import { api } from '../api/endpoints'
import { createDemoData } from '../demo/data'
import type { DashboardData,DemoStage } from '../types/dashboard'

type Connection='demo'|'connected'|'offline'
interface Value{data:DashboardData|null;loading:boolean;error:string|null;connection:Connection;isDemo:boolean;demoStage:DemoStage;setDemoStage:(stage:DemoStage)=>void;refresh:()=>Promise<void>;runRecovery:(planId:string)=>Promise<void>}
const Context=createContext<Value|null>(null)
const isDemo=(import.meta.env.VITE_DEMO_MODE??'true').toLowerCase()==='true'

export function DashboardProvider({children}:{children:ReactNode}){
  const[data,setData]=useState<DashboardData|null>(isDemo?createDemoData('healthy'):null);const[loading,setLoading]=useState(!isDemo);const[error,setError]=useState<string|null>(null);const[connection,setConnection]=useState<Connection>(isDemo?'demo':'offline');const[demoStage,setStage]=useState<DemoStage>('healthy')
  const refresh=useCallback(async()=>{if(isDemo)return;setLoading(true);setError(null);try{setData(await loadLiveDashboard());setConnection('connected')}catch(err){setConnection('offline');setError(err instanceof Error?err.message:'The DriftZero API is unavailable.')}finally{setLoading(false)}},[])
  useEffect(()=>{if(isDemo)return;let active=true;void loadLiveDashboard().then(result=>{if(active){setData(result);setConnection('connected')}}).catch(err=>{if(active){setConnection('offline');setError(err instanceof Error?err.message:'The DriftZero API is unavailable.')}}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[])
  const setDemoStage=(stage:DemoStage)=>{setStage(stage);setData(createDemoData(stage))}
  const runRecovery=async(planId:string)=>{if(isDemo){setDemoStage('recovering');return}setLoading(true);try{await api.approveRecovery(planId);await api.executeRecovery(planId);await refresh()}catch(err){setError(err instanceof Error?err.message:'Recovery action failed.');setLoading(false)}}
  const value={data,loading,error,connection,isDemo,demoStage,setDemoStage,refresh,runRecovery}
  return <Context.Provider value={value}>{children}</Context.Provider>
}
export function useDashboard(){const value=useContext(Context);if(!value)throw new Error('useDashboard must be used inside DashboardProvider');return value}
