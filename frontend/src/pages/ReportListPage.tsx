import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { ReportMeta } from '../types/report'
import { useAuth } from '../lib/auth'
import { useReports, useReportSearch } from '../lib/reports'
import { useDebounced } from '../lib/useDebounced'
import { cn } from '../lib/cn'
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Page,
  PageHeader,
  Segmented,
  SkeletonCards,
} from '../components/ui'

/** Плитка не бесконечная: карточки крупные, и сотня их — это уже прокрутка
    в несколько экранов. Дальше — «показать ещё». */
const PAGE = 48

export function ReportCard({ report }: { report: ReportMeta }) {
  const { isFavorite, toggleFavorite } = useReports()
  const pinned = isFavorite(report.slug)

  return (
    <Card interactive className="relative p-0">
      <button
        type="button"
        aria-label={pinned ? `Открепить «${report.title}»` : `Закрепить «${report.title}»`}
        aria-pressed={pinned}
        title={pinned ? 'Открепить' : 'Закрепить'}
        onClick={() => void toggleFavorite(report)}
        className={cn(
          'absolute top-3 right-3 z-10 cursor-pointer rounded-control px-1.5 py-0.5 transition-colors',
          pinned ? 'text-warn' : 'text-fg-muted hover:text-fg',
        )}
      >
        <span aria-hidden="true">{pinned ? '★' : '☆'}</span>
      </button>

      <Link to={`/reports/${report.slug}`} className="block p-5 pr-10">
        <h3 className="mb-1.5 text-[17px] font-semibold text-fg">{report.title}</h3>
        {report.description && <p className="mb-3.5 text-sm text-fg-muted">{report.description}</p>}
        {report.tags && report.tags.length > 0 && (
          <p className="mb-2 flex flex-wrap gap-1">
            {report.tags.map((tag) => (
              <Badge key={tag}>{tag}</Badge>
            ))}
          </p>
        )}
        {report.status === 'ready' ? (
          <span className="text-sm text-fg-muted">
            Обновлён: {report.updatedAt}
            {report.author && ` · ${report.author}`}
          </span>
        ) : report.status === 'error' ? (
          <Badge tone="bad">Ошибка: {report.error}</Badge>
        ) : (
          <Badge tone="warn">Сборка… ({report.status})</Badge>
        )}
      </Link>
    </Card>
  )
}

export function ReportGrid({ reports }: { reports: ReportMeta[] }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4">
      {reports.map((r) => (
        <ReportCard key={r.slug} report={r} />
      ))}
    </div>
  )
}

/**
 * Каталог отчётов плиткой: поиск и порядок считает сервер, страница
 * догружается по кнопке. Весь список сюда не приезжает — на десяти тысячах
 * отчётов это мегабайты ради первого экрана.
 */
export function ReportListPage() {
  const { user, isAdmin } = useAuth()
  const { facets } = useReports()
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<'updated' | 'title'>('updated')
  const search = useDebounced(query)
  const { reports, total, loading, error, hasMore, loadMore } = useReportSearch({
    q: search,
    sort,
    limit: PAGE,
  })

  const newReport = isAdmin ? (
    <Link
      to="/builder"
      className="inline-flex items-center rounded-control border border-accent bg-accent px-3.5 py-1.5 text-sm font-semibold text-accent-fg transition-colors hover:bg-accent-hover"
    >
      Новый отчёт
    </Link>
  ) : undefined

  const header = (
    <PageHeader
      title="Отчёты"
      subtitle={user ? `Доступны пользователю ${user.username}` : undefined}
      actions={newReport}
    >
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Input
          className="w-auto min-w-56 flex-1 py-1.5"
          type="search"
          placeholder="Поиск по названию, описанию, slug'у или теме"
          aria-label="Поиск по отчётам"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Segmented
          ariaLabel="Порядок отчётов"
          value={sort}
          onChange={setSort}
          options={[
            { value: 'updated', label: 'Сначала свежие' },
            { value: 'title', label: 'По названию' },
          ]}
        />
        <span className="text-sm text-fg-muted tabular-nums">
          {search.trim() ? `Найдено: ${total}` : `Всего: ${facets?.total ?? total}`}
        </span>
      </div>
    </PageHeader>
  )

  if (error) {
    return (
      <Page>
        {header}
        <Alert>{error}</Alert>
      </Page>
    )
  }

  if (loading && reports.length === 0) {
    return (
      <Page>
        {header}
        <SkeletonCards />
      </Page>
    )
  }

  return (
    <Page>
      {header}

      {reports.length === 0 ? (
        search.trim() ? (
          <EmptyState title="Ничего не нашлось" description={`По запросу «${search}» отчётов нет.`} />
        ) : (
          <EmptyState
            title="Пока нет доступных отчётов"
            description="Отчёты назначает администратор — обратитесь к нему или соберите свой в конструкторе."
            action={newReport}
          />
        )
      ) : (
        <>
          <ReportGrid reports={reports} />
          {hasMore && (
            <div className="mt-4 flex justify-center">
              <Button onClick={loadMore} disabled={loading}>
                {loading ? 'Загружаем…' : `Показать ещё (${total - reports.length})`}
              </Button>
            </div>
          )}
        </>
      )}
    </Page>
  )
}
