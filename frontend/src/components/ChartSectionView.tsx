import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ChartSection, NumberFormat } from '../types/report'
import { formatValue } from '../lib/format'

const PALETTE = ['#4f46e5', '#0ea5e9', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6']

const MONEY_KEYS = new Set(['revenue', 'amount', 'sales', 'sum'])

function kFormat(key: string): NumberFormat {
  return MONEY_KEYS.has(key) ? 'money' : 'number'
}

function XTick({ x, y, payload }: { x?: number; y?: number; payload?: { value: unknown } }) {
  const text = payload ? String(payload.value) : ''
  return (
    <text x={x} y={y} textAnchor="middle" dy={12} fontSize={11} fill="#6b7280">
      {text}
    </text>
  )
}

function YTick({ x, y, payload, format }: { x?: number; y?: number; payload?: { value?: string | number }; format: ReturnType<typeof kFormat> }) {
  return (
    <text x={x} y={y} textAnchor="end" dy={4} fontSize={11} fill="#6b7280">
      {payload?.value !== undefined ? formatValue(payload.value, format) : ''}
    </text>
  )
}

export function ChartSectionView({ section }: { section: ChartSection }) {
  const { kind, data, xKey, series } = section
  const xAxisKey = xKey ?? 'name'
  const firstKey = series[0]?.key

  const baseAxes = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
      <XAxis dataKey={xAxisKey} tick={<XTick />} tickLine={false} axisLine={{ stroke: '#e5e7eb' }} />
      <YAxis tick={<YTick format={kFormat(firstKey ?? '')} />} tickLine={false} axisLine={false} width={70} />
    </>
  )

  let chart: React.ReactNode
  if (kind === 'bar') {
    chart = (
      <BarChart data={data}>
        {baseAxes}
        <Tooltip />
        <Legend />
        {series.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} name={s.name ?? s.key} fill={s.color ?? PALETTE[i % PALETTE.length]} radius={[4, 4, 0, 0]} />
        ))}
      </BarChart>
    )
  } else if (kind === 'line') {
    chart = (
      <LineChart data={data}>
        {baseAxes}
        <Tooltip />
        <Legend />
        {series.map((s, i) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.name ?? s.key} stroke={s.color ?? PALETTE[i % PALETTE.length]} strokeWidth={2} dot={false} />
        ))}
      </LineChart>
    )
  } else if (kind === 'area') {
    chart = (
      <AreaChart data={data}>
        {baseAxes}
        <Tooltip />
        <Legend />
        {series.map((s, i) => (
          <Area key={s.key} type="monotone" dataKey={s.key} name={s.name ?? s.key} stroke={s.color ?? PALETTE[i % PALETTE.length]} fill={s.color ?? PALETTE[i % PALETTE.length]} fillOpacity={0.15} />
        ))}
      </AreaChart>
    )
  } else {
    chart = (
      <PieChart>
        <Tooltip />
        <Legend />
        <Pie data={data} dataKey={firstKey} nameKey={xAxisKey} innerRadius={60} outerRadius={110} paddingAngle={2}>
          {data.map((_, i) => (
            <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
          ))}
        </Pie>
      </PieChart>
    )
  }

  return (
    <div className="chart-block">
      <ResponsiveContainer width="100%" height={300}>
        {chart}
      </ResponsiveContainer>
    </div>
  )
}