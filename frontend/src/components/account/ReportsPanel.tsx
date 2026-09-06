import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useReports, useReportSearch } from '../../lib/reports'
import { useDebounced } from '../../lib/useDebounced'
import { Alert, Badge, Button, EmptyState, Input, Panel, PanelRow, Segmented } from '../ui'

type Order = 'updated' | 'title'

/** Страница списка в кабинете: строки компактные, полсотни хватает на экран
    с запасом, дальше — «показать ещё». */
const PAGE = 50

/**
 * Отчёты, доступные человеку: поиск, порядок и что с отчётом можно сделать
 * прямо отсюда. Раньше здесь был список ссылок без порядка — на трёх десятках
 * отчётов найти нужный было быстрее в дереве слева, и кабинет не нужен.
 *
 * Поиск и порядок считает сервер, тем же каталогом, что и меню слева: держать
 * весь список отчётов в памяти ради кабинета больше нельзя.
 */
export function ReportsPanel({
  scheduleCounts,
  isAdmin,
  onSchedule,
}: {
  /** Сколько рассылок человек настроил на отчёте; null — свод ещё едет. */
  scheduleCounts: Record<string, number> | null
  isAdmin: boolean
  onSchedule: (slug: string) => void
}) {
  const { facets } = useReports()
  const [query, setQuery] = useState('')
  const [order, setOrder] = useState<Order>('updated')
  const search = useDebounced(query)
  const { reports: shown, total, loading, error, hasMore, loadMore } = useReportSearch({
    q: search,
    sort: order,
    limit: PAGE,
  })

  return (
    <Panel
      title="Мои отчёты"
      count={facets?.total ?? total}
      description="Всё, что вам назначено — лично или через группу."
      toolbar={
        <>
          <Input
            className="w-auto min-w-56 flex-1 py-1.5"
            type="search"
            placeholder="Поиск по названию, описанию или slug'у"
            aria-label="Поиск по отчётам"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <Segmented
            ariaLabel="Порядок отчётов"
            value={order}
            onChange={setOrder}
            options={[
              { value: 'updated', label: 'Сначала свежие' },
              { value: 'title', label: 'По названию' },
            ]}
          />
        </>
      }
    >
      {error ? (
        <Alert>{error}</Alert>
      ) : shown.length === 0 ? (
        search.trim() ? (
          <EmptyState title="Ничего не нашлось" description={`По запросу «${search}» отчётов нет.`} />
        ) : (
          <EmptyState
            title="Отчёты не назначены"
            description="Доступ к отчёту даёт администратор — или соберите свой в конструкторе."
          />
        )
      ) : (
        <ul className="flex flex-col gap-2">
          {shown.map((r) => {
            const schedules = scheduleCounts?.[r.slug] ?? 0
            return (
              <li key={r.slug}>
                <PanelRow className="flex-col items-stretch gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link to={`/reports/${r.slug}`} className="font-semibold text-accent hover:underline">
                      {r.title}
                    </Link>
                    {r.status === 'error' ? (
                      <Badge tone="bad">ошибка: {r.error}</Badge>
                    ) : r.status && r.status !== 'ready' ? (
                      <Badge tone="warn">{r.status}</Badge>
                    ) : null}
                    {schedules > 0 && (
                      <Badge tone="accent">
                        {schedules === 1 ? 'рассылка' : `рассылок: ${schedules}`}
                      </Badge>
                    )}
                    <span className="ml-auto flex flex-wrap gap-1">
                      <Button size="sm" variant="ghost" onClick={() => onSchedule(r.slug)}>
                        Рассылка
                      </Button>
                      {isAdmin && (
                        <Link
                          to={`/builder/${r.slug}`}
                          className="inline-flex items-center rounded-control border border-transparent px-2.5 py-1 text-xs text-fg-muted transition-colors hover:bg-surface-sunken hover:text-fg"
                        >
                          Править
                        </Link>
                      )}
                    </span>
                  </div>
                  <p className="text-xs text-fg-muted">
                    {r.description ? `${r.description} · ` : ''}
                    {r.slug}
                    {r.updatedAt && ` · обновлён ${r.updatedAt}`}
                  </p>
                </PanelRow>
              </li>
            )
          })}
        </ul>
      )}

      {hasMore && (
        <div className="mt-3 flex justify-center">
          <Button onClick={loadMore} disabled={loading}>
            {loading ? 'Загружаем…' : `Показать ещё (${total - shown.length})`}
          </Button>
        </div>
      )}
    </Panel>
  )
}
