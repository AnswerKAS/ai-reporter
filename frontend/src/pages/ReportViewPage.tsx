import { useEffect, useState } from 'react'
import { useParams, Navigate, Link, useNavigate } from 'react-router-dom'
import type { Report } from '../types/report'
import { applyFilters, deleteReport, fetchReport, fetchSkillContent, updateReport } from '../lib/api'
import { SectionRenderer } from '../components/SectionRenderer'
import { ReportFilters } from '../components/ReportFilters'
import { useAuth } from '../lib/auth'
import { useReports } from '../lib/reports'
import {
  Alert,
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  Page,
  PageHeader,
  Skeleton,
  SkeletonCards,
} from '../components/ui'
import { cn } from '../lib/cn'

const LIVE_INTERVAL_MS = 15000

function Crumbs() {
  return (
    <nav className="mb-3.5 text-sm">
      <Link to="/reports" className="text-fg-muted hover:text-accent">
        ← Отчёты
      </Link>
    </nav>
  )
}

function ReportEdit({ report, onSaved }: { report: Report; onSaved: () => void }) {
  const { reload } = useReports()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState(report.title)
  const [description, setDescription] = useState(report.description ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setTitle(report.title)
      setDescription(report.description ?? '')
      setError(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, report.slug])

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await updateReport(report.slug, { title: title.trim(), description: description.trim() || undefined })
      await reload()
      setOpen(false)
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'не удалось сохранить')
    } finally {
      setBusy(false)
    }
  }

  // отчёт-конструктор правится там же, где собирался: состав секций,
  // поля и формулы живут в конструкторе, а не в этой форме
  if (report.kind === 'builder') {
    return (
      <Link
        to={`/builder/${report.slug}`}
        className="inline-flex items-center rounded-control border border-transparent px-3.5 py-1.5 text-sm text-fg-muted transition-colors hover:bg-surface-sunken hover:text-fg"
      >
        Редактировать
      </Link>
    )
  }

  if (!open) {
    return (
      <Button variant="ghost" onClick={() => setOpen(true)}>
        Редактировать
      </Button>
    )
  }

  return (
    <div className="mt-3 flex w-full max-w-xl flex-col gap-2.5 rounded-card border border-line bg-surface p-3.5">
      <Field label="Название">
        <Input value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <Field label="Описание">
        <Input value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      {error && <Alert>{error}</Alert>}
      <div className="flex gap-2">
        <Button variant="primary" disabled={busy || !title.trim()} onClick={save}>
          {busy ? 'Сохраняем…' : 'Сохранить'}
        </Button>
        <Button variant="ghost" disabled={busy} onClick={() => setOpen(false)}>
          Отмена
        </Button>
      </div>
    </div>
  )
}

function SkillInline({ skill }: { skill: string }) {
  const [open, setOpen] = useState(false)
  const [content, setContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const toggle = () => {
    const next = !open
    setOpen(next)
    if (next && content === null && !loading) {
      setLoading(true)
      fetchSkillContent(skill)
        .then(setContent)
        .catch(() => setError('не удалось загрузить текст скилла'))
        .finally(() => setLoading(false))
    }
  }

  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        onClick={toggle}
        className={cn(
          'inline-flex cursor-pointer items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors',
          open ? 'border-accent bg-accent-soft text-accent' : 'border-accent-soft bg-accent-soft text-accent hover:border-accent',
        )}
      >
        Скилл: {skill}
      </button>
      {open && (
        <section className="mt-3 w-full rounded-card border border-line bg-surface p-4">
          <div className="mb-2.5 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Текст скилла</h2>
            <Button variant="ghost" size="sm" onClick={toggle}>
              Скрыть
            </Button>
          </div>
          {error ? (
            <Alert>{error}</Alert>
          ) : content === null ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-11/12" />
              <Skeleton className="h-4 w-3/4" />
            </div>
          ) : (
            <pre className="overflow-x-auto text-sm leading-relaxed break-words whitespace-pre-wrap">{content}</pre>
          )}
        </section>
      )}
    </>
  )
}

/** Экран вместо отчёта: сборка, ошибка, отсутствие доступа. */
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

export function ReportViewPage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const { reload: reloadReports } = useReports()
  const [report, setReport] = useState<Report | null>(null)
  const [status, setStatus] = useState<string>('loading')
  const [refreshing, setRefreshing] = useState(false)
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    if (!slug) return
    let alive = true

    const load = async () => {
      // GET пересчитывает данные из БД — изменения в БД видны сразу
      let data: Report | null = null
      try {
        data = await fetchReport(slug!)
      } catch {
        data = null
      }
      if (!alive) return
      if (data?.sections) {
        setReport(data)
        setStatus('ready')
        return
      }
      const res = await fetch(`/api/reports/${slug}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('ai-reporter-token') ?? ''}` },
      }).catch(() => null)
      if (res && (res.status === 403 || res.status === 404)) {
        setStatus(res.status === 403 ? 'forbidden' : 'missing')
        return
      }
      const meta = res && res.ok ? ((await res.json()) as { report: Report }).report : null
      if (meta) setStatus(meta.status ?? 'unknown')
      else setStatus('error')
    }

    load()
    return () => {
      alive = false
    }
  }, [slug])

  useEffect(() => {
    if (!slug || !report) return
    const id = setInterval(async () => {
      const fresh = await fetchReport(slug)
      if (fresh?.sections) setReport(fresh)
    }, LIVE_INTERVAL_MS)
    return () => clearInterval(id)
  }, [slug, report])

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
    if (status === 'building' || status === 'queued') {
      return (
        <StatusScreen
          busy
          title="Идёт сборка отчёта"
          description={`Статус: ${status}. Страница обновится, когда сборка закончится — можно вернуться позже.`}
        />
      )
    }
    if (status === 'error') {
      return (
        <StatusScreen
          title="Ошибка сборки отчёта"
          description="Скрипт отчёта не собрался. Попробуйте пересобрать отчёт позже или проверьте скилл."
        />
      )
    }
    if (status === 'forbidden') {
      return <StatusScreen title="Нет доступа" description="Этот отчёт не назначен вашему аккаунту." />
    }
    return <Navigate to="/reports" replace />
  }

  return (
    <Page>
      <Crumbs />
      <PageHeader
        title={report.title}
        subtitle={report.description || undefined}
        actions={
          <>
            <ReportEdit
              report={report}
              onSaved={() => {
                if (!slug) return
                fetchReport(slug).then((fresh) => {
                  if (fresh?.sections) setReport(fresh)
                })
              }}
            />
            {isAdmin && (
              <Button variant="danger" onClick={() => setConfirming(true)}>
                Удалить отчёт
              </Button>
            )}
          </>
        }
      >
        <div className="mt-3.5 flex flex-wrap items-center gap-2">
          {report.skill && <SkillInline skill={report.skill} />}
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
        <EmptyState title="В отчёте нет секций" description="Скилл собрался, но не вернул ни одной секции." />
      ) : (
        <div className="flex flex-col gap-6">
          {report.sections.map((section, i) => (
            <SectionRenderer key={i} section={section} />
          ))}
        </div>
      )}

      {confirming && (
        <ConfirmDialog
          title="Удалить отчёт?"
          description={`Отчёт «${report.title}» будет удалён вместе с назначениями доступа и артефактами. Действие необратимо.`}
          onClose={() => setConfirming(false)}
          onConfirm={async () => {
            await deleteReport(report.slug)
            await reloadReports()
            navigate('/reports')
          }}
        />
      )}
    </Page>
  )
}
