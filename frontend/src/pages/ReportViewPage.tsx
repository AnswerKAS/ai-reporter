import { useEffect, useState } from 'react'
import { useParams, Navigate, Link, useNavigate } from 'react-router-dom'
import type { Report } from '../types/report'
import type { DrillPoint } from '../lib/api'
import { ApiError, applyFilters, deleteReport, fetchReport, restoreReport } from '../lib/api'
import { SectionsGrid } from '../components/SectionsGrid'
import { DrilldownDialog } from '../components/DrilldownDialog'
import { ScheduleDialog } from '../components/ScheduleDialog'
import { ReportFilters } from '../components/ReportFilters'
import { useAuth } from '../lib/auth'
import { useReports } from '../lib/reports'
import {
  Alert,
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  Page,
  PageHeader,
  Skeleton,
  SkeletonCards,
} from '../components/ui'

const LIVE_INTERVAL_MS = 15000

/** Navigate from a report back to the catalog. */
function Crumbs() {
  return (
    <nav className="mb-3.5 text-sm">
      <Link to="/reports" className="text-fg-muted hover:text-accent">
        ← Отчёты
      </Link>
    </nav>
  )
}

/** Open the report definition in the editor. */
function ReportEdit({ report }: { report: Report }) {
  // отчёт правится там же, где собирался: состав секций, поля и формулы
  // живут в конструкторе, а не в отдельной форме
  return (
    <Link
      to={`/workspace/${report.slug}`}
      className="inline-flex items-center rounded-control border border-transparent px-3.5 py-1.5 text-sm text-fg-muted transition-colors hover:bg-surface-sunken hover:text-fg"
    >
      Редактировать
    </Link>
  )
}


/** Explain a loading or unavailable report state. */
function StatusScreen({ title, description, busy }: { title: string; description: string; busy?: boolean }) {
  return (
    <Page>
      <Crumbs />
      <EmptyState
        title={title}
        description={description}
        action={busy ? <Skeleton className="h-1.5 w-48 animate-pulse" /> : undefined}
      />
    </Page>
  )
}

/** Display live reports or the reason and recovery actions for archived reports. */
export function ReportViewPage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { isAdmin, user } = useAuth()
  const { reload: reloadReports, markVisited, removeRecent } = useReports()
  const [report, setReport] = useState<Report | null>(null)
  const [status, setStatus] = useState<string>('loading')
  const [failure, setFailure] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  // что открыто в детализации: сырьё датасета или точка конкретной секции
  const [drill, setDrill] = useState<{ target: DrillPoint; title: string } | null>(null)
  const [mailOpen, setMailOpen] = useState(false)

  useEffect(() => {
    if (!slug) return
    let alive = true

    const load = async () => {
      // GET исполняет определение отчёта — данные всегда свежие
      try {
        const data = await fetchReport(slug!)
        if (!alive) return
        if (data?.sections) {
          setReport(data)
          setStatus('ready')
          // «Недавние» в меню слева ведут отсюда: каталог не знает, куда
          // человек ходил, и знать не должен — это его браузер
          if (!data.archivedAt) markVisited(data)
          else removeRecent(data.slug)
          return
        }
        setStatus('error')
      } catch (err) {
        if (!alive) return
        // ошибку источника показываем словами: читатель не писал запрос и
        // должен понимать, чинить ему фильтр или ждать источник
        const denied = err instanceof ApiError && err.status === 403
        const missing = err instanceof ApiError && err.status === 404
        setFailure(err instanceof Error ? err.message : null)
        setStatus(denied ? 'forbidden' : missing ? 'missing' : 'error')
      }
    }

    load()
    return () => {
      alive = false
    }
  }, [slug, markVisited, removeRecent])

  useEffect(() => {
    if (!slug || !report || report.archivedAt) return
    const id = setInterval(async () => {
      try {
        const fresh = await fetchReport(slug)
        if (fresh?.sections) {
          setReport(fresh)
          if (fresh.archivedAt) { removeRecent(fresh.slug); void reloadReports() }
        }
      } catch {
        // A later refresh retries transient source failures.
      }
    }, LIVE_INTERVAL_MS)
    return () => clearInterval(id)
  }, [slug, report, removeRecent, reloadReports])

  /** Apply one reader filter and replace the live report result. */
  const onFilterChange = async (key: string, value: string) => {
    if (!slug || !report) return
    const values = { ...(report.filterValues ?? {}), [key]: value }
    setRefreshing(true)
    try {
      const fresh = await applyFilters(slug, values)
      if (fresh?.sections) setReport(fresh)
    } finally {
      setRefreshing(false)
    }
  }

  if (!slug) return <Navigate to="/reports" replace />

  if (!report && status === 'loading') {
    return (
      <Page>
        <Crumbs />
        <Skeleton className="mb-2 h-9 w-80" />
        <Skeleton className="mb-7 h-4 w-56" />
        <SkeletonCards count={4} />
      </Page>
    )
  }

  if (!report) {
    if (status === 'error') {
      return (
        <StatusScreen
          title="Не удалось посчитать отчёт"
          description={failure ?? 'Источник данных не ответил. Попробуйте обновить страницу через минуту.'}
        />
      )
    }
    if (status === 'forbidden') {
      return <StatusScreen title="Нет доступа" description="Этот отчёт не назначен вашему аккаунту." />
    }
    return <Navigate to="/reports" replace />
  }

  if (report.archivedAt) {
    const canEdit = isAdmin || Boolean(user && report.createdBy === user.id)
    return (
      <Page>
        <Link to="/reports?archived=1" className="text-sm text-accent hover:underline">← Архив отчётов</Link>
        <PageHeader title={report.title} subtitle="Отчёт в архиве" />
        <EmptyState title="Источник отчёта удалён" description={report.archiveReason ?? 'Исправьте источники и восстановите отчёт.'}
          action={canEdit ? <div className="flex flex-wrap gap-2">
            <ReportEdit report={report} />
            <Button disabled={refreshing} onClick={async () => {
              setRefreshing(true)
              setFailure(null)
              try {
                await restoreReport(report.slug)
                const fresh = await fetchReport(report.slug)
                if (!fresh) throw new Error('Не удалось открыть восстановленный отчёт')
                setReport(fresh)
                markVisited(fresh)
                await reloadReports()
              } catch (err) {
                setFailure(err instanceof Error ? err.message : 'Не удалось восстановить отчёт')
              } finally { setRefreshing(false) }
            }}>{refreshing ? 'Проверяем…' : 'Восстановить отчёт'}</Button>
          </div> : undefined} />
        {failure && <Alert>{failure}</Alert>}
      </Page>
    )
  }

  return (
    <Page>
      <Crumbs />
      <PageHeader
        title={report.title}
        subtitle={report.description || undefined}
        actions={
          <>
            {report.drilldown && (
              <Button
                variant="ghost"
                onClick={() => setDrill({ target: {}, title: 'Сырые строки датасета' })}
              >
                Сырые данные
              </Button>
            )}
            <Button variant="ghost" onClick={() => setMailOpen(true)}>
              Отправка по почте
            </Button>
            {(isAdmin || (user && report.createdBy === user.id)) && <ReportEdit report={report} />}
            {isAdmin && (
              <Button variant="danger" onClick={() => setConfirming(true)}>
                Удалить отчёт
              </Button>
            )}
          </>
        }
      >
        <div className="mt-3.5 flex flex-wrap items-center gap-2">
          <Badge>Обновлён: {report.updatedAt}</Badge>
          <Badge tone="good" title="Данные пересчитываются при открытии страницы">
            live
          </Badge>
        </div>
      </PageHeader>

      {report.filters && report.filters.length > 0 && (
        <ReportFilters
          filters={report.filters}
          values={report.filterValues ?? {}}
          disabled={refreshing}
          onChange={onFilterChange}
        />
      )}

      {report.sections.length === 0 ? (
        <EmptyState title="В отчёте нет секций" description="В определении отчёта нет ни одной секции — добавьте их в конструкторе." />
      ) : (
        <SectionsGrid
          sections={report.sections}
          onDrill={
            report.drilldown
              ? (sectionIndex, point, label, metricKey, scope) =>
                  setDrill({
                    target: scope === 'dataset' ? { sectionIndex } : { sectionIndex, point, metricKey },
                    title: scope === 'dataset' ? 'Исходные строки датасета'
                      : label ? `Строки: ${label}` : 'Строки под показателем',
                  })
              : undefined
          }
        />
      )}

      {mailOpen && slug && <ScheduleDialog slug={slug} onClose={() => setMailOpen(false)} />}

      {drill && slug && (
        <DrilldownDialog
          slug={slug}
          target={drill.target}
          title={drill.title}
          onClose={() => setDrill(null)}
        />
      )}

      {confirming && (
        <ConfirmDialog
          title="Удалить отчёт?"
          description={`Отчёт «${report.title}» будет удалён вместе с назначениями доступа. Действие необратимо.`}
          onClose={() => setConfirming(false)}
          onConfirm={async () => {
            await deleteReport(report.slug)
            removeRecent(report.slug)
            await reloadReports()
            navigate('/reports')
          }}
        />
      )}
    </Page>
  )
}
