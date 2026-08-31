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
}

export type ChartKind = 'bar' | 'line' | 'area' | 'pie'

export interface MarkdownSection {
  type: 'markdown'
  content: string
}

export interface KpiSection {
  type: 'kpi'
  items: KpiItem[]
}

export interface ChartSection {
  type: 'chart'
  kind: ChartKind
  title?: string
  data: ChartPoint[]
  xKey?: string
  series: ChartSeries[]
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
  skill?: string
  status?: string
  createdAt: string
  updatedAt: string
  params?: Record<string, string>
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
  skill?: string
  params?: Record<string, string>
  filterValues?: Record<string, string>
  updatedAt: string
}