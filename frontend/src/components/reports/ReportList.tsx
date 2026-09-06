import { useCallback, useEffect, useRef, type ReactNode } from 'react'
import type { ReportMeta, ReportQuery } from '../../types/report'
import { useAuth } from '../../lib/auth'
import { useReports, useReportSearch } from '../../lib/reports'
import { Alert, Skeleton } from '../ui'
import { ReportRow } from './ReportRow'

/** За сколько пикселей до конца списка просить следующую страницу. */
const REACH = 240

/** Ближайший прокручиваемый предок: меню слева прокручивается само, и
    наблюдателю нужен именно его бокс, а не окно. */
function scrollParent(node: HTMLElement | null): HTMLElement | null {
  for (let el = node?.parentElement ?? null; el; el = el.parentElement) {
    const overflow = getComputedStyle(el).overflowY
    if (overflow === 'auto' || overflow === 'scroll') return el
  }
  return null
}

/**
 * Постраничный список отчётов: строки, догрузка и пустое состояние.
 *
 * Следующая страница подтягивается, когда конец списка доезжает до края
 * прокрутки. Та же метка — кнопка: с клавиатуры и на тач-устройстве догрузку
 * надо уметь позвать явно.
 */
export function ReportList({
  query,
  onNavigate,
  onEdit,
  onDelete,
  empty = 'Ничего не найдено',
}: {
  query: ReportQuery
  onNavigate?: () => void
  onEdit: (report: ReportMeta) => void
  onDelete: (report: ReportMeta) => void
  /** Что показать, когда выдача пуста: у поиска и у пустого каталога это
      разные сообщения, и знает их вызывающий. */
  empty?: ReactNode
}) {
  const { isAdmin } = useAuth()
  const { isFavorite, toggleFavorite } = useReports()
  const { reports, total, loading, error, hasMore, loadMore } = useReportSearch(query)
  const sentinel = useRef<HTMLButtonElement>(null)

  const more = useCallback(() => loadMore(), [loadMore])

  useEffect(() => {
    const node = sentinel.current
    if (!node || !hasMore) return
    // наблюдатель, а не обработчик прокрутки: тот считал бы геометрию на
    // каждый кадр прокрутки списка в сотни строк. Смотрим за самой меткой —
    // раскрытых групп бывает несколько, и у каждой своя выдача в общем скролле
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) more()
      },
      { root: scrollParent(node), rootMargin: `${REACH}px` },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [hasMore, more])

  if (error) return <Alert className="text-xs">{error}</Alert>

  if (loading && reports.length === 0) {
    return (
      <div className="flex flex-col gap-1.5 px-2 py-1">
        <Skeleton className="h-5 w-3/4" />
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-5 w-1/2" />
      </div>
    )
  }

  if (reports.length === 0) return <div className="px-2 py-1 text-sm text-fg-muted">{empty}</div>

  return (
    <div className="flex flex-col">
      {reports.map((report) => (
        <ReportRow
          key={report.slug}
          report={report}
          favorite={isFavorite(report.slug)}
          isAdmin={isAdmin}
          onNavigate={onNavigate}
          onRename={() => onEdit(report)}
          onDelete={() => onDelete(report)}
          onToggleFavorite={() => void toggleFavorite(report)}
        />
      ))}

      {hasMore && (
        <button
          ref={sentinel}
          type="button"
          onClick={more}
          className="cursor-pointer px-2 py-1.5 text-left text-xs text-fg-muted hover:text-fg"
        >
          {loading ? 'Загружаем…' : `Показать ещё (${total - reports.length})`}
        </button>
      )}
    </div>
  )
}
