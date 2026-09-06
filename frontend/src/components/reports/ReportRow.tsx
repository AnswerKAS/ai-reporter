import { NavLink, useNavigate } from 'react-router-dom'
import type { ReportMeta } from '../../types/report'
import { cn } from '../../lib/cn'
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
 * Кнопки конструктора, переименования и удаления остаются на своих местах и
 * появляются по наведению, а те же действия дублируются в меню «…», которое
 * видно всегда: на тач-устройстве наведения нет вовсе.
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
  const actions = [
    {
      label: 'Открыть в конструкторе',
      onSelect: () => {
        onNavigate?.()
        navigate(`/builder/${report.slug}`)
      },
    },
    { label: 'Переименовать', onSelect: onRename },
    { label: favorite ? 'Открепить' : 'Закрепить', onSelect: onToggleFavorite },
    ...(isAdmin ? [{ label: 'Удалить', onSelect: onDelete, danger: true }] : []),
  ]

  return (
    <div className="group/row flex items-center gap-0.5">
      <button
        type="button"
        aria-label={favorite ? `Открепить «${report.title}»` : `Закрепить «${report.title}»`}
        aria-pressed={favorite}
        title={favorite ? 'Открепить' : 'Закрепить'}
        onClick={onToggleFavorite}
        className={cn(
          'shrink-0 cursor-pointer rounded-control px-1 py-1 text-xs transition-colors',
          favorite
            ? 'text-warn'
            : 'text-fg-muted opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100 hover:text-fg',
        )}
      >
        <span aria-hidden="true">{favorite ? '★' : '☆'}</span>
      </button>

      <NavLink
        to={`/reports/${report.slug}`}
        onClick={onNavigate}
        title={report.description ? `${report.title} — ${report.description}` : report.title}
        className={({ isActive }) =>
          cn(
            'flex min-w-0 flex-1 items-center gap-2 rounded-control px-2 py-1.5 text-sm transition-colors',
            isActive ? 'bg-accent-soft font-semibold text-accent' : 'text-fg hover:bg-bg',
          )
        }
      >
        <StatusDot status={report.status} />
        <span className="truncate">{report.title}</span>
      </NavLink>

      <span className="flex shrink-0 items-center">
        <span className="hidden items-center opacity-0 transition-opacity group-hover/row:opacity-100 focus-within:opacity-100 md:flex">
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
        <span className="flex items-center md:opacity-0 md:transition-opacity md:group-hover/row:opacity-100 md:focus-within:opacity-100">
          <RowMenu label={`Действия с отчётом «${report.title}»`} actions={actions} />
        </span>
      </span>
    </div>
  )
}
