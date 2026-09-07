/* eslint-disable react-refresh/only-export-components -- provider and its typed hook intentionally share one context */
import { useCallback,useEffect,useSyncExternalStore,type ReactNode } from 'react'
import { exportSettings,getApiKey,getSettings,importSettings,patchSettings,resetSettings,setApiKey,subscribe } from '../settings/store'
import type { AppSettings } from '../types/settings'

/* The store is the source of truth rather than component state: api/client.ts, api/endpoints.ts
   and utils/format.ts all read it synchronously from outside React, so a settings change has to
   be visible to a fetch or a formatter that no hook ever sees. */
export function useSettings(){
  const settings=useSyncExternalStore(subscribe,getSettings,getSettings)
  const apiKey=useSyncExternalStore(subscribe,getApiKey,getApiKey)
  const update=useCallback(<K extends keyof AppSettings>(section:K,patch:Partial<AppSettings[K]>)=>{patchSettings(section,patch)},[])
  return{settings,apiKey,update,setApiKey,reset:resetSettings,exportSettings,importSettings}
}

/* Appearance preferences are applied to the document element so plain CSS can honour them,
   including inside portals and anything rendered outside the React tree. */
export function SettingsProvider({children}:{children:ReactNode}){
  const{settings}=useSettings()
  const{density,reducedMotion}=settings.appearance
  useEffect(()=>{
    const root=document.documentElement
    root.dataset.density=density
    root.dataset.motion=reducedMotion?'reduced':'full'
  },[density,reducedMotion])
  useEffect(()=>{document.title=`${settings.workspace.name} · AI reliability monitoring`},[settings.workspace.name])
  return <>{children}</>
}
