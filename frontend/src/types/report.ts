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
}

export interface KpiSection {
  type: 'kpi'
  items: KpiItem[]
  /** Фильтр отчёта, который к этой секции неприменим. */
  filterNote?: string
}

export interface ChartSection {
  type: 'chart'
  kind: ChartKind
  title?: string
  data: ChartPoint[]
  xKey?: string
  series: ChartSeries[]
  detail?: ChartDetail
  filterNote?: string
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
  filterNote?: string
  /** Выдача обрезана потолком строк — читатель должен знать, что видит часть. */
  rowsNote?: string
}

export type ReportSection =
  | MarkdownSection
  | KpiSection
  | ChartSection
  | TableSection

export interface ReportFilter {
  key: string
  label: string
  kind: 'select' | 'number' | 'text'
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