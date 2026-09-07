import { useMemo } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ChartTooltip } from './tooltip'
import { LiveLine } from './live-line'
import { LiveLineChart, type LiveLinePoint } from './live-line-chart'
import { LiveXAxis } from './live-x-axis'
import { LiveYAxis } from './live-y-axis'
import type { HealthPoint } from '../../types/dashboard'
import { shortTime } from '../../utils/format'

interface HealthChartProps { data: HealthPoint[]; height?: number; showMetrics?: boolean }

/**
 * The live chart expects a stream whose latest point is close to "now". API
 * snapshots can be older than that, so preserve their spacing while anchoring
 * the newest observed score to the current time. Values remain API-derived.
 */
function useLivePoints(data: HealthPoint[]): LiveLinePoint[] {
  return useMemo(() => {
    const points = data
      .map((point) => ({ time: Date.parse(point.time), value: point.score }))
      .filter((point): point is { time: number; value: number } => Number.isFinite(point.time) && typeof point.value === 'number')
      .sort((left, right) => left.time - right.time)
    const last = points.at(-1)
    if (!last) return []
    const anchor = Date.now()
    return points.map((point) => ({ time: (anchor - (last.time - point.time)) / 1000, value: point.value }))
  }, [data])
}

function LiveHealthChart({ data, height = 230 }: Pick<HealthChartProps, 'data' | 'height'>) {
  const points = useLivePoints(data)
  const latest = points.at(-1)?.value ?? 0
  const span = points.length > 1 ? (points.at(-1)!.time - points[0]!.time) : 60
  const windowSeconds = Math.max(60, Math.ceil(span + 30))

  if (!points.length) return <div className="health-chart live-health-chart" style={{ height }} />

  return <LiveLineChart
    className="health-chart live-health-chart"
    data={points}
    value={latest}
    window={windowSeconds}
    nowOffsetUnits={1}
    numXTicks={5}
    style={{ height }}
    margin={{ top: 16, right: 52, bottom: 32, left: 30 }}
  >
    <LiveLine
      dataKey="value"
      stroke="var(--chart-line-primary)"
      strokeWidth={2.5}
      formatValue={(value) => `${Math.round(value)}`}
      momentumColors={{ up: 'var(--green)', down: 'var(--red)', flat: 'var(--chart-line-primary)' }}
    />
    <ChartTooltip
      showDatePill={false}
      indicatorDasharray="3 3"
      rows={(point) => [{ color: 'var(--chart-line-primary)', label: 'Health score', value: Math.round(Number(point.value)) }]}
    />
    <LiveXAxis formatTime={(time) => shortTime(new Date(time).toISOString())} />
    <LiveYAxis position="left" formatValue={(value) => `${Math.round(value)}`} allowDecimals={false} />
  </LiveLineChart>
}

export function HealthChart({ data, height = 230, showMetrics = false }: HealthChartProps) {
  if (!showMetrics) return <LiveHealthChart data={data} height={height} />

  return <div className="health-chart" style={{ height }}><ResponsiveContainer width="100%" height="100%"><LineChart data={data} margin={{ top: 12, right: 10, bottom: 4, left: -22 }}><CartesianGrid stroke="#22262b" strokeDasharray="3 5" vertical={false} /><XAxis dataKey="time" tickFormatter={shortTime} tick={{ fill: '#5f6670', fontSize: 10, fontFamily: 'DM Mono' }} axisLine={false} tickLine={false} /><YAxis domain={[0, 100]} ticks={[25, 50, 75, 100]} tick={{ fill: '#5f6670', fontSize: 10, fontFamily: 'DM Mono' }} axisLine={false} tickLine={false} /><Tooltip content={<LegacyChartTooltip />} /><ReferenceLine y={70} stroke="#715c31" strokeDasharray="4 4" /><Line type="monotone" dataKey="score" name="Health" stroke="#53e6a4" strokeWidth={2.5} dot={false} activeDot={{ r: 4, fill: '#08090b', stroke: '#53e6a4', strokeWidth: 2 }} /><Line type="monotone" dataKey="groundedness" name="Groundedness" stroke="#7fa7ff" strokeWidth={1.5} dot={false} /><Line type="monotone" dataKey="stability" name="Stability" stroke="#b894ff" strokeWidth={1.5} dot={false} /></LineChart></ResponsiveContainer></div>
}

function LegacyChartTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number; color: string }>; label?: string }) {
  if (!active || !payload?.length) return null
  return <div className="chart-tooltip"><span>{label ? shortTime(label) : ''}</span>{payload.map((item) => <div key={item.name}><i style={{ background: item.color }} />{item.name}<strong>{Math.round(item.value)}</strong></div>)}</div>
}
