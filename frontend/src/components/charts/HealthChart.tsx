import { useEffect,useMemo,useState } from 'react'
import { Area,CartesianGrid,ComposedChart,Line,ReferenceLine,ResponsiveContainer,Tooltip,XAxis,YAxis } from 'recharts'
import type { HealthPoint } from '../../types/dashboard'
import { shortTime } from '../../utils/format'
import { WARNING_SCORE } from '../../utils/health'

/* A health window is often only a handful of snapshots, where a bare 2px line reads as an
   almost-empty panel. The gradient gives the series some weight, and points are drawn only
   while the series is short enough for them to stay legible. */
const DOT_LIMIT = 14
/* The final x tick is centred on the last point, so it needs roughly half a label of room or
   the clock time is cut off at the right edge. */
const RIGHT_GUTTER = 26
const DRAW_MS = 1100

type DotProps = { cx?:number; cy?:number; index?:number }

function useReducedMotion(){
  const [reduced,setReduced]=useState(()=>typeof window!=='undefined'&&window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  useEffect(()=>{
    const query=window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange=()=>{setReduced(query.matches)}
    query.addEventListener('change',onChange)
    return ()=>{query.removeEventListener('change',onChange)}
  },[])
  return reduced
}

/* The trend redraws whenever the dashboard reloads - every 1.5s while a recovery is being
   polled. Replaying the draw-in each time would strobe, so the intro is switched off once it
   has finished and later updates simply settle into place. Switching it off on the very next
   render instead would cut the animation short mid-flight. */
function useIntroAnimation(enabled:boolean){
  const [introDone,setIntroDone]=useState(false)
  useEffect(()=>{
    const timer=setTimeout(()=>{setIntroDone(true)},DRAW_MS+400)
    return ()=>{clearTimeout(timer)}
  },[])
  return enabled&&!introDone
}

export function HealthChart({data,height=230,showMetrics=false}:{data:HealthPoint[];height?:number;showMetrics?:boolean}){
  const reducedMotion=useReducedMotion()
  const animate=useIntroAnimation(!reducedMotion)
  const sparse=data.length<=DOT_LIMIT
  const lastIndex=data.length-1

  /* Held stable across renders: a fresh component identity would remount the beacon and
     restart its pulse on every poll. */
  const renderDot=useMemo(()=>{
    function HealthDot({cx,cy,index}:DotProps){
      if(cx===undefined||cy===undefined)return <g/>
      if(index===lastIndex)return <g className="chart-beacon">
        <circle className="beacon-ring" cx={cx} cy={cy} r={3.5}/>
        <circle className="beacon-core" cx={cx} cy={cy} r={3}/>
      </g>
      if(!sparse)return <g/>
      return <circle cx={cx} cy={cy} r={2.5} fill="#08090b" stroke="#53e6a4" strokeWidth={1.5}/>
    }
    return HealthDot
  },[lastIndex,sparse])

  return <div className={`health-chart${reducedMotion?' still':''}`} style={{height}}><ResponsiveContainer width="100%" height="100%"><ComposedChart data={data} margin={{top:12,right:RIGHT_GUTTER,bottom:4,left:-22}}>
    <defs><linearGradient id="healthFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#53e6a4" stopOpacity={.22}/><stop offset="100%" stopColor="#53e6a4" stopOpacity={0}/></linearGradient></defs>
    <CartesianGrid stroke="#22262b" strokeDasharray="3 5" vertical={false}/>
    <XAxis dataKey="time" tickFormatter={shortTime} tick={{fill:'#5f6670',fontSize:10,fontFamily:'DM Mono'}} axisLine={false} tickLine={false}/>
    <YAxis domain={[0,100]} ticks={[25,50,75,100]} tick={{fill:'#5f6670',fontSize:10,fontFamily:'DM Mono'}} axisLine={false} tickLine={false}/>
    <Tooltip content={<ChartTooltip/>}/>
    <ReferenceLine y={WARNING_SCORE} stroke="#715c31" strokeDasharray="4 4"/>
    <Area type="monotone" dataKey="score" stroke="none" fill="url(#healthFill)" isAnimationActive={animate} animationDuration={DRAW_MS} animationEasing="ease-out" activeDot={false} legendType="none" tooltipType="none"/>
    <Line type="monotone" dataKey="score" name="Health" stroke="#53e6a4" strokeWidth={2.5} dot={renderDot} isAnimationActive={animate} animationDuration={DRAW_MS} animationEasing="ease-out" activeDot={{r:4,fill:'#08090b',stroke:'#53e6a4',strokeWidth:2}}/>
    {showMetrics&&<Line type="monotone" dataKey="groundedness" name="Groundedness" stroke="#7fa7ff" strokeWidth={1.5} dot={false} isAnimationActive={animate} animationDuration={DRAW_MS} animationBegin={140} animationEasing="ease-out"/>}
    {showMetrics&&<Line type="monotone" dataKey="stability" name="Stability" stroke="#b894ff" strokeWidth={1.5} dot={false} isAnimationActive={animate} animationDuration={DRAW_MS} animationBegin={280} animationEasing="ease-out"/>}
  </ComposedChart></ResponsiveContainer></div>
}
function ChartTooltip({active,payload,label}:{active?:boolean;payload?:Array<{name:string;value:number;color:string}>;label?:string}){if(!active||!payload?.length)return null;return <div className="chart-tooltip"><span>{label?shortTime(label):''}</span>{payload.map(item=><div key={item.name}><i style={{background:item.color}}/>{item.name}<strong>{Math.round(item.value)}</strong></div>)}</div>}
