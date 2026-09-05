import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { ReportMeta } from '../types/report'
import type { AccessEntry, Group, User } from '../types/user'
import {
  adminListAccess,
  adminListGroups,
  adminListUsers,
  fetchReports,
} from '../lib/api'
import { useAuth } from '../lib/auth'
import { AccessPanel } from '../components/admin/AccessPanel'
import { GroupsPanel } from '../components/admin/GroupsPanel'
import { MailServersPanel } from '../components/admin/MailServersPanel'
import { UsersPanel } from '../components/admin/UsersPanel'
import { Segmented } from '../components/admin/Segmented'
import {
  Alert,
  Button,
  EmptyState,
  Page,
  PageHeader,
  SkeletonRows,
} from '../components/ui'

type Tab = 'users' | 'groups' | 'access' | 'mail'

const TABS: Tab[] = ['users', 'groups', 'access', 'mail']

/**
 * Администрирование одной страницей с вкладками: все четыре блока сразу
 * давали простыню, в которой назначение отчёта — самое частое действие —
 * оказывалось ниже двух форм.
 *
 * Вкладка живёт в адресе (`/admin?tab=access`): ссылку можно дать коллеге,
 * и возврат «назад» из отчёта не сбрасывает раздел.
 */
export function AdminPage() {
  const { isAdmin } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab = (TABS as string[]).includes(params.get('tab') ?? '') ? (params.get('tab') as Tab) : 'users'

  const [users, setUsers] = useState<User[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [reports, setReports] = useState<ReportMeta[]>([])
  const [access, setAccess] = useState<Record<string, AccessEntry[]>>({})
  // назначения приезжают отдельно и позже — их столько запросов, сколько
  // отчётов, и ждать их, чтобы показать список пользователей, незачем
  const [accessReady, setAccessReady] = useState(false)
  const [mailCount, setMailCount] = useState<number | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  /** Назначения читаются по одному отчёту — эндпоинт другого не умеет.
      Запросов столько же, сколько отчётов, зато обе панели («по отчётам» и
      «по людям») и счётчики в списках работают с полной картиной. */
  const loadAccess = useCallback(async (list: ReportMeta[]) => {
    const pairs = await Promise.all(
      list.map(async (r) => [r.slug, await adminListAccess(r.slug)] as const),
    )
    return Object.fromEntries(pairs)
  }, [])

  const reload = useCallback(async () => {
    setAccessReady(false)
    try {
      const [u, g, r] = await Promise.all([adminListUsers(), adminListGroups(), fetchReports()])
      setUsers(u)
      setGroups(g)
      setReports(r)
      setError(null)
      setLoading(false)
      setAccess(await loadAccess(r))
      setAccessReady(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ошибка загрузки')
      setLoading(false)
    }
  }, [loadAccess])

  useEffect(() => {
    if (isAdmin) void reload()
  }, [isAdmin, reload])

  /** Отчёты, доступные пользователю: назначенные ему и его группам. */
  const userReports = useMemo(() => {
    const groupsOfUser: Record<string, string[]> = {}
    for (const g of groups) {
      for (const m of g.members) (groupsOfUser[m.id] ??= []).push(g.id)
    }
    const map: Record<string, Set<string>> = {}
    for (const [slug, entries] of Object.entries(access)) {
      for (const entry of entries) {
        if (entry.userId) (map[entry.userId] ??= new Set()).add(slug)
        if (!entry.groupId) continue
        for (const u of users) {
          if ((groupsOfUser[u.id] ?? []).includes(entry.groupId)) (map[u.id] ??= new Set()).add(slug)
        }
      }
    }
    return Object.fromEntries(Object.entries(map).map(([id, slugs]) => [id, [...slugs]]))
  }, [access, groups, users])

  const groupReports = useMemo(() => {
    const map: Record<string, string[]> = {}
    for (const [slug, entries] of Object.entries(access)) {
      for (const entry of entries) if (entry.groupId) (map[entry.groupId] ??= []).push(slug)
    }
    return map
  }, [access])

  if (!isAdmin) {
    return (
      <Page>
        <EmptyState title="Раздел доступен только администраторам" />
      </Page>
    )
  }

  const fail = (err: unknown) => setError(err instanceof Error ? err.message : 'ошибка')
  const grants = Object.values(access).reduce((n, entries) => n + entries.length, 0)

  return (
    <Page>
      <PageHeader
        title="Администрирование"
        subtitle="Кто заходит в систему, кто что видит и из какого ящика уходят рассылки."
        actions={
          <Button onClick={() => void reload()} disabled={loading}>
            Обновить
          </Button>
        }
      >
        <Segmented
          className="mt-4"
          ariaLabel="Разделы администрирования"
          value={tab}
          onChange={(next) => setParams(next === 'users' ? {} : { tab: next }, { replace: true })}
          options={[
            { value: 'users', label: 'Пользователи', count: users.length },
            { value: 'groups', label: 'Группы', count: groups.length },
            { value: 'access', label: 'Доступ к отчётам', count: accessReady ? grants : undefined },
            { value: 'mail', label: 'Почтовые серверы', count: mailCount },
          ]}
        />
      </PageHeader>

      {error && <Alert className="mb-4">{error}</Alert>}
      {notice && (
        <Alert tone="success" className="mb-4">
          {notice}
        </Alert>
      )}

      {loading ? (
        <SkeletonRows count={5} />
      ) : tab === 'users' ? (
        <UsersPanel
          users={users}
          groups={groups}
          userReports={accessReady ? userReports : null}
          onChanged={reload}
          onFail={fail}
          onNotice={setNotice}
        />
      ) : tab === 'groups' ? (
        <GroupsPanel
          groups={groups}
          users={users}
          groupReports={accessReady ? groupReports : null}
          onChanged={reload}
          onFail={fail}
        />
      ) : tab === 'access' ? (
        !accessReady ? (
          <SkeletonRows count={5} />
        ) : (
        <AccessPanel
          reports={reports}
          users={users}
          groups={groups}
          access={access}
          onChanged={reload}
          onFail={fail}
        />
        )
      ) : (
        <MailServersPanel onCount={setMailCount} />
      )}
    </Page>
  )
}
