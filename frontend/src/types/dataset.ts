import type { DimensionType, MetricFormat } from './semantic'

export type DatasetSource = 'clickhouse' | 'postgres' | 'oracle' | 'csv'
export type DatasetStatus = 'new' | 'ok' | 'error'

export interface DatasetField {
  name: string
  type: string
  /** Комментарий колонки в источнике — что поле означает по мнению владельцев данных. */
  comment?: string | null
}

export interface Dataset {
  slug: string
  title: string
  description?: string | null
  source: DatasetSource
  tableName?: string | null
  /** Текст запроса-источника. Приходит только администратору. */
  query?: string | null
  /** Источник — SQL-запрос, а не таблица. Видно всем. */
  isQuery: boolean
  file?: string | null
  fields: DatasetField[]
  status: DatasetStatus
  error?: string | null
  createdAt: string
  updatedAt: string
}

export interface DatasetPreview {
  columns: string[]
  rows: string[][]
  truncated: boolean
}

export interface DatasetDetail {
  dataset: Dataset
  preview?: DatasetPreview | null
  /** Замечания к запросу-источнику: LIMIT внутри, ORDER BY, SETTINGS. */
  notes?: string[]
}

export interface DatasetCreateInput {
  slug: string
  title: string
  description?: string
  source: DatasetSource
  dsn?: string
  tableName?: string
  query?: string
}

export interface DatasetPatchInput {
  title?: string
  description?: string
  dsn?: string
  tableName?: string
  query?: string
}

/** Ответ на создание и правку: датасет + замечания и предупреждения о схеме. */
export interface DatasetSaveResult {
  dataset: Dataset
  notes?: string[]
  warnings?: string[]
}

export interface DimensionSuggestion {
  slug: string
  title: string
  field: string
  type: DimensionType
  column: string
  columnType: string
  exists: boolean
  selected: boolean
}

export interface MetricSuggestion {
  slug: string
  title: string
  expression: string
  format: MetricFormat
  unit?: string | null
  column: string
  columnType: string
  exists: boolean
  selected: boolean
}

export interface DatasetSuggestions {
  dimensions: DimensionSuggestion[]
  metrics: MetricSuggestion[]
  notes: string[]
}

export interface DatasetSemanticInput {
  dimensions: { slug: string; title: string; field: string; type: DimensionType }[]
  metrics: { slug: string; title: string; expression: string; format: MetricFormat; unit?: string | null }[]
}

export interface DatasetSemanticResult {
  createdDimensions: number
  createdMetrics: number
  skipped: string[]
  failed: { slug: string; error: string }[]
}
