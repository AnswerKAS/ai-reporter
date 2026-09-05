export type NumberFormat = 'string' | 'number' | 'money' | 'percent' | 'date'

export interface KpiItem {
  label: string
  value: string | number
  format?: NumberFormat
  delta?: number
  deltaGoodWhenUp?: boolean
  hint?: string
}

export interface ChartPoint {
  [key: string]: string | number
}

export interface ChartSeries {
  key: string
  name?: string
  color?: string
  type?: 'bar' | 'line'
}

export type ChartKind = 'bar' | 'line' | 'area' | 'pie' | 'combo'

export interface ChartDetail {
  title?: string
  columns: TableColumn[]
  rowsBy: Record<string, Record<string, unknown>[]>
}

export interface MarkdownSection {
  type: 'markdown'
  content: string
  /** Ширина секции в сетке отчёта. */
  perRow?: PerRow
}

export interface KpiSection {
  type: 'kpi'
  items: KpiItem[]
  /** Фильтр отчёта, который к этой секции неприменим. */
  filterNote?: string
  /** Ширина секции в сетке отчёта. */
  perRow?: PerRow
}

export interface ChartSection {
  type: 'chart'
  kind: ChartKind
  title?: string
  data: ChartPoint[]
  xKey?: string
  series: ChartSeries[]
  detail?: ChartDetail
  /** Разрезы секции в порядке вложенности — по ним собирается точка детализации. */
  groupKeys?: string[]
  /** Ключ серии → значение второго разреза (для детализации по клику). */
  seriesSplit?: Record<string, string | number | null>
  filterNote?: string
  /** Показаны не все серии разбивки — их было больше потолка. */
  rowsNote?: string
  /** Ширина секции в сетке отчёта. */
  perRow?: PerRow
}

export interface TableColumn {
  key: string
  header: string
  format?: NumberFormat
}

export interface TableSection {
  type: 'table'
  title?: string
  columns: TableColumn[]
  rows: Record<string, unknown>[]
  /** Разрезы группировки в порядке вложенности: первый родитель, дальше потомки. */
  groupKeys?: string[]
  filterNote?: string
  /** Выдача обрезана потолком строк — читатель должен знать, что видит часть. */
  rowsNote?: string
  /** Ширина секции в сетке отчёта. */
  perRow?: PerRow
}

/** Сколько таких секций встаёт в ряд: 1 — во всю ширину, 2 — половина. */
export type PerRow = 1 | 2

export type ReportSection =
  | MarkdownSection
  | KpiSection
  | ChartSection
  | TableSection

export interface ReportFilter {
  key: string
  label: string
  /** daterange — период «с — по»: значения приходят ключами `<key>__from` и `<key>__to`. */
  kind: 'select' | 'number' | 'text' | 'daterange'
  options: string[]
  default?: string | number | null
}

export interface Report {
  id: string
  slug: string
  title: string
  description?: string
  status?: string
  createdAt: string
  updatedAt: string
  filters?: ReportFilter[]
  filterValues?: Record<string, string>
  /** Детализация включена автором: клики по секциям открывают сырые строки. */
  drilldown?: boolean
  sections: ReportSection[]
}

export interface ReportMeta {
  id: string
  slug: string
  title: string
  description?: string
  status?: string
  error?: string
  filterValues?: Record<string, string>
  updatedAt: string
}