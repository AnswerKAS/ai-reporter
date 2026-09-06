import { useState } from 'react'
import type { ReportDimension, ReportMeta, ReportQuery } from '../../types/report'
import { useReportFacets } from '../../lib/reports'
import { cn } from '../../lib/cn'
import { facetItems, facetLabel } from './catalog'
import { Skeleton } from '../ui'
import { ReportList } from './ReportList'

/** Страница внутри группы меньше корневой: группу раскрывают, чтобы посмотреть,
    что в ней, а не чтобы прокрутить её до конца. */
const GROUP_PAGE = 50

/**
 * Отчёты по группам выбранного разреза.
 *
 * Заголовки со счётчиками приходят из фасетов одним запросом, а строки группы
 * — обычной постраничной выдачей при раскрытии. Иначе группировку пришлось бы
 * отдавать одной выдачей с размноженными строками: отчёт лежит в трёх группах
 * и приезжал бы трижды, а `total` переставал означать «отчётов».
 */
export function ReportGroups({
  dimension,
  base,
  onNavigate,
  onEdit,
  onDelete,
}: {
  dimension: ReportDimension
  base: ReportQuery
  onNavigate?: () => void
  onEdit: (report: ReportMeta) => void
  onDelete: (report: ReportMeta) => void
}) {
  const facets = useReportFacets(base.q ?? '')
  const [open, setOpen] = useState<string[]>([])
  const items = facetItems(facets, dimension)

  if (!facets) {
    return (
      <div className="flex flex-col gap-1.5 px-2 py-1">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-5 w-1/2" />
      </div>
    )
  }
  if (items.length === 0) return <p className="px-2 py-1 text-sm text-fg-muted">Ничего не найдено</p>

  return (
    <div className="flex flex-col">
      {items.map((item) => {
        const expanded = open.includes(item.id)
        return (
          <div key={item.id}>
            <button
              type="button"
              aria-expanded={expanded}
              onClick={() =>
                setOpen((prev) =>
                  prev.includes(item.id) ? prev.filter((id) => id !== item.id) : [...prev, item.id],
                )
              }
              className={cn(
                'flex w-full cursor-pointer items-center gap-1.5 rounded-control px-2 py-1.5',
                'text-left text-sm text-fg transition-colors hover:bg-bg',
              )}
            >
              <span aria-hidden="true" className="w-2 shrink-0 text-xs text-fg-muted">
                {expanded ? '▾' : '▸'}
              </span>
              <span className={cn('min-w-0 flex-1 truncate', item.name ? '' : 'text-fg-muted italic')}>
                {facetLabel(item, dimension)}
              </span>
              <span className="shrink-0 text-xs tabular-nums text-fg-muted">{item.count}</span>
            </button>

            {expanded && (
              <div className="ml-2 border-l border-line pl-1">
                <ReportList
                  query={{ ...base, [dimension]: item.id, limit: GROUP_PAGE }}
                  onNavigate={onNavigate}
                  onEdit={onEdit}
                  onDelete={onDelete}
                  empty="Ничего не найдено"
                />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
