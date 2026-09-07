import { useId,type ReactNode } from 'react'

export function SettingsPanel({label,title,description,children,actions}:{label:string;title:string;description?:string;children:ReactNode;actions?:ReactNode}){
  return <section className="panel settings-panel">
    <div className="panel-heading"><div><span className="panel-label">{label}</span><h2>{title}</h2>{description&&<p className="settings-panel-note">{description}</p>}</div>{actions}</div>
    <div className="settings-fields">{children}</div>
  </section>
}

export function Field({label,hint,children,control}:{label:string;hint?:string;children?:ReactNode;control?:ReactNode}){
  return <div className="settings-field"><div><span>{label}</span>{hint&&<small>{hint}</small>}</div><div className="settings-control">{control??children}</div></div>
}

/* Labelled with the field text rather than an icon: a switch whose only label is its own visual
   state is unreadable to a screen reader and ambiguous when several sit in a column. */
export function Toggle({checked,onChange,label,hint,disabled}:{checked:boolean;onChange:(next:boolean)=>void;label:string;hint?:string;disabled?:boolean}){
  const id=useId()
  return <div className="settings-field">
    <div><span id={id}>{label}</span>{hint&&<small>{hint}</small>}</div>
    <div className="settings-control">
      <button type="button" role="switch" aria-checked={checked} aria-labelledby={id} disabled={disabled} className={`switch${checked?' on':''}`} onClick={()=>{onChange(!checked)}}><i/></button>
    </div>
  </div>
}

export function Segmented<T extends string|number>({value,options,onChange,label}:{value:T;options:Array<{value:T;label:string}>;onChange:(next:T)=>void;label:string}){
  return <div className="segmented" role="group" aria-label={label}>
    {options.map(option=><button key={String(option.value)} type="button" aria-pressed={option.value===value} className={option.value===value?'active':''} onClick={()=>{onChange(option.value)}}>{option.label}</button>)}
  </div>
}

export function TextField({value,onChange,placeholder,invalid,type='text',width,ariaLabel,disabled}:{value:string;onChange:(next:string)=>void;placeholder?:string;invalid?:boolean;type?:string;width?:number;ariaLabel:string;disabled?:boolean}){
  return <input className={`settings-input${invalid?' invalid':''}`} type={type} value={value} placeholder={placeholder} aria-label={ariaLabel} aria-invalid={invalid??false} disabled={disabled} style={width?{width}:undefined} onChange={event=>{onChange(event.target.value)}}/>
}

export function NumberField({value,onChange,min,max,step=1,ariaLabel,disabled}:{value:number|null;onChange:(next:number|null)=>void;min?:number;max?:number;step?:number;ariaLabel:string;disabled?:boolean}){
  return <input className="settings-input number" type="number" value={value??''} min={min} max={max} step={step} aria-label={ariaLabel} disabled={disabled} onChange={event=>{const raw=event.target.value;onChange(raw===''?null:Number(raw))}}/>
}

export function SelectField<T extends string>({value,options,onChange,ariaLabel,disabled}:{value:T;options:Array<{value:T;label:string}>;onChange:(next:T)=>void;ariaLabel:string;disabled?:boolean}){
  return <select className="settings-select" value={value} aria-label={ariaLabel} disabled={disabled} onChange={event=>{onChange(event.target.value as T)}}>
    {options.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}
  </select>
}

export function Note({tone='info',children}:{tone?:'info'|'warn'|'danger';children:ReactNode}){return <p className={`settings-note ${tone}`}>{children}</p>}
