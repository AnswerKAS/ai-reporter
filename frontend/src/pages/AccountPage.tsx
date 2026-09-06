import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { ScheduleDigestItem, ScheduleServer } from '../types/user'
import { ApiError, fetchScheduleDigest } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useReports, useReportSearch } from '../lib/reports'
import { ReportsPanel } from '../components/account/ReportsPanel'
import { SchedulesPanel } from '../components/account/SchedulesPanel'
import { SecurityPanel } from '../components/account/SecurityPanel'
import { ScheduleDialog } from '../components/ScheduleDialog'
import { Alert, Button, Page, PageHeader, Segmented } from '../components/ui'

type Tab = 'reports' | 'schedules' | 'security'

const TABS: Tab[] = ['reports', 'schedules', 'security']
type Scope = 'mine' | 'all'

/**
 * Кабинет вкладками — той же механикой, что админка: раздел живёт в адресе
 * (`/account?tab=schedules`), поэтому ссылку можно передать, а возврат «назад»
 * из отчёта не сбрасывает выбранное.
 *
 * Свод рассылок грузится страницей, а не вкладкой: по нему считается и число
 * рассылок у каждого отчёта в соседней вкладке, и счётчик на самой вкладке.
 */
export function AccountPage() {
  const { user, isAdmin } = useAuth()
  const { facets } = useReports()
  // список отчётов нужен только вкладке рассылок — там из него собран выбор
  // отчёта. Полтысячи строк в селекте это уже потолок читаемости, и потолок
  // страницы каталога тот же: выбор отчёта в рассылке пора делать поиском.
  const { reports } = useReportSearch({ sort: 'title', limit: 500 })
  const [params, setParams] = useSearchParams()
  const tab = (TABS as string[]).includes(params.get('tab') ?? '')
    ? (params.get('tab') as Tab)
    : 'reports'

  const [scope, setScope] = useState<Scope>('mine')
  const [schedules, setSchedules] = useState<ScheduleDigestItem[] | null>(null)
  const [servers, setServers] = useState<ScheduleServer[]>([])
  const [error, setError] = useState<string | null>(null)
  /** Окно рассылки отчёта — то же, что на его странице: заводится оттуда. */
  const [scheduling, setScheduling] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const data = await fetchScheduleDigest(scope)
      setSchedules(data.schedules)
      setServers(data.servers)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'не удалось загрузить рассылки')
      setSchedules([])
    }
  }, [scope])

  useEffect(() => {
    if (user) void reload()
  }, [user, reload])

  /** Свои рассылки по отчётам: счётчики не должны меняться от того, что
      администратор переключил свод на «все в системе». */
  const mine = useMemo(
    () => (schedules ?? []).filter((s) => s.author_id === user?.id),
    [schedules, user],
  )

  const counts = useMemo(() => {
    if (schedules === null) return null
    const map: Record<string, number> = {}
    for (const s of mine) map[s.report_slug] = (map[s.report_slug] ?? 0) + 1
    return map
  }, [schedules, mine])

  if (!user) return null

  return (
    <Page>
      <PageHeader
        title="Личный кабинет"
        subtitle={`${user.username} · ${user.role === 'admin' ? 'администратор' : 'пользователь'}`}
        actions={
          <Button onClick={() => void reload()} disabled={schedules === null}>
            Обновить
          </Button>
        }
      >
        <Segmented
          className="mt-4"
          ariaLabel="Разделы кабинета"
          value={tab}
          onChange={(next) => setParams(next === 'reports' ? {} : { tab: next }, { replace: true })}
          options={[
            { value: 'reports', label: 'Мои отчёты', count: facets?.total },
            {
              value: 'schedules',
              label: 'Мои рассылки',
              count: schedules === null ? undefined : mine.length,
            },
            { value: 'security', label: 'Безопасность' },
          ]}
        />
      </PageHeader>

      {error && <Alert className="mb-4">{error}</Alert>}

      {tab === 'reports' ? (
        <ReportsPanel
          scheduleCounts={counts}
          isAdmin={isAdmin}
          onSchedule={setScheduling}
        />
      ) : tab === 'schedules' ? (
        <SchedulesPanel
          items={schedules}
          servers={servers}
          reports={reports}
          scope={scope}
          isAdmin={isAdmin}
          onScope={setScope}
          onChanged={reload}
        />
      ) : (
        <SecurityPanel user={user} isAdmin={isAdmin} />
      )}

      {scheduling && (
        <ScheduleDialog
          slug={scheduling}
          onClose={() => {
            setScheduling(null)
            // в окне могли завести или удалить рассылку — свод об этом не знает
            void reload()
          }}
        />
      )}
    </Page>
  )
}
