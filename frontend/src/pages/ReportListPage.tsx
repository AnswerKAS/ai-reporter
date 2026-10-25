import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { ReportMeta } from '../types/report'
import { deleteReport } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useReportFacets, useReportPage, useReports } from '../lib/reports'
import { useDebounced } from '../lib/useDebounced'
import { facetItems, facetLabel, STATUS_LABELS } from '../components/reports/catalog'
import { ReportEditDialog } from '../components/reports/ReportEditDialog'
import { ReportRow } from '../components/reports/ReportRow'
import {
  Alert, Button, EmptyState, Input, Page, PageHeader, Segmented,
  Select, Skeleton, useConfirm,
} from '../components/ui'

const PAGE_SIZE = 30

/** Parse a user supplied page number without allowing invalid offsets. */
function pageNumber(value: string | null): number {
  const number = Number(value)
  return Number.isSafeInteger(number) && number > 0 ? Math.min(number, 10000) : 1
}

/** Searchable catalog that keeps only one compact page in the DOM. */
export function ReportListPage() {
  const { user, isAdmin } = useAuth()
  const { facets, isFavorite, toggleFavorite, reload, removeRecent } = useReports()
  const { confirm, dialog } = useConfirm()
  const [params, setParams] = useSearchParams()
  const [editing, setEditing] = useState<ReportMeta | null>(null)
  const query = params.get('q') ?? ''
  const search = useDebounced(query)
  const page = pageNumber(params.get('page'))
  const group = params.get('group') ?? ''
  const author = params.get('author') ?? ''
  const tag = params.get('tag') ?? ''
  const status = params.get('status') ?? ''
  const favorite = params.get('favorite') === '1'
  const sort = params.get('sort') === 'title' ? 'title' : 'updated'
  const scoped = useReportFacets(search)
  const choices = scoped ?? facets
  const { reports, total, loading, error } = useReportPage({
    q: search, group: group || undefined, author: author || undefined,
    tag: tag || undefined, status: status || undefined, favorite,
    sort, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE,
  })
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const pendingSearch = query.trim() !== search.trim()
  const activeFilters = [group, author, tag, status].filter(Boolean).length + Number(favorite)
  const [filtersOpen, setFiltersOpen] = useState(() => Boolean(group || author || tag || status))

  /** Update a URL filter and return to the first result page. */
  const update = (key: string, value: string, resetPage = true) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    if (resetPage) next.delete('page')
    setParams(next, { replace: true })
  }

  /** Clear selected filters while preserving the typed search and sort. */
  const clearFilters = () => {
    const next = new URLSearchParams(params)
    for (const key of ['group', 'author', 'tag', 'status', 'favorite', 'page']) next.delete(key)
    setParams(next, { replace: true })
  }

  /** Ask before removing a report and refresh the visible page. */
  const askDelete = (report: ReportMeta) => confirm({
    title: 'Удалить отчёт?',
    description: `Отчёт «${report.title}» будет удалён вместе с назначениями доступа. Действие необратимо.`,
    onConfirm: async () => {
      await deleteReport(report.slug)
      removeRecent(report.slug)
      await reload()
    },
  })

  useEffect(() => {
    if (!loading && total > 0 && page > pages) update('page', String(pages), false)
    // The completed page request is the only time an out-of-range page is corrected.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, total, page, pages])

  return (
    <Page>
      <PageHeader
        title="Библиотека отчётов"
        subtitle="Найдите нужный отчёт по словам названия, описания или темы."
        actions={<>
          <Link to="/workspace" className="inline-flex min-h-10 items-center rounded-control border border-line bg-surface px-4 text-sm font-medium text-fg hover:bg-accent-soft">Задать вопрос</Link>
          <Link to="/workspace?mode=report" className="inline-flex min-h-10 items-center rounded-control bg-accent px-4 text-sm font-semibold text-accent-fg hover:bg-accent-hover">Новый отчёт</Link>
        </>}
      />

      <section aria-label="Поиск и фильтры отчётов" className="mb-5 rounded-card border border-line bg-surface p-4 shadow-card">
        <Input
          type="search"
          value={query}
          onChange={(event) => update('q', event.target.value)}
          placeholder="Название, описание, тема или slug — слова в любом порядке"
          aria-label="Поиск по отчётам"
          className="w-full"
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button size="sm" variant={favorite ? 'default' : 'ghost'} aria-pressed={favorite}
            onClick={() => update('favorite', favorite ? '' : '1')}>
            ★ Закреплённые
          </Button>
          {user && <Button size="sm" variant={author === user.id ? 'default' : 'ghost'}
            aria-pressed={author === user.id} onClick={() => update('author', author === user.id ? '' : user.id)}>
            Мои отчёты
          </Button>}
          <Button size="sm" variant={filtersOpen || activeFilters > 0 ? 'default' : 'ghost'}
            aria-expanded={filtersOpen} aria-controls="catalog-advanced-filters"
            onClick={() => setFiltersOpen((open) => !open)}>
            Фильтры{activeFilters > 0 ? ` (${activeFilters})` : ''}
          </Button>
          {(activeFilters > 0 || query) && <Button size="sm" variant="ghost" onClick={() => {
            const next = new URLSearchParams(params)
            for (const key of ['q', 'group', 'author', 'tag', 'status', 'favorite', 'page']) next.delete(key)
            setParams(next, { replace: true })
          }}>Сбросить поиск</Button>}
        </div>

        <div id="catalog-advanced-filters" className={filtersOpen
          ? 'mt-3 grid gap-2 border-t border-line pt-3 sm:grid-cols-2 xl:grid-cols-4'
          : 'hidden'}>
          <label className="flex flex-col gap-1 text-xs text-fg-muted">
            Группа доступа
            <Select value={group} onChange={(event) => update('group', event.target.value)}>
              <option value="">Все группы</option>
              {facetItems(choices, 'group').map((item) => <option key={item.id} value={item.id}>{facetLabel(item, 'group')} ({item.count})</option>)}
            </Select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-fg-muted">
            Автор
            <Select value={author} onChange={(event) => update('author', event.target.value)}>
              <option value="">Все авторы</option>
              {facetItems(choices, 'author').map((item) => <option key={item.id} value={item.id}>{facetLabel(item, 'author')} ({item.count})</option>)}
            </Select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-fg-muted">
            Тема
            <Select value={tag} onChange={(event) => update('tag', event.target.value)}>
              <option value="">Все темы</option>
              {facetItems(choices, 'tag').map((item) => <option key={item.id} value={item.id}>{facetLabel(item, 'tag')} ({item.count})</option>)}
            </Select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-fg-muted">
            Статус
            <Select value={status} onChange={(event) => update('status', event.target.value)}>
              <option value="">Любой статус</option>
              {(choices?.statuses ?? []).map((item) => <option key={item.id} value={item.id}>{STATUS_LABELS[item.id] ?? item.id} ({item.count})</option>)}
            </Select>
          </label>
        </div>
        {filtersOpen && activeFilters > 0 && <Button size="sm" variant="ghost" className="mt-2" onClick={clearFilters}>Сбросить фильтры ({activeFilters})</Button>}
      </section>

      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-fg-muted" aria-live="polite">
          {loading || pendingSearch ? 'Ищем отчёты…' : `${total.toLocaleString('ru-RU')} отчётов · страница ${page} из ${pages}`}
        </div>
        <Segmented
          ariaLabel="Порядок отчётов"
          value={sort}
          onChange={(value) => update('sort', value)}
          options={[{ value: 'updated', label: 'Сначала свежие' }, { value: 'title', label: 'По названию' }]}
        />
      </div>

      {error ? <Alert>{error}</Alert> : loading || pendingSearch ? (
        <div className="space-y-2" aria-label="Загрузка отчётов">
          {Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-16 w-full" />)}
        </div>
      ) : reports.length === 0 ? (
        <EmptyState
          title="Отчёты не найдены"
          description="Попробуйте другие слова или сбросьте фильтры."
          action={<Button onClick={() => setParams(new URLSearchParams(), { replace: true })}>Сбросить поиск</Button>}
        />
      ) : (
        <>
          <section aria-label="Найденные отчёты" className="rounded-card border border-line bg-surface px-2">
            {reports.map((report) => <ReportRow
              key={report.slug}
              report={report}
              favorite={isFavorite(report.slug)}
              isAdmin={isAdmin}
              onRename={() => setEditing(report)}
              onDelete={() => askDelete(report)}
              onToggleFavorite={() => void toggleFavorite(report)}
              variant="catalog"
            />)}
          </section>
          {pages > 1 && <nav aria-label="Страницы каталога" className="mt-5 flex flex-wrap items-center justify-center gap-3">
            <Button disabled={page === 1} onClick={() => update('page', String(page - 1), false)}>← Назад</Button>
            <label className="flex items-center gap-2 text-sm text-fg-muted">
              Страница
              <Select aria-label="Номер страницы" value={String(page)} onChange={(event) => update('page', event.target.value, false)}>
                {Array.from({ length: pages }, (_, index) => <option key={index + 1} value={index + 1}>{index + 1}</option>)}
              </Select>
              из {pages}
            </label>
            <Button disabled={page >= pages} onClick={() => update('page', String(page + 1), false)}>Далее →</Button>
          </nav>}
        </>
      )}

      {editing && <ReportEditDialog report={editing} onClose={() => setEditing(null)} />}
      {dialog}
    </Page>
  )
}
