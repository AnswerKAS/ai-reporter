import type { DimensionType, MetricFormat } from './semantic'

export type DatasetSource = 'clickhouse' | 'postgres' | 'oracle' | 'csv'
export type DatasetStatus = 'new' | 'ok' | 'error'

export interface DatasetField {
  name: string
  type: string
  /** Комментарий колонки в источнике — что поле означает по мнению владельцев данных. */
  comment?: string | null
}

export interface DatasetFieldSetting {
  title: string
  role: 'metric' | 'dimension' | 'ignore'
  agg?: 'sum' | 'count' | 'count_distinct' | 'avg' | 'min' | 'max' | null
  format: 'number' | 'money' | 'percent'
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
  fieldSettings: Record<string, DatasetFieldSetting>
  /** Сервер, на котором лежит датасет: тождество для отбора. У CSV его нет. */
  serverId?: string | null
  /** Имя сервера для интерфейса. Адрес в нём виден только администратору. */
  serverTitle?: string | null
  connectionKey?: string | null
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
  connectionKey?: string
  tableName?: string
  query?: string
}

export interface DatasetPatchInput {
  title?: string
  description?: string
  dsn?: string
  connectionKey?: string
  tableName?: string
  query?: string
}

/** Ответ на создание и правку: датасет + замечания и предупреждения о схеме. */
export interface DatasetSaveResult {
  dataset: Dataset
  notes?: string[]
  warnings?: string[]
}

export interface DbConnection {
  key: string
  title: string
  source: Exclude<DatasetSource, 'csv'>
  address?: string | null
}

export interface DatasetAnswerExplanation {
  source: string
  calculations: string[]
  groupBy: string[]
  filters: string[]
  orderBy: string | null
  scope: string
  limit: number
  shownRows: number
  totalRows: number | null
  hasMore: boolean
}

export interface DatasetQuestionTurn {
  /** Источник итоговой таблицы; у старых ответов используется первый результат. */
  primaryDatasetSlug?: string
  datasetSlug?: string
  datasetTitle?: string
  datasetSlugs?: string[]
  datasetTitles?: string[]
  question: string
  answer: string
  /** Название результата, предложенное моделью; отсутствует у старых сообщений. */
  title?: string
  columns: string[]
  rows: string[][]
  plan: Record<string, unknown>
  truncated: boolean
  explanation: DatasetAnswerExplanation
  sql?: string | null
  parameters?: Record<string, string | number | boolean>
  evidence?: Array<{
    datasetSlug: string
    datasetTitle: string
    title?: string
    columns: string[]
    rows: string[][]
    sql: string
    truncated: boolean
  }>
  hypotheses?: Array<{ text: string; howToCheck: string }>
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
