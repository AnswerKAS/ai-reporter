export interface User {
  id: string
  username: string
  role: 'admin' | 'user'
  createdAt: string
}

export interface GroupMember {
  id: string
  username: string
  role: string
}

export interface Group {
  id: string
  name: string
  createdAt: string
  members: GroupMember[]
}

export interface AccessEntry {
  reportSlug: string
  userId: string | null
  groupId: string | null
  username: string | null
  groupName: string | null
}

export const TOKEN_KEY = 'ai-reporter-token'
/** Почтовый сервер рассылки: настройки заводит администратор. */
export interface MailServer {
  id: string
  title: string
  kind: 'gmail' | 'exchange' | 'smtp'
  host: string
  port: number
  security: 'starttls' | 'ssl' | 'none'
  username?: string
  from_email: string
  from_name?: string
  is_default: boolean
  status: 'new' | 'ok' | 'error'
  error?: string
}

export interface MailServerInput {
  title: string
  kind: 'gmail' | 'exchange' | 'smtp'
  host?: string
  port?: number
  security?: 'starttls' | 'ssl' | 'none'
  username?: string
  password?: string
  fromEmail: string
  fromName?: string
  isDefault?: boolean
}

/** Рассылка отчёта: сотрудник выбирает время, формат и получателей. */
export interface ReportSchedule {
  id: string
  report_slug: string
  author_id: string
  server_id?: string
  recipients: string[]
  format: 'xlsx' | 'pdf'
  kind: 'once' | 'daily' | 'weekly' | 'monthly'
  at_time: string
  weekday?: number
  day_of_month?: number
  run_at?: string
  enabled: boolean
  next_run_at?: string
  last_run_at?: string
  last_status?: 'ok' | 'error'
  last_error?: string
}

export interface ScheduleInput {
  recipients: string[]
  format: 'xlsx' | 'pdf'
  kind: 'once' | 'daily' | 'weekly' | 'monthly'
  atTime?: string
  weekday?: number | null
  dayOfMonth?: number | null
  runAt?: string | null
  serverId?: string | null
  enabled?: boolean
}
