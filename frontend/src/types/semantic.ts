export type MetricFormat = 'number' | 'money' | 'percent' | 'string' | 'date'
export type DimensionType = 'string' | 'date' | 'number'
export type Grain = 'day' | 'week' | 'month' | 'quarter' | 'year'

export interface Metric {
  slug: string
  title: string
  description?: string
  datasetSlug: string
  expression: string
  format: MetricFormat
  unit?: string
  status: 'new' | 'ok' | 'error'
  error?: string
  createdAt: string
  updatedAt: string
}

export interface Dimension {
  slug: string
  title: string
  description?: string
  datasetSlug: string
  field: string
  type: DimensionType
  createdAt: string
  updatedAt: string
}

/** Отчёт, ссылающийся на элемент словаря. */
export interface UsageReport {
  slug: string
  title: string
}

/** Где используется словарь: slug показателя или разреза → отчёты с ним.

    Ссылок нигде не хранится — свод считается по декларациям отчётов, поэтому
    приезжает вместе со словарём и отдельно не обновляется. */
export type SemanticUsage = Record<string, UsageReport[]>

export interface DatasetLink {
  id: string
  title?: string
  leftSlug: string
  rightSlug: string
  leftField: string
  rightField: string
  kind: 'inner' | 'left'
  createdAt: string
}

/** Секция отчёта: что показать, а не как посчитать. */
export interface SectionDefinition {
  type: 'kpi' | 'chart' | 'table'
  title?: string | null
  kind?: 'bar' | 'line' | 'area' | 'pie' | 'combo' | null
  /** Сколько секций в ряд: 1 — во всю ширину, 2 — половина. Не задано — по виду секции. */
  perRow?: 1 | 2 | null
  metrics: string[]
  by: string[]
  grain?: Grain | null
  orderBy?: string | null
  orderDir: 'asc' | 'desc'
  limit?: number | null
}

export interface FilterDefinition {
  dimension: string
  label?: string | null
  kind: 'select' | 'text' | 'number' | 'daterange'
}

/** Поле, взятое автором отчёта прямо из колонки датасета. */
export interface ReportField {
  key: string
  title: string
  datasetSlug: string
  field: string
  role: 'metric' | 'dimension'
  agg?: 'sum' | 'count' | 'count_distinct' | 'avg' | 'min' | 'max' | null
  type: DimensionType
  format: 'number' | 'money' | 'percent'
}

/** Поле, собранное пользователем из выбранных показателей: SQL он не пишет. */
export interface ComputedField {
  key: string
  title: string
  left: string
  op: '+' | '-' | '*' | '/'
  right: string
  format: 'number' | 'money' | 'percent'
}

export interface ReportDefinition {
  /** Детализация: сырые строки по кнопке и по клику на секцию. */
  drilldown?: boolean
  sections: SectionDefinition[]
  filters: FilterDefinition[]
  fields?: ReportField[]
  computed?: ComputedField[]
}

export interface MetricInput {
  slug: string
  title: string
  description?: string
  datasetSlug: string
  expression: string
  format: MetricFormat
  unit?: string
}

export interface DimensionInput {
  slug: string
  title: string
  description?: string
  datasetSlug: string
  field: string
  type: DimensionType
}

export interface LinkInput {
  title?: string
  leftSlug: string
  rightSlug: string
  leftField: string
  rightField: string
  kind: 'inner' | 'left'
}
