import { useEffect, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
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
import type { ChartPoint, ChartSection, NumberFormat, TableSection } from '../types/report'
import { formatValue } from '../lib/format'
import { TableSectionView } from './TableSectionView'

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

function pointValue(arg: unknown, xAxisKey: string): string | null {
  if (!arg || typeof arg !== 'object') return null
  const obj = arg as Record<string, unknown>
  const row = (obj.payload && typeof obj.payload === 'object' ? obj.payload : obj) as Partial<ChartPoint>
  const value = row[xAxisKey] ?? obj.name
  return value === undefined || value === null ? null : String(value)
}

export function ChartSectionView({ section }: { section: ChartSection }) {
  const { kind, data, xKey, series, detail } = section
  const [selected, setSelected] = useState<string | null>(null)
  const xAxisKey = xKey ?? 'name'
  const firstKey = series[0]?.key

  useEffect(() => {
    if (!selected) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelected(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected])

  const onPointClick = (arg: unknown) => {
    if (!detail) return
    const value = pointValue(arg, xAxisKey)
    if (value) setSelected(value)
  }

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
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.name ?? s.key}
            fill={s.color ?? PALETTE[i % PALETTE.length]}
            radius={[4, 4, 0, 0]}
            cursor={detail ? 'pointer' : undefined}
            onClick={onPointClick}
          />
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
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.name ?? s.key}
            stroke={s.color ?? PALETTE[i % PALETTE.length]}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 5 }}
            onClick={onPointClick}
          />
        ))}
      </LineChart>
    )
  } else if (kind === 'combo') {
    const hasLine = series.some((s) => s.type === 'line')
    const firstLineKey = series.find((s) => s.type === 'line')?.key
    chart = (
      <ComposedChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey={xAxisKey} tick={<XTick />} tickLine={false} axisLine={{ stroke: '#e5e7eb' }} />
        <YAxis yAxisId="left" tick={<YTick format={kFormat(firstKey ?? '')} />} tickLine={false} axisLine={false} width={70} />
        {hasLine && (
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={<YTick format={kFormat(firstLineKey ?? '')} />}
            tickLine={false}
            axisLine={false}
            width={70}
          />
        )}
        <Tooltip />
        <Legend />
        {series.map((s, i) =>
          s.type === 'line' ? (
            <Line
              key={s.key}
              yAxisId={hasLine ? 'right' : 'left'}
              type="monotone"
              dataKey={s.key}
              name={s.name ?? s.key}
              stroke={s.color ?? PALETTE[i % PALETTE.length]}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              onClick={onPointClick}
            />
          ) : (
            <Bar
              key={s.key}
              yAxisId="left"
              dataKey={s.key}
              name={s.name ?? s.key}
              fill={s.color ?? PALETTE[i % PALETTE.length]}
              radius={[4, 4, 0, 0]}
              onClick={onPointClick}
            />
          ),
        )}
      </ComposedChart>
    )
  } else if (kind === 'area') {
    chart = (
      <AreaChart data={data}>
        {baseAxes}
        <Tooltip />
        <Legend />
        {series.map((s, i) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.name ?? s.key}
            stroke={s.color ?? PALETTE[i % PALETTE.length]}
            fill={s.color ?? PALETTE[i % PALETTE.length]}
            fillOpacity={0.15}
            activeDot={{ r: 5 }}
            onClick={onPointClick}
          />
        ))}
      </AreaChart>
    )
  } else {
    chart = (
      <PieChart>
        <Tooltip />
        <Legend />
        <Pie data={data} dataKey={firstKey} nameKey={xAxisKey} innerRadius={60} outerRadius={110} paddingAngle={2} cursor={detail ? 'pointer' : undefined} onClick={onPointClick}>
          {data.map((_, i) => (
            <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
          ))}
        </Pie>
      </PieChart>
    )
  }

  const detailRows = detail && selected ? (detail.rowsBy[selected] ?? []) : []
  const detailTitle = detail?.title ?? 'Детализация: {point}'

  return (
    <div className={detail ? 'chart-block chart-clickable' : 'chart-block'}>
      <ResponsiveContainer width="100%" height={300}>
        {chart}
      </ResponsiveContainer>
      {detail && selected && (
        <div className="chart-detail-overlay" onClick={() => setSelected(null)}>
          <div className="chart-detail-modal" onClick={(e) => e.stopPropagation()}>
            <div className="chart-detail-head">
              <h3>{detailTitle.replace('{point}', selected)}</h3>
              <button type="button" className="chart-detail-close" onClick={() => setSelected(null)} aria-label="Закрыть">
                ×
              </button>
            </div>
            {detailRows.length > 0 ? (
              <TableSectionView section={{ type: 'table', columns: detail.columns, rows: detailRows } satisfies TableSection} />
            ) : (
              <p className="chart-detail-empty">Нет данных по точке «{selected}»</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
