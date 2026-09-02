export type DatasetSource = 'clickhouse' | 'postgres' | 'csv'
export type DatasetStatus = 'new' | 'ok' | 'error'

export interface DatasetField {
  name: string
  type: string
}

export interface Dataset {
  slug: string
  title: string
  description?: string | null
  source: DatasetSource
  tableName?: string | null
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
}

export interface DatasetCreateInput {
  slug: string
  title: string
  description?: string
  source: DatasetSource
  dsn?: string
  tableName?: string
}

export interface SkillInfo {
  name: string
  domain: string
  path: string
}

export type SkillDraftStatus =
  | 'generating'
  | 'draft'
  | 'review'
  | 'checked'
  | 'rejected'
  | 'failed'
  | 'unavailable'
  | 'improving'
  | 'checking'
  | 'published'

export interface SkillDraft {
  id: string
  domain: string
  name: string
  title: string
  description: string
  datasets: string[]
  content: string
  status: SkillDraftStatus
  issues: string[]
  authorId: string
  createdAt: string
  updatedAt: string
}
