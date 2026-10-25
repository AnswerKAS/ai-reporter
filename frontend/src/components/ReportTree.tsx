import { useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import type { ReportDimension, ReportMeta } from '../types/report'
import { deleteReport } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useReportFacets, useReports } from '../lib/reports'
import { useDebounced } from '../lib/useDebounced'
import { cn } from '../lib/cn'
import { Alert, useConfirm } from './ui'
import { CatalogControls } from './reports/CatalogControls'
import { ReportEditDialog } from './reports/ReportEditDialog'
import { ReportGroups } from './reports/ReportGroups'
import { ReportList } from './reports/ReportList'
import { ReportRow } from './reports/ReportRow'
import { activeFilters, readCatalog, toQuery, writeCatalog, type CatalogState } from './reports/catalog'

/** Свёрнутый блок меню: заголовок со счётчиком и содержимое. */
function Section({
  title,
  count,
  open,
  onToggle,
  children,
}: {
  title: string
  count: number
  open: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <section className="mb-5">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex min-h-9 w-full cursor-pointer items-center gap-2 rounded-control px-2 text-left text-xs font-semibold tracking-[0.1em] text-fg-muted uppercase hover:bg-surface-sunken hover:text-fg"
      >
        <span aria-hidden="true" className="w-3 shrink-0 text-sm">
          {open ? '▾' : '▸'}
        </span>
        <span className="min-w-0 flex-1 truncate">{title}</span>
        <span className="shrink-0 rounded-control bg-surface-sunken px-2 py-0.5 text-[11px] font-medium tracking-normal tabular-nums text-fg-muted">{count}</span>
      </button>
      {open && <div className="mt-1">{children}</div>}
    </section>
  )
}

/**
 * Меню отчётов: навигатор по каталогу.
 *
 * Список отчётов сюда не выгружается — сервер отдаёт страницу под текущий
 * поиск и фильтры, а меню догружает следующую по мере прокрутки. Наверху то,
 * ради чего человек обычно и открывает меню: закреплённое и недавнее; они
 * прячутся, как только он начинает искать — иначе повторяли бы выдачу.
 *
 * Создание, переименование и удаление живут здесь же: раньше отчётами
 * управляли с трёх разных экранов.
 */
export function ReportTree({ className, onNavigate }: { className?: string; onNavigate?: () => void }) {
  const { facets, favorites, recent, error, reload, isFavorite, toggleFavorite, removeRecent } = useReports()
  const { isAdmin } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const { confirm, dialog } = useConfirm()

  const [state, setState] = useState<CatalogState>(readCatalog)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [pinnedOpen, setPinnedOpen] = useState(true)
  const [recentOpen, setRecentOpen] = useState(true)
  const [editing, setEditing] = useState<ReportMeta | null>(null)

  const search = useDebounced(query)
  const scoped = useReportFacets(search)
  const total = facets?.total ?? 0
  // пока человек ищет или сузил выдачу фильтрами, блоки сверху молчат:
  // закреплённое и недавнее к его вопросу отношения не имеют
  const narrowed = search.trim() !== '' || activeFilters(state) > 0
  // заголовки групп берутся из фасетов, и без них группировать нечем. Но сам
  // список живёт своим запросом и работает — показываем его плоским, а не
  // пустое меню: упавший вспомогательный запрос не должен прятать отчёты
  const grouped = state.groupBy !== 'none' && !error

  const update = (next: CatalogState) => {
    setState(next)
    writeCatalog(next)
  }

  const activeSlug = decodeURIComponent(location.pathname).match(/^\/(?:reports|workspace)\/(.+)$/)?.[1]

  const askDelete = (report: ReportMeta) =>
    confirm({
      title: 'Удалить отчёт?',
      description: `Отчёт «${report.title}» будет удалён вместе с назначениями доступа. Действие необратимо.`,
      onConfirm: async () => {
        await deleteReport(report.slug)
        removeRecent(report.slug)
        await reload()
        if (report.slug === activeSlug) navigate('/reports')
      },
    })

  return (
    <nav aria-label="Отчёты" className={cn('min-w-0', className)}>
      <div className={cn('z-20 border-b border-line bg-surface px-3 pb-4 pt-5', !filtersOpen && 'xl:sticky xl:top-0')}>
        <div className="mb-4 flex items-start justify-between gap-2 px-1">
          <div className="min-w-0">
            <NavLink to="/reports" onClick={onNavigate} className="text-lg font-semibold tracking-tight text-fg hover:text-accent">
              Отчёты
            </NavLink>
            <p className="text-xs text-fg-muted tabular-nums">Доступно: {total}</p>
          </div>
          <NavLink
            to="/workspace?mode=report"
            onClick={onNavigate}
            aria-label="Создать отчёт"
            title="Создать отчёт"
            className="flex size-10 shrink-0 items-center justify-center rounded-control bg-accent text-xl leading-none text-accent-fg shadow-card transition-colors hover:bg-accent-hover"
          >
            <span aria-hidden="true">＋</span>
          </NavLink>
        </div>

        <CatalogControls
          state={state}
          onChange={update}
          query={query}
          onQuery={setQuery}
          facets={scoped ?? facets}
          open={filtersOpen}
          onOpen={setFiltersOpen}
        />
      </div>
      <div className="px-3 pb-5 pt-4">
      {error && <Alert className="mb-3 text-xs">{error}</Alert>}

      {!narrowed && favorites.length > 0 && (
        <Section
          title="Закреплённые"
          count={favorites.length}
          open={pinnedOpen}
          onToggle={() => setPinnedOpen((v) => !v)}
        >
          {favorites.map((report) => (
            <ReportRow
              key={report.slug}
              report={report}
              favorite
              isAdmin={isAdmin}
              onNavigate={onNavigate}
              onRename={() => setEditing(report)}
              onDelete={() => askDelete(report)}
              onToggleFavorite={() => void toggleFavorite(report)}
            />
          ))}
        </Section>
      )}

      {!narrowed && recent.length > 0 && (
        <Section
          title="Недавние"
          count={recent.length}
          open={recentOpen}
          onToggle={() => setRecentOpen((v) => !v)}
        >
          {recent.map((item) => (
            <NavLink
              key={item.slug}
              to={`/reports/${item.slug}`}
              onClick={onNavigate}
              title={item.title}
              className={({ isActive }) =>
                cn(
                  'flex min-h-9 items-center gap-2 rounded-control px-3 py-1.5 text-sm transition-colors',
                  isActive ? 'bg-accent-soft font-semibold text-accent' : 'text-fg hover:bg-surface-sunken',
                )
              }
            >
              <span className="min-w-0 whitespace-normal break-words">{item.title}</span>
              {isFavorite(item.slug) && (
                <span aria-hidden="true" className="shrink-0 text-xs text-warn">
                  ★
                </span>
              )}
            </NavLink>
          ))}
        </Section>
      )}

      <div className="mb-2 flex items-center justify-between gap-2 border-t border-line px-2 pt-4 text-xs font-semibold tracking-[0.1em] text-fg-muted uppercase">
        <span>{narrowed ? 'Результаты' : 'Все отчёты'}</span>
        {activeFilters(state) === 0 && <span className="rounded-control bg-surface-sunken px-2 py-0.5 text-[11px] font-medium tracking-normal tabular-nums">{narrowed ? (scoped?.total ?? total) : total}</span>}
      </div>

      {grouped ? (
        <ReportGroups
          dimension={state.groupBy as ReportDimension}
          base={toQuery(state, search)}
          onNavigate={onNavigate}
          onEdit={setEditing}
          onDelete={askDelete}
        />
      ) : (
        <ReportList
          query={toQuery(state, search)}
          onNavigate={onNavigate}
          onEdit={setEditing}
          onDelete={askDelete}
          empty={
            narrowed ? (
              'Ничего не найдено'
            ) : (
              <>
                Отчётов пока нет.{' '}
                <NavLink to="/workspace?mode=report" onClick={onNavigate} className="text-accent hover:underline">
                  Собрать первый
                </NavLink>
              </>
            )
          }
        />
      )}

      {editing && <ReportEditDialog report={editing} onClose={() => setEditing(null)} />}
      {dialog}
      </div>
    </nav>
  )
}
