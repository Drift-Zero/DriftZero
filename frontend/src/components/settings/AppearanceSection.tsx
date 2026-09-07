import { useSettings } from '../../context/SettingsContext'
import { formatScore,fullDate,shortTime,timeAgo,timeZoneLabel } from '../../utils/format'
import { Field,Note,Segmented,SettingsPanel,Toggle } from './controls'

/* Fixed when the module loads so the preview reads as one worked example rather than a
   ticking clock that re-renders the panel. */
const sample=new Date(Date.now()-5.5*60*1000).toISOString()

export function AppearanceSection(){
  const{settings,update}=useSettings()
  const{appearance,connection}=settings

  return <>
    <SettingsPanel label="Interface" title="Layout" description="Applies immediately, across every page.">
      <Field label="Density" hint="Compact tightens page padding and card spacing to fit more on screen.">
        <Segmented label="Density" value={appearance.density} onChange={density=>{update('appearance',{density})}}
          options={[{value:'comfortable',label:'Comfortable'},{value:'compact',label:'Compact'}]}/>
      </Field>
      <Toggle label="Reduce motion" hint="Stops chart transitions, the live pulse, and the recovery spinner animating."
        checked={appearance.reducedMotion} onChange={reducedMotion=>{update('appearance',{reducedMotion})}}/>
      <Toggle label="Show demo controls" hint={connection.mode==='demo'?'The scenario switcher pinned to the bottom of the page.':'Only visible while the data source is set to demo data.'}
        checked={appearance.showDemoControls} onChange={showDemoControls=>{update('appearance',{showDemoControls})}}/>
    </SettingsPanel>

    <SettingsPanel label="Formatting" title="Numbers and time" description="Controls how health scores and event times are written throughout the dashboard.">
      <Field label="Timestamps" hint="Relative reads at a glance; absolute is what you want beside a log.">
        <Segmented label="Timestamp format" value={appearance.timestampFormat} onChange={timestampFormat=>{update('appearance',{timestampFormat})}}
          options={[{value:'relative',label:'Relative'},{value:'absolute',label:'Absolute'}]}/>
      </Field>
      <Field label="Time zone" hint={`Times currently render in ${timeZoneLabel()}.`}>
        <Segmented label="Time zone" value={appearance.timeZone} onChange={timeZone=>{update('appearance',{timeZone})}}
          options={[{value:'local',label:'Local'},{value:'utc',label:'UTC'}]}/>
      </Field>
      <Field label="Health score precision" hint="Decimal places on health scores and dimension metrics.">
        <Segmented label="Health score precision" value={appearance.scoreDecimals} onChange={scoreDecimals=>{update('appearance',{scoreDecimals})}}
          options={[{value:0,label:'0'},{value:1,label:'0.0'},{value:2,label:'0.00'}]}/>
      </Field>
      <div className="settings-preview">
        <span className="panel-label">Preview</span>
        <div><span>Health score</span><strong>{formatScore(87.416)}</strong></div>
        <div><span>Evaluated</span><strong>{timeAgo(sample)}</strong></div>
        <div><span>Event time</span><strong>{shortTime(sample)}</strong></div>
        <div><span>Full date</span><strong>{fullDate(sample)}</strong></div>
      </div>
      <Note>Precision is a display choice only. Scores are stored and compared at full precision, and alert thresholds are unaffected.</Note>
    </SettingsPanel>
  </>
}
