import type { Report, ReportFacets, ReportMeta, ReportPage, ReportQuery } from '../types/report'
import type {
  AccessEntry,
  Group,
  MailServer,
  MailServerInput,
  ReportSchedule,
  ScheduleDigestItem,
  ScheduleInput,
  ScheduleServer,
  User,
} from '../types/user'
import type {
  Dataset,
  DatasetCreateInput,
  DatasetDetail,
  DatasetPatchInput,
  DatasetSaveResult,
  DatasetSemanticInput,
  DatasetSemanticResult,
  DatasetSuggestions,
} from '../types/dataset'
import type {
  ComputedField,
  DatasetLink,
  Dimension,
  DimensionInput,
  LinkInput,
  Metric,
  MetricInput,
  SemanticUsage,
  ReportDefinition,
  ReportField,
} from '../types/semantic'
import { TOKEN_KEY } from '../types/user'

const BASE = import.meta.env.VITE_API_BASE ?? '/api'

let onUnauthorized: (() => void) | null = null

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, { ...options, headers })
  // 401 на самом входе — это неверный логин или пароль, а не протухшая
  // сессия: чистить токен и уводить на страницу входа тут нечего, а текст
  // нужен серверный, иначе человек с опечаткой видит «требуется авторизация»
  // и не понимает, что именно не так. Такой ответ разбирает ветка ниже.
  if (res.status === 401 && path !== '/auth/login') {
    setToken(null)
    onUnauthorized?.()
    throw new ApiError(401, 'требуется авторизация')
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (body?.detail) detail = describeDetail(body.detail)
    } catch {
      // тело не JSON
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

/** Ошибка от сервера в читаемый вид.

    FastAPI при несовпадении схемы отвечает списком объектов; напечатанный
    как есть, он превращается в «[object Object]» и не говорит ничего. */
function describeDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (typeof item === 'string') return item
      const row = item as { loc?: unknown[]; msg?: string }
      const where = Array.isArray(row.loc)
        ? row.loc.filter((x) => typeof x === 'string' && x !== 'body').join('.')
        : ''
      return where ? `${where}: ${row.msg ?? 'некорректное значение'}` : (row.msg ?? '')
    })
    const text = parts.filter(Boolean).join('; ')
    if (text) return text
  }
  try {
    return JSON.stringify(detail)
  } catch {
    return 'сервер вернул ошибку без описания'
  }
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// --- auth ---

export async function login(username: string, password: string): Promise<User> {
  const json = await request<{ token: string; user: User }>('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  setToken(json.token)
  return json.user
}

export async function logout(): Promise<void> {
  try {
    await request('/auth/logout', { method: 'POST' })
  } catch {
    // даже при ошибке чистим токен локально
  }
  setToken(null)
}

export async function fetchMe(): Promise<User | null> {
  if (!getToken()) return null
  try {
    const json = await request<{ user: User }>('/auth/me')
    return json.user
  } catch {
    return null
  }
}

export async function changePassword(password: string): Promise<void> {
  await request('/auth/password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })
}

// --- отчёты ---

export async function fetchReports(): Promise<ReportMeta[]> {
  const json = await request<{ reports: ReportMeta[] }>('/reports')
  return json.reports
}

/** Параметры каталога в строку запроса: пустые и выключенные не идут. */
function catalogParams(query: ReportQuery): string {
  const params = new URLSearchParams()
  if (query.q?.trim()) params.set('q', query.q.trim())
  for (const key of ['group', 'author', 'tag', 'status'] as const) {
    const value = query[key]
    if (value) params.set(key, value)
  }
  if (query.favorite) params.set('favorite', 'true')
  if (query.sort) params.set('sort', query.sort)
  if (query.limit !== undefined) params.set('limit', String(query.limit))
  if (query.offset) params.set('offset', String(query.offset))
  const text = params.toString()
  return text ? `?${text}` : ''
}

/** Страница каталога: поиск и фильтры считает сервер, клиент их не повторяет. */
export async function searchReports(
  query: ReportQuery,
  signal?: AbortSignal,
): Promise<ReportPage> {
  const json = await request<{ reports: ReportMeta[]; total: number }>(
    `/reports${catalogParams(query)}`,
    { signal },
  )
  return { reports: json.reports, total: json.total ?? json.reports.length }
}

export async function fetchReportFacets(q?: string, signal?: AbortSignal): Promise<ReportFacets> {
  const suffix = q?.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''
  return request<ReportFacets>(`/reports/facets${suffix}`, { signal })
}

/** Закрепление отчёта — личное: чужое не видно и не мешает. */
export async function setReportFavorite(slug: string, on: boolean): Promise<void> {
  await request(`/reports/${encodeURIComponent(slug)}/favorite`, {
    method: on ? 'PUT' : 'DELETE',
  })
}

export async function fetchReport(slug: string): Promise<Report | null> {
  try {
    const json = await request<{ report: Report }>(`/reports/${slug}`)
    return json.report.sections ? json.report : null
  } catch (err) {
    if (err instanceof ApiError) throw err
    return null
  }
}

export async function applyFilters(
  slug: string,
  values: Record<string, string>,
): Promise<Report | null> {
  try {
    const json = await request<{ report: Report }>(`/reports/${slug}/filters`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values }),
    })
    return json.report
  } catch {
    return null
  }
}

export async function updateReport(
  slug: string,
  patch: { title?: string; description?: string; tags?: string[] },
): Promise<ReportMeta> {
  const json = await request<{ report: ReportMeta }>(`/reports/${slug}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  return json.report
}

export async function deleteReport(slug: string): Promise<void> {
  await request(`/reports/${slug}`, { method: 'DELETE' })
}

// --- admin ---

export async function adminListUsers(): Promise<User[]> {
  const json = await request<{ users: User[] }>('/admin/users')
  return json.users
}

export async function adminCreateUser(
  username: string,
  password: string,
  role: 'admin' | 'user',
): Promise<User> {
  const json = await request<{ user: User }>('/admin/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, role }),
  })
  return json.user
}

export async function adminDeleteUser(userId: string): Promise<void> {
  await request(`/admin/users/${userId}`, { method: 'DELETE' })
}

export async function adminResetPassword(
  userId: string,
  password: string,
): Promise<void> {
  await request(`/admin/users/${userId}/password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })
}

export async function adminListGroups(): Promise<Group[]> {
  const json = await request<{ groups: Group[] }>('/admin/groups')
  return json.groups
}

export async function adminCreateGroup(name: string): Promise<void> {
  await request('/admin/groups', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export async function adminDeleteGroup(groupId: string): Promise<void> {
  await request(`/admin/groups/${groupId}`, { method: 'DELETE' })
}

export async function adminAddMember(groupId: string, userId: string): Promise<void> {
  await request(`/admin/groups/${groupId}/members`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ userId }),
  })
}

export async function adminRemoveMember(
  groupId: string,
  userId: string,
): Promise<void> {
  await request(`/admin/groups/${groupId}/members/${userId}`, { method: 'DELETE' })
}

export async function adminListAccess(slug: string): Promise<AccessEntry[]> {
  const json = await request<{ access: AccessEntry[] }>(`/admin/access/${slug}`)
  return json.access
}

export async function adminGrantAccess(
  slug: string,
  userId: string | null,
  groupId: string | null,
): Promise<void> {
  await request('/admin/access', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reportSlug: slug, userId, groupId }),
  })
}

export async function adminRevokeAccess(
  slug: string,
  userId: string | null,
  groupId: string | null,
): Promise<void> {
  await request('/admin/access', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reportSlug: slug, userId, groupId }),
  })
}

// --- датасеты ---

export async function fetchDatasets(): Promise<Dataset[]> {
  const json = await request<{ datasets: Dataset[] }>('/datasets')
  return json.datasets
}

export async function fetchDataset(slug: string): Promise<DatasetDetail> {
  return await request<DatasetDetail>(`/datasets/${slug}`)
}

export async function createDataset(input: DatasetCreateInput): Promise<DatasetSaveResult> {
  return await request<DatasetSaveResult>('/datasets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export async function patchDataset(slug: string, patch: DatasetPatchInput): Promise<DatasetSaveResult> {
  return await request<DatasetSaveResult>(`/datasets/${slug}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

export async function refreshDataset(slug: string): Promise<DatasetSaveResult> {
  return await request<DatasetSaveResult>(`/datasets/${slug}/refresh`, {
    method: 'POST',
  })
}

export async function fetchDatasetSuggestions(slug: string): Promise<DatasetSuggestions> {
  const json = await request<{ suggestions: DatasetSuggestions }>(`/datasets/${slug}/suggest`)
  return json.suggestions
}

export async function createDatasetSemantic(
  slug: string,
  selection: DatasetSemanticInput,
): Promise<DatasetSemanticResult> {
  return await request<DatasetSemanticResult>(`/datasets/${slug}/semantic`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(selection),
  })
}

export async function deleteDataset(slug: string): Promise<void> {
  await request(`/datasets/${slug}`, { method: 'DELETE' })
}

export async function uploadDatasetCsv(slug: string, file: File): Promise<{ dataset: Dataset; rows: number }> {
  const form = new FormData()
  form.append('file', file)
  const json = await request<{ dataset: Dataset; rows: number }>(`/datasets/${slug}/upload`, {
    method: 'POST',
    body: form,
  })
  return json
}

// --- рассылка отчётов ---

export async function fetchMailServers(): Promise<{ servers: MailServer[]; presets: Record<string, { host: string; port: number; security: string }> }> {
  return await request('/admin/mail-servers')
}

export async function createMailServer(input: MailServerInput): Promise<MailServer> {
  const json = await request<{ server: MailServer }>('/admin/mail-servers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  return json.server
}

export async function patchMailServer(id: string, patch: Partial<MailServerInput>): Promise<MailServer> {
  const json = await request<{ server: MailServer }>(`/admin/mail-servers/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  return json.server
}

export async function testMailServer(id: string, to: string): Promise<MailServer> {
  const json = await request<{ server: MailServer }>(`/admin/mail-servers/${id}/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ to }),
  })
  return json.server
}

export async function deleteMailServer(id: string): Promise<void> {
  await request(`/admin/mail-servers/${id}`, { method: 'DELETE' })
}

export async function fetchSchedules(
  slug: string,
): Promise<{ schedules: ReportSchedule[]; servers: ScheduleServer[] }> {
  return await request(`/reports/${slug}/schedules`)
}

/** Свод рассылок: свои по всем отчётам сразу — или все, если спросил админ.

    Обойти отчёты по одному кабинет мог бы и сам, но это запрос на отчёт ради
    обычно двух-трёх рассылок. */
export async function fetchScheduleDigest(
  scope: 'mine' | 'all' = 'mine',
): Promise<{ schedules: ScheduleDigestItem[]; servers: ScheduleServer[] }> {
  return await request(`/schedules?scope=${scope}`)
}

export async function createSchedule(slug: string, input: ScheduleInput): Promise<ReportSchedule> {
  const json = await request<{ schedule: ReportSchedule }>(`/reports/${slug}/schedules`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  return json.schedule
}

export async function patchSchedule(
  slug: string,
  id: string,
  patch: Partial<ScheduleInput>,
): Promise<ReportSchedule> {
  const json = await request<{ schedule: ReportSchedule }>(`/reports/${slug}/schedules/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  return json.schedule
}

export async function sendScheduleNow(slug: string, id: string): Promise<ReportSchedule> {
  const json = await request<{ schedule: ReportSchedule }>(`/reports/${slug}/schedules/${id}/send`, {
    method: 'POST',
  })
  return json.schedule
}

export async function deleteSchedule(slug: string, id: string): Promise<void> {
  await request(`/reports/${slug}/schedules/${id}`, { method: 'DELETE' })
}

// --- детализация отчёта ---

export interface DrillPoint {
  sectionIndex?: number
  datasetSlug?: string
  point?: Record<string, string | number | null>
}

export interface DrillPage {
  dataset: string
  title: string
  datasets: { slug: string; title: string }[]
  columns: string[]
  rows: Record<string, unknown>[]
  offset: number
  hasMore: boolean
}

export async function fetchDrilldown(
  slug: string,
  body: DrillPoint & { limit?: number; offset?: number },
): Promise<DrillPage> {
  return await request<DrillPage>(`/reports/${slug}/drilldown`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

/** Выгрузка детализации в Excel: файл приходит потоком, поэтому мимо request(). */
export async function exportDrilldown(slug: string, body: DrillPoint): Promise<Blob> {
  const res = await fetch(`${BASE}/reports/${slug}/drilldown.xlsx`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
    },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail
    } catch {
      // тело не json — оставляем код ответа
    }
    throw new ApiError(res.status, detail)
  }
  return await res.blob()
}

// --- семантический слой и конструктор отчётов ---

export async function fetchMetrics(): Promise<Metric[]> {
  const json = await request<{ metrics: Metric[] }>('/metrics')
  return json.metrics
}

export async function fetchDimensions(): Promise<Dimension[]> {
  const json = await request<{ dimensions: Dimension[] }>('/dimensions')
  return json.dimensions
}

export async function createMetric(input: MetricInput): Promise<Metric> {
  const json = await request<{ metric: Metric }>('/metrics', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  return json.metric
}

export async function patchMetric(slug: string, patch: Partial<MetricInput>): Promise<Metric> {
  const json = await request<{ metric: Metric }>(`/metrics/${slug}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  return json.metric
}

/** Прогоняет выражение по источнику: битая метрика не должна дожить до отчёта. */
export async function testMetric(slug: string): Promise<Metric> {
  const json = await request<{ metric: Metric }>(`/metrics/${slug}/test`, { method: 'POST' })
  return json.metric
}

/** Проверка пачки выражений: пустой список — весь словарь.

    По одной метрике за запрос нельзя: подключение к источнику стоит дороже
    самой проверки, а сервер открывает одно соединение на датасет. */
export async function testMetrics(slugs: string[] = []): Promise<Metric[]> {
  const json = await request<{ metrics: Metric[] }>('/metrics/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slugs }),
  })
  return json.metrics
}

export async function deleteMetric(slug: string): Promise<void> {
  await request(`/metrics/${slug}`, { method: 'DELETE' })
}

export async function createDimension(input: DimensionInput): Promise<Dimension> {
  const json = await request<{ dimension: Dimension }>('/dimensions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  return json.dimension
}

export async function patchDimension(slug: string, patch: Partial<DimensionInput>): Promise<Dimension> {
  const json = await request<{ dimension: Dimension }>(`/dimensions/${slug}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  return json.dimension
}

export async function deleteDimension(slug: string): Promise<void> {
  await request(`/dimensions/${slug}`, { method: 'DELETE' })
}

/** Связи датасетов: по ним конструктор строит JOIN между показателями. */
export async function fetchLinks(): Promise<DatasetLink[]> {
  const json = await request<{ links: DatasetLink[] }>('/dataset-links')
  return json.links
}

export async function createLink(input: LinkInput): Promise<DatasetLink> {
  const json = await request<{ link: DatasetLink }>('/dataset-links', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  return json.link
}

/** Где используется словарь: показатель или разрез → отчёты, ссылающиеся на него. */
export async function fetchSemanticUsage(): Promise<SemanticUsage> {
  const json = await request<{ usage: SemanticUsage }>('/semantic/usage')
  return json.usage
}

export async function deleteLink(id: string): Promise<void> {
  await request(`/dataset-links/${id}`, { method: 'DELETE' })
}

/** Выполняет определение, ничего не сохраняя — предпросмотр конструктора.
 *  Значения фильтров идут рядом с определением и в него не попадают. */
export async function previewDefinition(
  definition: ReportDefinition,
  filterValues: Record<string, string> = {},
): Promise<Report> {
  const json = await request<{ report: Report }>('/reports/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...definition, filterValues }),
  })
  return json.report
}

export async function createBuilderReport(payload: {
  title: string
  slug?: string
  description?: string
  definition: ReportDefinition
}): Promise<ReportMeta> {
  const json = await request<{ report: ReportMeta }>('/reports/builder', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return json.report
}

export interface DefinitionResponse {
  definition: ReportDefinition
  title?: string
  description?: string
}

export async function fetchDefinition(slug: string): Promise<DefinitionResponse> {
  return await request<DefinitionResponse>(`/reports/${slug}/definition`)
}

export async function saveDefinition(slug: string, definition: ReportDefinition): Promise<ReportMeta> {
  const json = await request<{ report: ReportMeta }>(`/reports/${slug}/definition`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(definition),
  })
  return json.report
}

/** Разбор словесного ТЗ в декларацию (детерминированный, по словарю метрик). */
export interface ParseNote {
  text: string
  problem?: string | null
  matchedMetrics?: string[]
  matchedDimensions?: string[]
  unmatched?: string[]
  /** 'модель' или разбор по словарю — читателю полезно знать, чем понято. */
  source?: string
}

export interface ParseResult {
  definition: ReportDefinition
  notes: ParseNote[]
  source?: 'llm' | 'parser'
  /** Почему разбирала не модель, а словарь: без этого разница в качестве
      разбора выглядит для человека необъяснимой. */
  fallbackReason?: string
}

/** Реплика переписки о будущем отчёте. Историю держит клиент: сервер
 *  диалоговых сессий не заводит, вся переписка уходит с каждым обращением. */
export interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
}

export interface ChatAnswer {
  /** Ответ собеседника по-русски — его и показываем в переписке. */
  reply: string
  /** Раскладка целиком; `null`, когда собеседник переспрашивает. */
  definition: ReportDefinition | null
  /** Название, предложенное моделью, — подставляется в пустое поле. */
  title?: string | null
  notes: ParseNote[]
  source?: 'llm' | 'parser'
  /** Какая модель ответила: у диалога и разбора они разные. */
  model?: string
}

/** Ход диалога об отчёте. Текущее определение уходит вместе с перепиской:
 *  «добавь фильтр по городу» — это правка раскладки, а не новый отчёт. */
export async function chatReport(
  messages: ChatMessage[],
  context: {
    fields?: ReportField[]
    computed?: ComputedField[]
    datasets?: string[]
    definition?: ReportDefinition | null
  } = {},
): Promise<ChatAnswer> {
  return request<ChatAnswer>('/reports/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages,
      fields: context.fields ?? [],
      computed: context.computed ?? [],
      datasets: context.datasets ?? [],
      definition: context.definition ?? null,
    }),
  })
}

/** Разбор описания. Поля и формулы отчёта передаются вместе с текстом:
 *  в общем словаре их нет, но для этого отчёта это полноценные показатели. */
export async function parsePhrase(
  text: string,
  own: { fields?: ReportField[]; computed?: ComputedField[]; datasets?: string[] } = {},
): Promise<ParseResult> {
  return request<ParseResult>('/reports/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // датасеты, выбранные на шаге «Данные»: без них словарь для модели — все
    // показатели установки, среди которых «Выручка» встречается десяток раз
    body: JSON.stringify({
      text,
      fields: own.fields ?? [],
      computed: own.computed ?? [],
      datasets: own.datasets ?? [],
    }),
  })
}
