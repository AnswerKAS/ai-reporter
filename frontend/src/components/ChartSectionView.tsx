import { useRef, useState } from 'react'
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
import { formatAxisValue, formatValue } from '../lib/format'
import { useChartTheme, type ChartTheme } from '../lib/chart-theme'
import { TableSectionView } from './TableSectionView'
import { EmptyState, Modal } from './ui'

const MONEY_KEYS = new Set(['revenue', 'amount', 'sales', 'sum'])

function kFormat(key: string): NumberFormat {
  return MONEY_KEYS.has(key) ? 'money' : 'number'
}

function XTick({ x, y, payload, fill }: { x?: number; y?: number; payload?: { value: unknown }; fill: string }) {
  const text = payload ? String(payload.value) : ''
  return (
    <text x={x} y={y} textAnchor="middle" dy={12} fontSize={11} fill={fill}>
      {text}
    </text>
  )
}

function YTick({
  x,
  y,
  payload,
  format,
  fill,
}: {
  x?: number
  y?: number
  payload?: { value?: string | number }
  format: ReturnType<typeof kFormat>
  fill: string
}) {
  return (
    <text x={x} y={y} textAnchor="end" dy={4} fontSize={11} fill={fill}>
      {payload?.value !== undefined ? formatAxisValue(payload.value, format) : ''}
    </text>
  )
}

interface TooltipEntry {
  name?: string | number
  value?: string | number
  color?: string
  dataKey?: string | number
}

/** Свой тултип: дефолтный recharts — белая коробка, нечитаемая в тёмной теме,
    и он показывает сырые числа вместо форматированных. */
function ChartTooltip({
  active,
  payload,
  label,
  theme,
}: {
  active?: boolean
  payload?: TooltipEntry[]
  label?: string | number
  theme: ChartTheme
}) {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div
      style={{
        background: theme.surface,
        border: `1px solid ${theme.line}`,
        borderRadius: 10,
        padding: '8px 10px',
        boxShadow: '0 10px 30px rgb(0 0 0 / 0.18)',
        fontSize: 13,
        color: theme.fg,
      }}
    >
      {label !== undefined && (
        <div style={{ marginBottom: 6, fontWeight: 600 }}>{String(label)}</div>
      )}
      {payload.map((entry, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, whiteSpace: 'nowrap' }}>
          <span
            aria-hidden="true"
            style={{ width: 8, height: 8, borderRadius: 999, background: entry.color, flexShrink: 0 }}
          />
          <span style={{ color: theme.fgMuted }}>{entry.name}</span>
          <span style={{ marginLeft: 'auto', fontVariantNumeric: 'tabular-nums' }}>
            {formatValue(entry.value ?? '', kFormat(String(entry.dataKey ?? '')))}
          </span>
        </div>
      ))}
    </div>
  )
}

function ChartLegend({ payload, theme }: { payload?: Array<{ value?: string; color?: string }>; theme: ChartTheme }) {
  if (!payload || payload.length === 0) return null
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        justifyContent: 'center',
        gap: '4px 16px',
        paddingTop: 8,
        fontSize: 12,
        color: theme.fgMuted,
      }}
    >
      {payload.map((entry, i) => (
        <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <span
            aria-hidden="true"
            style={{ width: 8, height: 8, borderRadius: 999, background: entry.color, flexShrink: 0 }}
          />
          {entry.value}
        </span>
      ))}
    </div>
  )
}

function pointValue(arg: unknown, xAxisKey: string, data?: ChartPoint[]): string | null {
  if (!arg || typeof arg !== 'object') return null
  const obj = arg as Record<string, unknown>
  // клик по элементу серии несёт саму точку в payload; клик по площади графика
  // отдаёт только состояние графика, и точку там находит индекс активной оси
  const active = Array.isArray(obj.activePayload) ? obj.activePayload[0] : null
  const byIndex =
    data && typeof obj.activeIndex !== 'undefined' && obj.activeIndex !== null
      ? data[Number(obj.activeIndex)]
      : null
  const source =
    (obj.payload && typeof obj.payload === 'object' ? obj.payload : null) ??
    (active && typeof active === 'object' ? (active as Record<string, unknown>).payload : null) ??
    byIndex ??
    obj
  const row = source as Partial<ChartPoint>
  const value = row[xAxisKey] ?? obj.activeLabel ?? obj.name
  return value === undefined || value === null ? null : String(value)
}

export function ChartSectionView({
  section,
  onDrill,
}: {
  section: ChartSection
  onDrill?: (point: Record<string, string | number | null>, label: string) => void
}) {
  const { kind, data, xKey, series, detail, groupKeys, seriesSplit } = section
  const [selected, setSelected] = useState<string | null>(null)
  const theme = useChartTheme()
  const xAxisKey = xKey ?? 'name'
  const firstKey = series[0]?.key

  // клик по самой линии уже обработан: контейнерный обработчик нужен лишь
  // как подстраховка для промаха мимо кривой, и дублировать его не должен
  const handled = useRef(0)

  /** Клик по точке: детализация из спеки — если она есть, иначе сырые строки.

      У точки известен разрез оси; если график разбит на серии, второй разрез
      берётся по ключу серии — карту прислал исполнитель. */
  const onPointClick = (arg: unknown, seriesKey?: string) => {
    if (seriesKey !== undefined) handled.current = Date.now()
    const value = pointValue(arg, xAxisKey, data)
    if (detail) {
      if (value) setSelected(value)
      return
    }
    if (!onDrill || !value) return
    const point: Record<string, string | number | null> = {}
    if (groupKeys?.[0]) point[groupKeys[0]] = value
    const split = seriesKey !== undefined ? seriesSplit?.[seriesKey] : undefined
    if (groupKeys?.[1] && split !== undefined) point[groupKeys[1]] = split
    // в подписи только значения разрезов: ключ серии без разбивки — это имя
    // метрики, и в заголовке окна оно ничего не объясняет
    onDrill(point, [value, split].filter((v) => v != null && v !== '').join(' · '))
  }


  /** Клик по площади графика: линию мышью не поймать, а вертикаль — легко.

      Recharts отдаёт здесь ближайшую точку оси; серию в этом случае не знаем,
      поэтому детализация ограничивается разрезом оси. */
  const onChartClick = (arg: unknown) => {
    if (Date.now() - handled.current < 150) return
    onPointClick(arg)
  }

  const color = (i: number) => theme.palette[i % theme.palette.length]

  /** Точка линии как цель клика.

      Обработчик висит на самом кружке: клик по нему до линии не всплывает,
      а попасть мышью в кривую толщиной два пикселя — задача не для читателя. */
  const drillDot = (seriesKey: string, fill: string) =>
    function DrillDot({ cx, cy, payload }: { cx?: number; cy?: number; payload?: ChartPoint }) {
      if (cx === undefined || cy === undefined) return null
      return (
        <circle
          cx={cx}
          cy={cy}
          r={3}
          fill={fill}
          className="cursor-pointer"
          onClick={() => onPointClick({ payload }, seriesKey)}
        />
      )
    }

  const tooltip = <Tooltip content={<ChartTooltip theme={theme} />} cursor={{ fill: theme.grid, fillOpacity: 0.35 }} />
  const legend = <Legend content={<ChartLegend theme={theme} />} />

  const baseAxes = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} />
      <XAxis dataKey={xAxisKey} tick={<XTick fill={theme.axis} />} tickLine={false} axisLine={{ stroke: theme.grid }} />
      <YAxis
        tick={<YTick format={kFormat(firstKey ?? '')} fill={theme.axis} />}
        tickLine={false}
        axisLine={false}
        width={56}
      />
    </>
  )

  if (data.length === 0) {
    return <EmptyState title="Нет данных" description="По текущим фильтрам за выбранный период ничего не найдено." />
  }

  let chart: React.ReactNode
  if (kind === 'bar') {
    chart = (
      <BarChart data={data}>
        {baseAxes}
        {tooltip}
        {legend}
        {series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.name ?? s.key}
            fill={s.color ?? color(i)}
            radius={[4, 4, 0, 0]}
            cursor={detail ? 'pointer' : undefined}
            onClick={(arg: unknown) => onPointClick(arg, s.key)}
          />
        ))}
      </BarChart>
    )
  } else if (kind === 'line') {
    chart = (
      <LineChart data={data} onClick={onChartClick}>
        {baseAxes}
        {tooltip}
        {legend}
        {series.map((s, i) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.name ?? s.key}
            stroke={s.color ?? color(i)}
            strokeWidth={2}
            dot={onDrill ? drillDot(s.key, s.color ?? color(i)) : false}
            activeDot={{ r: 5 }}
            onClick={(arg: unknown) => onPointClick(arg, s.key)}
          />
        ))}
      </LineChart>
    )
  } else if (kind === 'combo') {
    const hasLine = series.some((s) => s.type === 'line')
    const firstLineKey = series.find((s) => s.type === 'line')?.key
    chart = (
      <ComposedChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} />
        <XAxis
          dataKey={xAxisKey}
          tick={<XTick fill={theme.axis} />}
          tickLine={false}
          axisLine={{ stroke: theme.grid }}
        />
        <YAxis
          yAxisId="left"
          tick={<YTick format={kFormat(firstKey ?? '')} fill={theme.axis} />}
          tickLine={false}
          axisLine={false}
          width={56}
        />
        {hasLine && (
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={<YTick format={kFormat(firstLineKey ?? '')} fill={theme.axis} />}
            tickLine={false}
            axisLine={false}
            width={56}
          />
        )}
        {tooltip}
        {legend}
        {series.map((s, i) =>
          s.type === 'line' ? (
            <Line
              key={s.key}
              yAxisId={hasLine ? 'right' : 'left'}
              type="monotone"
              dataKey={s.key}
              name={s.name ?? s.key}
              stroke={s.color ?? color(i)}
              strokeWidth={2}
              dot={onDrill ? drillDot(s.key, s.color ?? color(i)) : false}
              activeDot={{ r: 4 }}
              onClick={(arg: unknown) => onPointClick(arg, s.key)}
            />
          ) : (
            <Bar
              key={s.key}
              yAxisId="left"
              dataKey={s.key}
              name={s.name ?? s.key}
              fill={s.color ?? color(i)}
              radius={[4, 4, 0, 0]}
              onClick={(arg: unknown) => onPointClick(arg, s.key)}
            />
          ),
        )}
      </ComposedChart>
    )
  } else if (kind === 'area') {
    chart = (
      <AreaChart data={data} onClick={onChartClick}>
        {baseAxes}
        {tooltip}
        {legend}
        {series.map((s, i) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.name ?? s.key}
            stroke={s.color ?? color(i)}
            fill={s.color ?? color(i)}
            fillOpacity={0.15}
            dot={onDrill ? drillDot(s.key, s.color ?? color(i)) : false}
            activeDot={{ r: 5 }}
            onClick={(arg: unknown) => onPointClick(arg, s.key)}
          />
        ))}
      </AreaChart>
    )
  } else {
    chart = (
      <PieChart>
        {tooltip}
        {legend}
        <Pie
          data={data}
          dataKey={firstKey}
          nameKey={xAxisKey}
          innerRadius={60}
          outerRadius={110}
          paddingAngle={2}
          cursor={detail || onDrill ? 'pointer' : undefined}
          onClick={(arg: unknown) => onPointClick(arg, firstKey)}
        >
          {data.map((_, i) => (
            <Cell key={i} fill={color(i)} stroke={theme.surface} />
          ))}
        </Pie>
      </PieChart>
    )
  }

  const detailRows = detail && selected ? (detail.rowsBy[selected] ?? []) : []
  const detailTitle = detail?.title ?? 'Детализация: {point}'

  return (
    <div className={detail || onDrill ? 'w-full [&_.recharts-wrapper]:cursor-pointer' : 'w-full'}>
      <ResponsiveContainer width="100%" height={300}>
        {chart}
      </ResponsiveContainer>
      {detail && selected && (
        <Modal title={detailTitle.replace('{point}', selected)} size="lg" onClose={() => setSelected(null)}>
          {detailRows.length > 0 ? (
            <TableSectionView section={{ type: 'table', columns: detail.columns, rows: detailRows } satisfies TableSection} />
          ) : (
            <p className="py-3 text-sm text-fg-muted">Нет данных по точке «{selected}»</p>
          )}
        </Modal>
      )}
    </div>
  )
}
