import type { ReportDimension, ReportFacets } from '../../types/report'
import { Button, Chips, Input, Select } from '../ui'
import {
  DIMENSIONS,
  EMPTY_CATALOG,
  STATUS_LABELS,
  activeFilters,
  facetItems,
  facetLabel,
  type CatalogState,
  type GroupBy,
} from './catalog'

const DIMENSION_KEYS: ReportDimension[] = ['group', 'author', 'tag']

/**
 * Полоса управления каталогом: поиск, фильтры со счётчиками и группировка.
 *
 * Фильтры сложены под кнопку, а не разложены полосой, как на странице
 * датасетов: меню бывает шириной в двести пикселей, и пять контролов подряд
 * не оставили бы в нём места самим отчётам. Число на кнопке говорит, что
 * выдача сужена, даже когда панель закрыта.
 *
 * Разрезы — селекты, а не `Chips`: групп и тем бывают сотни, и все варианты
 * сразу здесь не показать. Счётчик у варианта равен тому, что даст его выбор.
 */
export function CatalogControls({
  state,
  onChange,
  query,
  onQuery,
  facets,
  open,
  onOpen,
}: {
  state: CatalogState
  onChange: (next: CatalogState) => void
  query: string
  onQuery: (value: string) => void
  facets: ReportFacets | null
  open: boolean
  onOpen: (open: boolean) => void
}) {
  const active = activeFilters(state)
  const statuses = facets?.statuses ?? []

  return (
    <div className="mb-2 flex flex-col gap-1.5">
      <Input
        type="search"
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        placeholder="Поиск отчёта"
        aria-label="Поиск отчёта"
      />

      <div className="flex items-center gap-1.5">
        <Button
          size="sm"
          variant={open ? 'default' : 'ghost'}
          aria-expanded={open}
          onClick={() => onOpen(!open)}
          className="flex-1"
        >
          Фильтры{active > 0 && <span className="tabular-nums">({active})</span>}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          aria-label="Порядок отчётов"
          title={state.sort === 'title' ? 'По названию' : 'Сначала свежие'}
          onClick={() => onChange({ ...state, sort: state.sort === 'title' ? 'updated' : 'title' })}
        >
          {state.sort === 'title' ? 'А–Я' : 'Свежие'}
        </Button>
      </div>

      {open && (
        <div className="flex flex-col gap-2 rounded-card border border-line bg-bg p-2">
          <Chips
            ariaLabel="Быстрые фильтры"
            className="w-full"
            values={state.favorite ? ['favorite'] : []}
            options={[{ value: 'favorite', label: '★ Закреплённые', count: facets?.favorites }]}
            onToggle={() => onChange({ ...state, favorite: !state.favorite })}
          />

          {DIMENSION_KEYS.map((key) => {
            const items = facetItems(facets, key)
            return (
              <label key={key} className="flex flex-col gap-1 text-xs text-fg-muted">
                <span>{DIMENSIONS[key].title}</span>
                <Select
                  value={state[key]}
                  onChange={(e) => onChange({ ...state, [key]: e.target.value })}
                  className="py-1.5"
                >
                  <option value="">Все</option>
                  {items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {facetLabel(item, key)} ({item.count})
                    </option>
                  ))}
                </Select>
              </label>
            )
          })}

          <label className="flex flex-col gap-1 text-xs text-fg-muted">
            <span>Статус</span>
            <Select
              value={state.status}
              onChange={(e) => onChange({ ...state, status: e.target.value })}
              className="py-1.5"
            >
              <option value="">Любой</option>
              {statuses.map((item) => (
                <option key={item.id} value={item.id}>
                  {STATUS_LABELS[item.id] ?? item.id} ({item.count})
                </option>
              ))}
            </Select>
          </label>

          <label className="flex flex-col gap-1 text-xs text-fg-muted">
            <span>Группировать</span>
            <Select
              value={state.groupBy}
              onChange={(e) => onChange({ ...state, groupBy: e.target.value as GroupBy })}
              className="py-1.5"
            >
              <option value="none">Без группировки</option>
              {DIMENSION_KEYS.map((key) => (
                <option key={key} value={key}>
                  {DIMENSIONS[key].by}
                </option>
              ))}
            </Select>
          </label>

          {(active > 0 || state.groupBy !== 'none') && (
            <Button size="sm" variant="ghost" onClick={() => onChange({ ...EMPTY_CATALOG, sort: state.sort })}>
              Сбросить
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
