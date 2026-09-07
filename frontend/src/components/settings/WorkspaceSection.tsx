import { Check,RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { useSettings } from '../../context/SettingsContext'
import { OPERATOR_ROLES } from '../../types/settings'
import type { OperatorRole } from '../../types/settings'
import { labelize } from '../../utils/format'
import { Field,Note,SelectField,SettingsPanel,TextField } from './controls'

const roleHints:Record<OperatorRole,string>={viewer:'Read-only. The API rejects recovery actions.',operator:'Can approve and apply low and medium risk recovery plans.',admin:'Adds approval for high risk recovery plans.'}

function Actions({dirty,valid,onSave,onDiscard}:{dirty:boolean;valid:boolean;onSave:()=>void;onDiscard:()=>void}){
  return <div className="settings-actions">
    <button type="button" className="button" onClick={onDiscard} disabled={!dirty}><RotateCcw size={14}/>Discard</button>
    <button type="button" className="button primary" onClick={onSave} disabled={!dirty||!valid}><Check size={14}/>{dirty?'Save changes':'Saved'}</button>
  </div>
}

export function WorkspaceSection(){
  const{settings,update}=useSettings()
  const{workspace}=settings
  /* Drafts start from the saved values and are committed explicitly: writing every keystroke
     to the store would persist half-typed names, and normalisation would rewrite the field
     under the cursor. */
  const[name,setName]=useState(workspace.name)
  const[environmentLabel,setEnvironmentLabel]=useState(workspace.environmentLabel)
  const[actor,setActor]=useState(workspace.actor)
  const brandDirty=name.trim()!==workspace.name||environmentLabel.trim()!==workspace.environmentLabel
  const actorDirty=actor.trim()!==workspace.actor

  return <>
    <SettingsPanel label="Identity" title="Workspace" description="Names this dashboard in the sidebar and the browser tab.">
      <Field label="Workspace name" hint="Its first two letters become the sidebar badge."><TextField value={name} onChange={setName} ariaLabel="Workspace name" invalid={!name.trim()} width={260}/></Field>
      <Field label="Environment label" hint="Shown beneath the workspace name."><TextField value={environmentLabel} onChange={setEnvironmentLabel} ariaLabel="Environment label" invalid={!environmentLabel.trim()} width={260}/></Field>
      <Actions dirty={brandDirty} valid={Boolean(name.trim()&&environmentLabel.trim())}
        onSave={()=>{update('workspace',{name:name.trim(),environmentLabel:environmentLabel.trim()})}}
        onDiscard={()=>{setName(workspace.name);setEnvironmentLabel(workspace.environmentLabel)}}/>
    </SettingsPanel>

    <SettingsPanel label="Authorization" title="Operator identity" description="Sent with every recovery approval, alert-rule change, and model change this dashboard makes.">
      <Field label="Actor" hint="Recorded in the audit trail beside each action."><TextField value={actor} onChange={setActor} ariaLabel="Actor" invalid={!actor.trim()} width={260}/></Field>
      <Field label="Role" hint={roleHints[workspace.role]}>
        <SelectField value={workspace.role} ariaLabel="Operator role" options={OPERATOR_ROLES.map(role=>({value:role,label:labelize(role)}))} onChange={role=>{update('workspace',{role})}}/>
      </Field>
      <Note tone="warn">These apply only while the API runs with local identity allowed. A deployment with authentication enabled derives the actor and role from the API credential and ignores what the dashboard claims.</Note>
      <Actions dirty={actorDirty} valid={Boolean(actor.trim())}
        onSave={()=>{update('workspace',{actor:actor.trim()})}}
        onDiscard={()=>{setActor(workspace.actor)}}/>
    </SettingsPanel>
  </>
}
