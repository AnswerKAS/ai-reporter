import { NavLink, useNavigate } from 'react-router-dom'
import type { ReportMeta } from '../../types/report'
import { cn } from '../../lib/cn'
import { useAuth } from '../../lib/auth'
import { RowMenu } from './RowMenu'

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

/**
 * Строка отчёта в меню: ссылка, закрепление и действия.
 *
 * Название занимает основную ширину; закрепление и меню действий доступны
 * постоянно, в том числе с клавиатуры и на сенсорном экране.
 */
export function ReportRow({
  report,
  favorite,
  isAdmin,
  onNavigate,
  onRename,
  onDelete,
  onToggleFavorite,
}: {
  report: ReportMeta
  favorite: boolean
  isAdmin: boolean
  onNavigate?: () => void
  onRename: () => void
  onDelete: () => void
  onToggleFavorite: () => void
}) {
  const navigate = useNavigate()
  const { user } = useAuth()
  const canEdit = isAdmin || Boolean(user && report.createdBy === user.id)
  const actions = [
    ...(canEdit ? [{
      label: 'Открыть в конструкторе',
      onSelect: () => {
        onNavigate?.()
        navigate(`/workspace/${report.slug}`)
      },
    }] : []),
    ...(canEdit ? [{ label: 'Переименовать', onSelect: onRename }] : []),
    { label: favorite ? 'Открепить' : 'Закрепить', onSelect: onToggleFavorite },
    ...(isAdmin ? [{ label: 'Удалить', onSelect: onDelete, danger: true }] : []),
  ]

  return (
    <div className="group/row flex min-w-0 items-center gap-1 rounded-control transition-colors hover:bg-surface-sunken">
      <NavLink
        to={`/reports/${report.slug}`}
        onClick={onNavigate}
        title={report.description ? `${report.title} — ${report.description}` : report.title}
        className={({ isActive }) =>
          cn(
            'flex min-h-10 min-w-0 flex-1 items-center gap-2 rounded-control px-3 py-1.5 text-sm transition-colors',
            isActive ? 'bg-accent-soft font-semibold text-accent' : 'text-fg',
          )
        }
      >
        <StatusDot status={report.status} />
        <span className="min-w-0 whitespace-normal break-words">{report.title}</span>
      </NavLink>

      <button
        type="button"
        aria-label={favorite ? `Открепить «${report.title}»` : `Закрепить «${report.title}»`}
        aria-pressed={favorite}
        title={favorite ? 'Открепить' : 'Закрепить'}
        onClick={onToggleFavorite}
        className={cn('flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-control text-sm transition-colors hover:bg-accent-soft', favorite ? 'text-warn' : 'text-fg-muted hover:text-fg')}
      >
        <span aria-hidden="true">{favorite ? '★' : '☆'}</span>
      </button>
      <RowMenu label={`Действия с отчётом «${report.title}»`} actions={actions} />
    </div>
  )
}
