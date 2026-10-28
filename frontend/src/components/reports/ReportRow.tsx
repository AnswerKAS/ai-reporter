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
  variant = 'sidebar',
}: {
  report: ReportMeta
  favorite: boolean
  isAdmin: boolean
  onNavigate?: () => void
  onRename: () => void
  onDelete: () => void
  onToggleFavorite: () => void
  variant?: 'sidebar' | 'catalog' | 'preview'
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
    ...(canEdit ? [{ label: 'Переименовать', onSelect: onRename }, { label: 'Изменить метки', onSelect: onRename }] : []),
    { label: favorite ? 'Открепить' : 'Закрепить', onSelect: onToggleFavorite },
    ...(isAdmin ? [{ label: 'Удалить', onSelect: onDelete, danger: true }] : []),
  ]

  return (
    <div className={cn(
      'group/row flex min-w-0 items-center gap-1 transition-colors hover:bg-surface-sunken',
      variant === 'catalog' ? 'border-b border-line px-2 py-1.5 last:border-b-0' : 'rounded-control',
    )}>
      <NavLink
        to={`/reports/${report.slug}`}
        onClick={onNavigate}
        title={report.description ? `${report.title} — ${report.description}` : report.title}
        className={({ isActive }) =>
          cn(
            'flex min-h-10 min-w-0 flex-1 items-center gap-2 rounded-control px-3 text-sm transition-colors',
            variant === 'catalog' ? 'py-2.5' : 'py-1.5',
            isActive ? 'bg-accent-soft font-semibold text-accent' : 'text-fg',
          )
        }
      >
        <StatusDot status={report.archivedAt ? undefined : report.status} />
        <span className="min-w-0 flex-1">
          <span className={cn('block min-w-0 break-words', variant === 'catalog' ? 'font-medium' : 'line-clamp-2')}>
            {report.title}
          </span>
          {variant === 'catalog' && (
            <span className="mt-1 block min-w-0 text-xs font-normal text-fg-muted">
              {report.description && <span className="mb-1 block line-clamp-1">{report.description}</span>}
              <span className="flex flex-wrap gap-x-2 gap-y-0.5">
                {report.author && <span>{report.author}</span>}
                <span>Обновлён {report.updatedAt.slice(0, 10)}</span>
                {report.tags?.slice(0, 2).map((tag) => <span key={tag}>#{tag}</span>)}
              </span>
            </span>
          )}
        </span>
        {variant === 'catalog' && <span aria-hidden="true" className="hidden shrink-0 text-xs text-accent sm:inline">Открыть →</span>}
      </NavLink>

      {variant !== 'preview' && <button
        type="button"
        aria-label={favorite ? `Открепить «${report.title}»` : `Закрепить «${report.title}»`}
        aria-pressed={favorite}
        title={favorite ? 'Открепить' : 'Закрепить'}
        onClick={onToggleFavorite}
        className={cn('flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-control text-sm transition-colors hover:bg-accent-soft', favorite ? 'text-warn' : 'text-fg-muted hover:text-fg')}
      >
        <span aria-hidden="true">{favorite ? '★' : '☆'}</span>
      </button>}
      {variant !== 'preview' && <RowMenu label={`Действия с отчётом «${report.title}»`} actions={actions} />}
    </div>
  )
}
