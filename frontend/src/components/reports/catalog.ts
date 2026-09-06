import type { FacetItem, ReportDimension, ReportFacets, ReportQuery } from '../../types/report'

/** Чем меню делит отчёты на группы; `none` — плоский список. */
export type GroupBy = 'none' | ReportDimension

export interface CatalogState {
  group: string
  author: string
  tag: string
  status: string
  favorite: boolean
  sort: 'title' | 'updated'
  groupBy: GroupBy
}

export const EMPTY_CATALOG: CatalogState = {
  group: '', author: '', tag: '', status: '',
  favorite: false, sort: 'title', groupBy: 'none',
}

const KEY = 'ai-reporter-catalog'

/** Фильтры и группировка живут у читателя в браузере: разбор на десяти
    тысячах отчётов длиннее одной сессии, и сбрасывать его на перезагрузке
    страницы — значит начинать его заново. Строка поиска сюда не идёт: она
    меняется на каждый символ и остаётся черновиком экрана. */
export function readCatalog(): CatalogState {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? '{}') as Partial<CatalogState>
    return { ...EMPTY_CATALOG, ...saved }
  } catch {
    return EMPTY_CATALOG // приватное окно или мусор в хранилище
  }
}

export function writeCatalog(state: CatalogState): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(state))
  } catch {
    // хранилище недоступно — разбор просто не переживёт перезагрузку
  }
}

/** Сколько фильтров сейчас сужают выдачу — число на кнопке «Фильтры». */
export function activeFilters(state: CatalogState): number {
  return [state.group, state.author, state.tag, state.status].filter(Boolean).length +
    (state.favorite ? 1 : 0)
}

/** Условия каталога для запроса; поиск приходит отдельно — он черновик. */
export function toQuery(state: CatalogState, q: string): ReportQuery {
  return {
    q,
    group: state.group || undefined,
    author: state.author || undefined,
    tag: state.tag || undefined,
    status: state.status || undefined,
    favorite: state.favorite || undefined,
    sort: state.sort,
  }
}

export const DIMENSIONS: Record<ReportDimension, { title: string; empty: string; by: string }> = {
  group: { title: 'Группа доступа', empty: 'Без группы', by: 'По группе доступа' },
  author: { title: 'Автор', empty: 'Без автора', by: 'По автору' },
  tag: { title: 'Тема', empty: 'Без темы', by: 'По теме' },
}

export function facetItems(facets: ReportFacets | null, dimension: ReportDimension): FacetItem[] {
  if (!facets) return []
  return dimension === 'group' ? facets.groups : dimension === 'author' ? facets.authors : facets.tags
}

/** Имя варианта разреза; у ведра «ни одной» имени нет — оно у разреза. */
export function facetLabel(item: FacetItem, dimension: ReportDimension): string {
  return item.name ?? DIMENSIONS[dimension].empty
}

export const STATUS_LABELS: Record<string, string> = {
  ready: 'Готов',
  error: 'Ошибка',
}
