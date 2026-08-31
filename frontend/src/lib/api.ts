import type { Report, ReportMeta } from '../types/report'
import type { AccessEntry, Group, User } from '../types/user'
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
  if (res.status === 401) {
    setToken(null)
    onUnauthorized?.()
    throw new ApiError(401, 'требуется авторизация')
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = (await res.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch {
      // тело не JSON
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
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

export async function fetchSkills(): Promise<string[]> {
  const json = await request<{ skills: { name: string }[] }>('/skills')
  return json.skills.map((s) => s.name)
}

export async function createReport(
  skill: string,
  title: string,
  mode: 'demo' | 'llm' | 'auto' = 'demo',
): Promise<void> {
  await request('/reports', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ skill, title, mode }),
  })
}