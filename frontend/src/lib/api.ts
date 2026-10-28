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
  DatasetFieldSetting,
  DatasetPatchInput,
  DatasetSaveResult,
  DatasetSemanticInput,
  DatasetSemanticResult,
  DatasetSuggestions,
  DbConnection,
  DatasetQuestionTurn,
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

/** Send an authenticated API request and accept an empty 204 response. */
async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, { ...options, headers })
  } catch {
    const resource = path.includes('history') || path.includes('conversation') ? 'историю диалога' : 'данные'
    throw new ApiError(0, `Не удалось загрузить ${resource}: нет соединения с сервером. Проверьте интернет и доступность сайта, затем повторите действие.`, 'connection_failed')
  }
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
    const messages: Record<number, string> = {
      502: 'Сервер приложения недоступен, возможно, он обновляется. Подождите минуту и повторите действие.',
      503: 'Сервер временно недоступен или перегружен. Подождите минуту и повторите действие.',
      504: 'Не удалось дождаться ответа сервера. Попробуйте проверить историю диалога позже.',
    }
    let detail = messages[res.status] || `Сервер отклонил запрос (код ${res.status}). Повторите действие; если ошибка повторится, сообщите администратору.`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (body?.detail) detail = describeDetail(body.detail)
    } catch {
      // тело не JSON
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  try {
    return (await res.json()) as T
  } catch {
    throw new ApiError(0, 'Получение данных с сервера прервалось или ответ повреждён. Проверьте соединение и повторите действие.', 'connection_failed')
  }
}

/** Explain a transport failure without exposing the browser's raw exception. */
function streamFailure(code: 'connection_failed' | 'stream_interrupted' | 'incomplete_stream' | 'invalid_stream', lastStatus = ''): ApiError {
  const messages = {
    connection_failed: 'Не удалось отправить запрос: подтверждение от сервера не получено. Проверьте интернет и доступность сайта.',
    stream_interrupted: 'Соединение с сервером оборвалось во время получения ответа. Возможна перезагрузка сервера или сбой сети.',
    incomplete_stream: 'Сервер завершил передачу без итогового ответа.',
    invalid_stream: 'Сервер прислал ответ в неподходящем формате; показать результат не удалось.',
  }
  const stage = lastStatus ? ` Последний этап: ${lastStatus}` : ''
  return new ApiError(0, `${messages[code]}${stage} Нажмите «Проверить историю»: запрос мог дойти до сервера, а готовый результат — сохраниться.`, code)
}

/** Decode one event; distinguish corrupt transport data from application errors. */
function parseStreamEvent<T extends { type: string }>(line: string): T {
  try {
    const value = JSON.parse(line)
    if (!value || !['status', 'delta', 'done', 'error', 'heartbeat'].includes(value.type)) throw new Error()
    if (value.type === 'done' && (!value.result || typeof value.result !== 'object')) throw new Error()
    return value as T
  } catch {
    throw streamFailure('invalid_stream')
  }
}

/** Send a chat request, preserving server errors and explaining transport failures. */
async function streamEvents<T extends { type: string; text?: string }>(
  path: string,
  payload: unknown,
  onEvent: (event: T) => void,
): Promise<void> {
  const token = getToken()
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
    })
  } catch {
    throw streamFailure('connection_failed')
  }
  if (response.status === 401) {
    setToken(null)
    onUnauthorized?.()
    throw new ApiError(401, 'Сессия закончилась. Войдите снова, затем откройте сохранённый диалог.')
  }
  if (!response.ok) {
    const proxyMessages: Record<number, string> = {
      502: 'Сервер приложения сейчас недоступен, возможно, он обновляется. Подождите минуту и проверьте историю диалога.',
      503: 'Сервер временно недоступен или перегружен. Подождите минуту и проверьте историю диалога.',
      504: 'Промежуточный сервер не дождался ответа приложения. Расчёт мог продолжиться. Нажмите «Проверить историю» перед повторной отправкой.',
    }
    if (proxyMessages[response.status]) throw new ApiError(response.status, proxyMessages[response.status], 'server_unavailable')
    let detail = `Сервер отклонил запрос (код ${response.status}). Повторите действие; если ошибка повторится, сообщите администратору.`
    try {
      const body = await response.json() as { detail?: unknown }
      if (body.detail) detail = describeDetail(body.detail)
    } catch { /* The proxy may return an HTML error page. */ }
    throw new ApiError(response.status, detail)
  }
  if (!response.body) throw streamFailure('incomplete_stream')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let pending = ''
  let lastStatus = ''
  let terminal = false
  try {
    while (!terminal) {
      let chunk: ReadableStreamReadResult<Uint8Array>
      try {
        chunk = await reader.read()
      } catch {
        throw streamFailure('stream_interrupted', lastStatus)
      }
      pending += decoder.decode(chunk.value, { stream: !chunk.done })
      const lines = pending.split('\n')
      pending = lines.pop() ?? ''
      if (chunk.done && pending.trim()) { lines.push(pending); pending = '' }
      for (const line of lines) {
        if (!line.trim()) continue
        const event = parseStreamEvent<T>(line)
        if (event.type === 'status' && event.text) lastStatus = event.text
        terminal = event.type === 'done' || event.type === 'error'
        onEvent(event)
        if (terminal) break
      }
      if (chunk.done) break
    }
    if (!terminal) throw streamFailure('incomplete_stream', lastStatus)
  } finally {
    try { await reader.cancel() } catch { /* A broken connection is already explained. */ }
    reader.releaseLock()
  }
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
  code?: string

  /** Store an HTTP or transport failure for actionable recovery in the UI. */
  constructor(status: number, message: string, code?: string) {
    super(message)
    this.status = status
    this.code = code
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

export async function adminGetAccessTags(kind: 'user' | 'group', id: string): Promise<string[]> {
  const json = await request<{ tags: string[] }>(`/admin/access-tags/${kind}/${encodeURIComponent(id)}`)
  return json.tags
}

export async function adminSetAccessTags(kind: 'user' | 'group', id: string, tags: string[]): Promise<string[]> {
  const json = await request<{ tags: string[] }>(`/admin/access-tags/${kind}/${encodeURIComponent(id)}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tags }),
  })
  return json.tags
}

export async function adminEffectiveAccess(slug: string): Promise<{ userId: string; username: string; reasons: string[] }[]> {
  const json = await request<{ users: { userId: string; username: string; reasons: string[] }[] }>(`/admin/access/${slug}/effective`)
  return json.users
}

export async function adminUserAccessibleReports(id: string): Promise<{ slug: string; title: string; reasons: string[] }[]> {
  const json = await request<{ reports: { slug: string; title: string; reasons: string[] }[] }>(`/admin/users/${id}/accessible-reports`)
  return json.reports
}

// --- отчёты ---

export async function fetchReports(): Promise<ReportMeta[]> {
  const json = await request<{ reports: ReportMeta[] }>('/reports')
  return json.reports
}

/** Serialize every catalog filter so archived and active pages use distinct requests. */
function catalogParams(query: ReportQuery): string {
  const params = new URLSearchParams()
  if (query.q?.trim()) params.set('q', query.q.trim())
  for (const slug of query.slugs ?? []) params.append('slug', slug)
  for (const key of ['group', 'author', 'tag', 'status'] as const) {
    const value = query[key]
    if (value) params.set(key, value)
  }
  if (query.favorite) params.set('favorite', 'true')
  if (query.archived) params.set('archived', 'true')
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

/** Fetch facets for the same active or archived catalog as the visible rows. */
export async function fetchReportFacets(q?: string, signal?: AbortSignal, archived = false): Promise<ReportFacets> {
  const params = new URLSearchParams()
  if (q?.trim()) params.set('q', q.trim())
  if (archived) params.set('archived', 'true')
  return request<ReportFacets>(`/reports/facets?${params}`, { signal })
}

/** Restore an archived report after the server validates its sources and queries. */
export async function restoreReport(slug: string): Promise<void> {
  await request(`/reports/${slug}/restore`, { method: 'POST' })
}

export interface DatasetDeletionImpact {
  total: number
  reports: { slug: string; title: string }[]
}

/** Read the affected report count and a bounded list of names before deletion. */
export async function fetchDatasetDeletionImpact(slug: string, signal?: AbortSignal): Promise<DatasetDeletionImpact> {
  return request(`/datasets/${slug}/deletion-impact`, { signal })
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

export async function fetchDbConnections(): Promise<DbConnection[]> {
  const json = await request<{ connections: DbConnection[] }>('/datasets/connections')
  return json.connections
}

export async function testDbConnection(key: string): Promise<void> {
  await request(`/datasets/connections/${encodeURIComponent(key)}/test`, { method: 'POST' })
}

export interface DatasetStreamEvent {
  code?: string
  type: 'status' | 'delta' | 'done' | 'error' | 'heartbeat'
  text?: string
  message?: string
  conversationId?: string
  result?: DatasetQuestionTurn
}

/** Read a saved dataset conversation after reopening or switching datasets. */
export async function fetchDatasetConversation(slug: string): Promise<{
  conversationId: string | null
  turns: DatasetQuestionTurn[]
}> {
  return request(`/datasets/${encodeURIComponent(slug)}/conversation`)
}

/** Restore the shared question chat across attached datasets. */
export async function fetchWorkspaceConversation(conversationId?: string): Promise<{
  conversationId: string | null
  turns: DatasetQuestionTurn[]
}> {
  return request(`/datasets/chat/history${conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ''}`)
}

export interface SavedChat {
  id: string
  kind: 'dataset' | 'report'
  target: string
  title: string
  savedAt: string
  updatedAt: string
}

/** List explicitly named chats belonging to one agent and report scope. */
export async function fetchSavedChats(kind: SavedChat['kind'], target: string): Promise<SavedChat[]> {
  const result = await request<{ chats: SavedChat[] }>(
    `/chats?kind=${encodeURIComponent(kind)}&target=${encodeURIComponent(target)}`)
  return result.chats
}

/** Save or rename an owned chat, creating an empty chat when no id exists. */
export async function saveNamedChat(kind: SavedChat['kind'], target: string,
                                    title: string, conversationId: string | null): Promise<SavedChat> {
  const result = await request<{ chat: SavedChat }>('/chats', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, target, title, conversationId }),
  })
  return result.chat
}

/** Remove one owned chat and its history from the selected agent scope. */
export async function deleteSavedChat(id: string, kind: SavedChat['kind'],
                                      target: string): Promise<void> {
  await request<void>(`/chats/${encodeURIComponent(id)}?kind=${encodeURIComponent(kind)}&target=${encodeURIComponent(target)}`,
    { method: 'DELETE' })
}

/** Create an empty independent chat so a reload cannot revive the previous one. */
export async function createAgentChat(kind: SavedChat['kind'], target: string): Promise<string> {
  const result = await request<{ conversationId: string }>('/chats/new', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, target }),
  })
  return result.conversationId
}

/** Read newline-delimited agent events as soon as the server sends them. */
export async function streamDatasetAnswer(
  slug: string,
  question: string,
  conversationId: string | null,
  onEvent: (event: DatasetStreamEvent) => void,
): Promise<void> {
  return streamDatasetEvents(`/datasets/${encodeURIComponent(slug)}/ask/stream`,
    { question, conversationId }, onEvent)
}

/** Stream a turn in the full-screen chat using every attached dataset. */
export async function streamWorkspaceAnswer(
  datasetSlugs: string[],
  question: string,
  conversationId: string | null,
  onEvent: (event: DatasetStreamEvent) => void,
): Promise<void> {
  return streamDatasetEvents('/datasets/chat/stream',
    { datasetSlugs, question, conversationId }, onEvent)
}

/** Use the shared decoder for question chat and report chat alike. */
async function streamDatasetEvents(
  path: string,
  body: Record<string, unknown>,
  onEvent: (event: DatasetStreamEvent) => void,
): Promise<void> {
  return streamEvents(path, body, onEvent)
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

/** Сохраняет ручные настройки текущих колонок подготовленного датасета. */
export async function putDatasetFields(
  slug: string,
  fields: Record<string, DatasetFieldSetting>,
): Promise<{ dataset: Dataset }> {
  return await request<{ dataset: Dataset }>(`/datasets/${encodeURIComponent(slug)}/fields`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fields }),
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
  metricKey?: string
}

export interface DrillPage {
  dataset: string
  title: string
  datasets: { slug: string; title: string }[]
  columns: string[]
  rows: Record<string, unknown>[]
  offset: number
  hasMore: boolean
  scopeNote?: string | null
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
  conversationId?: string | null
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

/** Реплика переписки о будущем отчёте, сохранённая в метабазе. */
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
  source?: 'llm' | 'parser' | 'agent'
  /** Какая модель ответила: у диалога и разбора они разные. */
  model?: string
  conversationId?: string
}

/** Restore the authenticated user's saved report conversation. */
export async function fetchReportChatHistory(target: string, conversationId?: string): Promise<{
  conversationId: string | null
  messages: ChatMessage[]
  proposal?: { definition: ReportDefinition; title?: string | null } | null
}> {
  return request(`/reports/chat/history?target=${encodeURIComponent(target)}${conversationId
    ? `&conversation_id=${encodeURIComponent(conversationId)}` : ''}`)
}

/** Ход диалога об отчёте. Текущее определение уходит вместе с перепиской:
 *  «добавь фильтр по городу» — это правка раскладки, а не новый отчёт. */
export async function chatReport(
  messages: ChatMessage[],
  context: {
    fields?: ReportField[]
    computed?: ComputedField[]
    datasets?: string[]
    attachedDatasets?: string[]
    definition?: ReportDefinition | null
    conversationId?: string | null
    target?: string
    newConversation?: boolean
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
      attachedDatasets: context.attachedDatasets ?? [],
      definition: context.definition ?? null,
      conversationId: context.conversationId ?? null,
      target: context.target ?? 'new',
      newConversation: context.newConversation ?? false,
    }),
  })
}

export interface ReportStreamEvent {
  type: 'status' | 'delta' | 'done' | 'error' | 'heartbeat'
  text?: string
  message?: string
  conversationId?: string
  result?: ChatAnswer
}

/** Stream visual report construction and its verified proposal. */
export async function streamReportChat(
  messages: ChatMessage[],
  context: {
    fields?: ReportField[]
    computed?: ComputedField[]
    datasets?: string[]
    attachedDatasets?: string[]
    definition?: ReportDefinition | null
    conversationId?: string | null
    target?: string
    newConversation?: boolean
  },
  onEvent: (event: ReportStreamEvent) => void,
): Promise<void> {
  return streamEvents('/reports/chat/stream', { messages, ...context }, onEvent)
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

export interface DatasetAccess {
  userIds: string[]
  groupIds: string[]
}

/** Read explicit personal and group grants for the dataset administration dialog. */
export async function adminDatasetAccess(slug: string, signal?: AbortSignal): Promise<DatasetAccess> {
  return request(`/admin/datasets/${encodeURIComponent(slug)}/access`, { signal })
}

/** Replace grants atomically; empty arrays leave access to administrators only. */
export async function adminSetDatasetAccess(slug: string, grants: DatasetAccess): Promise<DatasetAccess> {
  return request(`/admin/datasets/${encodeURIComponent(slug)}/access`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(grants),
  })
}

export interface TagCatalogItem {
  tag: string
  reportCount: number
  userCount: number
  groupCount: number
}

export interface TagUsage {
  reports: { slug: string; title: string; archivedAt: string | null }[]
  users: { id: string; username: string }[]
  groups: { id: string; name: string }[]
}

export interface AccessTagDetails {
  tags: string[]
  inheritedTags: string[]
  effectiveTags: string[]
  inheritedFrom: { groupId: string; groupName: string; tags: string[] }[]
}

/** List tags known to the caller without revealing inaccessible report labels. */
export async function fetchAvailableReportTags(signal?: AbortSignal): Promise<string[]> {
  const result = await request<{ tags: string[] }>('/report-tags', { signal })
  return result.tags
}

/** Summarize all report, personal and group tag assignments for administrators. */
export async function adminTagCatalog(signal?: AbortSignal): Promise<TagCatalogItem[]> {
  const result = await request<{ tags: TagCatalogItem[] }>('/admin/tags', { signal })
  return result.tags
}

/** Show bounded examples of where a selected tag is used. */
export async function adminTagUsage(tag: string, signal?: AbortSignal): Promise<TagUsage> {
  return request(`/admin/tags/usage?${new URLSearchParams({ tag })}`, { signal })
}

/** Separate direct permissions from those inherited through groups. */
export async function adminAccessTagDetails(kind: 'user' | 'group', id: string, signal?: AbortSignal): Promise<AccessTagDetails> {
  return request(`/admin/access-tags/${kind}/${encodeURIComponent(id)}?effective=true`, { signal })
}
