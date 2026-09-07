import { Area,CartesianGrid,ComposedChart,Line,ReferenceLine,ResponsiveContainer,Tooltip,XAxis,YAxis } from 'recharts'
import type { HealthPoint } from '../../types/dashboard'
import { shortTime } from '../../utils/format'

/* A health window is often only a handful of snapshots, where a bare 2px line reads as an
   almost-empty panel. The gradient gives the series some weight, and points are drawn only
   while the series is short enough for them to stay legible. */
const DOT_LIMIT = 14

export function HealthChart({data,height=230,showMetrics=false}:{data:HealthPoint[];height?:number;showMetrics?:boolean}){
  const sparse=data.length<=DOT_LIMIT
  const dot=sparse?{r:2.5,fill:'#08090b',stroke:'#53e6a4',strokeWidth:1.5}:false
  return <div className="health-chart" style={{height}}><ResponsiveContainer width="100%" height="100%"><ComposedChart data={data} margin={{top:12,right:10,bottom:4,left:-22}}>
    <defs><linearGradient id="healthFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#53e6a4" stopOpacity={.22}/><stop offset="100%" stopColor="#53e6a4" stopOpacity={0}/></linearGradient></defs>
    <CartesianGrid stroke="#22262b" strokeDasharray="3 5" vertical={false}/>
    <XAxis dataKey="time" tickFormatter={shortTime} tick={{fill:'#5f6670',fontSize:10,fontFamily:'DM Mono'}} axisLine={false} tickLine={false}/>
    <YAxis domain={[0,100]} ticks={[25,50,75,100]} tick={{fill:'#5f6670',fontSize:10,fontFamily:'DM Mono'}} axisLine={false} tickLine={false}/>
    <Tooltip content={<ChartTooltip/>}/>
    <ReferenceLine y={70} stroke="#715c31" strokeDasharray="4 4"/>
    <Area type="monotone" dataKey="score" stroke="none" fill="url(#healthFill)" isAnimationActive={false} activeDot={false} legendType="none" tooltipType="none"/>
    <Line type="monotone" dataKey="score" name="Health" stroke="#53e6a4" strokeWidth={2.5} dot={dot} activeDot={{r:4,fill:'#08090b',stroke:'#53e6a4',strokeWidth:2}}/>
    {showMetrics&&<Line type="monotone" dataKey="groundedness" name="Groundedness" stroke="#7fa7ff" strokeWidth={1.5} dot={false}/>}
    {showMetrics&&<Line type="monotone" dataKey="stability" name="Stability" stroke="#b894ff" strokeWidth={1.5} dot={false}/>}
  </ComposedChart></ResponsiveContainer></div>
}
function ChartTooltip({active,payload,label}:{active?:boolean;payload?:Array<{name:string;value:number;color:string}>;label?:string}){if(!active||!payload?.length)return null;return <div className="chart-tooltip"><span>{label?shortTime(label):''}</span>{payload.map(item=><div key={item.name}><i style={{background:item.color}}/>{item.name}<strong>{Math.round(item.value)}</strong></div>)}</div>}
