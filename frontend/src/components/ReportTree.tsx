import { useMemo, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import type { ReportMeta } from '../types/report'
import { deleteReport, updateReport } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useReports } from '../lib/reports'
import { cn } from '../lib/cn'
import { Alert, Button, Field, Input, Modal, Skeleton, useConfirm } from './ui'

/** Точка статуса: готовый отчёт молчит, сборка и ошибка — видны прямо в меню. */
function StatusDot({ status }: { status?: string }) {
  if (!status || status === 'ready') return null
  const failed = status === 'error'
  return (
    <span
      aria-label={failed ? 'ошибка сборки' : 'собирается'}
      title={failed ? 'ошибка сборки' : `собирается (${status})`}
      className={cn('size-1.5 shrink-0 rounded-full', failed ? 'bg-bad' : 'animate-pulse bg-warn')}
    />
  )
}

function RenameDialog({ report, onClose }: { report: ReportMeta; onClose: () => void }) {
  const { reload } = useReports()
  const [title, setTitle] = useState(report.title)
  const [description, setDescription] = useState(report.description ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await updateReport(report.slug, {
        title: title.trim(),
        description: description.trim() || undefined,
      })
      await reload()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'не удалось сохранить')
      setBusy(false)
    }
  }

  return (
    <Modal
      title="Переименовать отчёт"
      onClose={onClose}
      footer={
        <>
          <Button variant="primary" disabled={busy || !title.trim()} onClick={save}>
            {busy ? 'Сохраняем…' : 'Сохранить'}
          </Button>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Отмена
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-2.5">
        <Field label="Название">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Описание">
          <Input value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <p className="font-mono text-xs text-fg-muted">{report.slug}</p>
        {error && <Alert>{error}</Alert>}
      </div>
    </Modal>
  )
}

function ReportRow({
  report,
  onNavigate,
  onRename,
  onDelete,
}: {
  report: ReportMeta
  onNavigate?: () => void
  onRename: () => void
  onDelete: () => void
}) {
  const { isAdmin } = useAuth()

  return (
    <div className="group/row flex items-center gap-0.5">
      <NavLink
        to={`/reports/${report.slug}`}
        onClick={onNavigate}
        title={report.title}
        className={({ isActive }) =>
          cn(
            'flex min-w-0 flex-1 items-center gap-2 rounded-control px-2.5 py-1.5 text-sm transition-colors',
            isActive ? 'bg-accent-soft font-semibold text-accent' : 'text-fg hover:bg-bg',
          )
        }
      >
        <StatusDot status={report.status} />
        <span className="truncate">{report.title}</span>
      </NavLink>

      <span className="flex shrink-0 items-center opacity-0 transition-opacity group-hover/row:opacity-100 focus-within:opacity-100">
        <NavLink
          to={`/builder/${report.slug}`}
          onClick={onNavigate}
          aria-label={`Открыть «${report.title}» в конструкторе`}
          title="Открыть в конструкторе"
          className="rounded-control px-1.5 py-1 text-xs text-fg-muted hover:bg-bg hover:text-fg"
        >
          <span aria-hidden="true">⚙</span>
        </NavLink>
        <button
          type="button"
          aria-label={`Переименовать «${report.title}»`}
          title="Переименовать"
          onClick={onRename}
          className="cursor-pointer rounded-control px-1.5 py-1 text-xs text-fg-muted hover:bg-bg hover:text-fg"
        >
          <span aria-hidden="true">✎</span>
        </button>
        {isAdmin && (
          <button
            type="button"
            aria-label={`Удалить «${report.title}»`}
            title="Удалить"
            onClick={onDelete}
            className="cursor-pointer rounded-control px-1.5 py-1 text-xs text-fg-muted hover:bg-bad-soft hover:text-bad"
          >
            <span aria-hidden="true">✕</span>
          </button>
        )}
      </span>
    </div>
  )
}

/**
 * Меню отчётов: активный отчёт подсвечен, а создание, переименование и
 * удаление живут здесь же — раньше отчётами управляли с трёх разных экранов.
 */
export function ReportTree({ className, onNavigate }: { className?: string; onNavigate?: () => void }) {
  const { reports, loading, error, reload } = useReports()
  const { isAdmin } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const { confirm, dialog } = useConfirm()
  const [query, setQuery] = useState('')
  const [renaming, setRenaming] = useState<ReportMeta | null>(null)

  const activeSlug = useMemo(() => {
    const m = decodeURIComponent(location.pathname).match(/^\/(?:reports|builder)\/(.+)$/)
    return m ? m[1] : null
  }, [location.pathname])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const found = q
      ? reports.filter((r) =>
          [r.title, r.slug, r.description ?? ''].some((v) => v.toLowerCase().includes(q)),
        )
      : reports
    return [...found].sort((a, b) => a.title.localeCompare(b.title))
  }, [reports, query])

  const askDelete = (report: ReportMeta) =>
    confirm({
      title: 'Удалить отчёт?',
      description: `Отчёт «${report.title}» будет удалён вместе с назначениями доступа. Действие необратимо.`,
      onConfirm: async () => {
        await deleteReport(report.slug)
        await reload()
        if (report.slug === activeSlug) navigate('/reports')
      },
    })

  return (
    <nav aria-label="Отчёты" className={className}>
      <div className="mb-2 flex items-center justify-between gap-2 px-2">
        <NavLink
          to="/reports"
          onClick={onNavigate}
          className="text-xs font-bold tracking-wider text-fg-muted uppercase hover:text-fg"
        >
          Отчёты {reports.length > 0 && <span className="font-mono">({reports.length})</span>}
        </NavLink>
        {isAdmin && (
          <NavLink
            to="/builder"
            onClick={onNavigate}
            aria-label="Новый отчёт"
            title="Новый отчёт"
            className="rounded-control px-1.5 text-base leading-none text-fg-muted hover:bg-bg hover:text-accent"
          >
            <span aria-hidden="true">＋</span>
          </NavLink>
        )}
      </div>

      {reports.length > 4 && (
        <Input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Поиск отчёта"
          aria-label="Поиск отчёта"
          className="mb-2"
        />
      )}

      {error && <Alert className="mb-2 text-xs">{error}</Alert>}

      {loading && reports.length === 0 ? (
        <div className="flex flex-col gap-1.5 px-2">
          <Skeleton className="h-5 w-3/4" />
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-5 w-1/2" />
        </div>
      ) : reports.length === 0 ? (
        <p className="px-2 text-sm text-fg-muted">
          Отчётов пока нет.{' '}
          {isAdmin && (
            <NavLink to="/builder" onClick={onNavigate} className="text-accent hover:underline">
              Собрать первый
            </NavLink>
          )}
        </p>
      ) : filtered.length === 0 ? (
        <p className="px-2 text-sm text-fg-muted">Ничего не найдено</p>
      ) : (
        <div className="flex flex-col">
          {filtered.map((r) => (
            <ReportRow
              key={r.slug}
              report={r}
              onNavigate={onNavigate}
              onRename={() => setRenaming(r)}
              onDelete={() => askDelete(r)}
            />
          ))}
        </div>
      )}

      {renaming && <RenameDialog report={renaming} onClose={() => setRenaming(null)} />}
      {dialog}
    </nav>
  )
}
