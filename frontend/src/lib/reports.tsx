import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import type { ReportFacets, ReportMeta, ReportQuery } from '../types/report'
import { ApiError, fetchReportFacets, searchReports, setReportFavorite } from './api'
import { useAuth } from './auth'

/** Пока отчёт собирается, выдача сама себя обновляет — статус в меню живой. */
const PENDING_INTERVAL_MS = 15000

/** Страница каталога. Список из десяти тысяч отчётов на клиент не выгружается. */
export const PAGE_SIZE = 100

/** Закреплённых у человека единицы; сотня — потолок на всякий случай. */
const FAVORITES_LIMIT = 100

const RECENT_KEY = 'ai-reporter-recent-reports'
const RECENT_MAX = 8

/** Недавно открытый отчёт: название хранится рядом со slug'ом, чтобы блок
    «Недавние» рисовался сразу, не дожидаясь запроса за его строкой. */
export interface RecentReport {
  slug: string
  title: string
}

function readRecent(): RecentReport[] {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]') as unknown
    if (!Array.isArray(raw)) return []
    return raw
      .filter((item): item is RecentReport =>
        typeof item === 'object' && item !== null &&
        typeof (item as RecentReport).slug === 'string' &&
        typeof (item as RecentReport).title === 'string',
      )
      .slice(0, RECENT_MAX)
  } catch {
    return [] // приватное окно или мусор в хранилище — просто пусто
  }
}

interface ReportsContextValue {
  /** Разрезы каталога со счётчиками; null — ещё едут. */
  facets: ReportFacets | null
  /** Закреплённые отчёты читателя, свежее закрепление сверху. */
  favorites: ReportMeta[]
  /** Недавно открытые отчёты этого браузера. */
  recent: RecentReport[]
  loading: boolean
  error: string | null
  /**
   * Номер версии каталога. Постраничные выдачи перечитываются, когда он
   * растёт: держать где-то один общий список отчётов больше нельзя, а
   * узнавать об удалении соседнего экрана по-прежнему надо.
   */
  version: number
  /** Перечитать каталог: звать после создания, правки и удаления отчёта. */
  reload: () => Promise<void>
  isFavorite: (slug: string) => boolean
  toggleFavorite: (report: ReportMeta) => Promise<void>
  /** Отметить отчёт открытым — попадёт в «недавние». */
  markVisited: (report: { slug: string; title: string }) => void
}

const ReportsContext = createContext<ReportsContextValue | null>(null)

/**
 * Каталог отчётов на всё приложение: фасеты, закреплённое и недавнее.
 *
 * Раньше здесь лежал весь список отчётов, и им жили и меню, и страницы. На
 * десяти тысячах отчётов такой список — мегабайты на каждой загрузке страницы,
 * поэтому выдачу теперь запрашивают постранично (`useReportSearch`), а общим
 * остаётся только то, что мало и нужно всем сразу.
 */
export function ReportsProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [facets, setFacets] = useState<ReportFacets | null>(null)
  const [favorites, setFavorites] = useState<ReportMeta[]>([])
  const [recent, setRecent] = useState<RecentReport[]>(readRecent)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState(0)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const refresh = useCallback(async () => {
    if (!user) {
      setFacets(null)
      setFavorites([])
      return
    }
    try {
      const [next, pinned] = await Promise.all([
        fetchReportFacets(),
        searchReports({ favorite: true, limit: FAVORITES_LIMIT, sort: 'title' }),
      ])
      if (!alive.current) return
      setFacets(next)
      setFavorites(pinned.reports)
      setError(null)
    } catch (err) {
      if (!alive.current) return
      // сюда приходит ошибка фасетов и закреплённого, а не самого списка —
      // он живёт своим запросом и работает. Говорим, что именно отвалилось:
      // текст API («отчёт не найден» от старого бэкенда без /facets) сам по
      // себе объясняет ровно ничего
      const detail = err instanceof ApiError ? err.message : 'API недоступен'
      setError(`фильтры и группировка недоступны: ${detail}`)
    }
  }, [user])

  /** Перечитать каталог и подтолкнуть все открытые выдачи. */
  const reload = useCallback(async () => {
    await refresh()
    if (alive.current) setVersion((n) => n + 1)
  }, [refresh])

  useEffect(() => {
    if (!user) {
      setFacets(null)
      setFavorites([])
      setError(null)
      setLoading(false)
      return
    }
    setLoading(true)
    refresh().finally(() => {
      if (alive.current) setLoading(false)
    })
  }, [user, refresh])

  const isFavorite = useCallback(
    (slug: string) => favorites.some((r) => r.slug === slug),
    [favorites],
  )

  const toggleFavorite = useCallback(
    async (report: ReportMeta) => {
      const on = !favorites.some((r) => r.slug === report.slug)
      // список меняем сразу: звёздочка не должна ждать ответа сервера
      setFavorites((prev) =>
        on
          ? [{ ...report, favorite: true }, ...prev.filter((r) => r.slug !== report.slug)]
          : prev.filter((r) => r.slug !== report.slug),
      )
      try {
        await setReportFavorite(report.slug, on)
        await refresh()
      } catch (err) {
        if (!alive.current) return
        setError(err instanceof ApiError ? err.message : 'не удалось закрепить отчёт')
        await refresh() // вернуть список к тому, что на сервере
      }
    },
    [favorites, refresh],
  )

  const markVisited = useCallback((report: { slug: string; title: string }) => {
    setRecent((prev) => {
      const next = [
        { slug: report.slug, title: report.title },
        ...prev.filter((r) => r.slug !== report.slug),
      ].slice(0, RECENT_MAX)
      try {
        localStorage.setItem(RECENT_KEY, JSON.stringify(next))
      } catch {
        // хранилище недоступно — недавние просто не переживут перезагрузку
      }
      return next
    })
  }, [])

  const value = useMemo(
    () => ({
      facets, favorites, recent, loading, error, version,
      reload, isFavorite, toggleFavorite, markVisited,
    }),
    [facets, favorites, recent, loading, error, version, reload, isFavorite, toggleFavorite, markVisited],
  )

  return <ReportsContext.Provider value={value}>{children}</ReportsContext.Provider>
}

export function useReports(): ReportsContextValue {
  const ctx = useContext(ReportsContext)
  if (!ctx) throw new Error('useReports вне ReportsProvider')
  return ctx
}

/**
 * Фасеты под текущий поиск.
 *
 * Общие фасеты в контексте посчитаны без поиска — они отвечают на вопрос
 * «что вообще есть в каталоге». Заголовкам групп нужен другой ответ: сколько
 * найденного лежит в каждой, иначе счётчик у группы врёт, а сама группа
 * раскрывается пустой.
 */
export function useReportFacets(q: string): ReportFacets | null {
  const { facets, version } = useReports()
  const [scoped, setScoped] = useState<ReportFacets | null>(null)
  const needle = q.trim()

  useEffect(() => {
    if (!needle) {
      setScoped(null)
      return
    }
    let alive = true
    fetchReportFacets(needle)
      .then((next) => {
        if (alive) setScoped(next)
      })
      .catch(() => {
        if (alive) setScoped(null)
      })
    return () => {
      alive = false
    }
  }, [needle, version])

  return needle ? scoped : facets
}


function isPending(report: ReportMeta): boolean {
  return report.status !== undefined && report.status !== 'ready' && report.status !== 'error'
}

export interface ReportSearch {
  reports: ReportMeta[]
  /** Сколько отчётов подходит под запрос — не сколько уже загружено. */
  total: number
  loading: boolean
  error: string | null
  hasMore: boolean
  loadMore: () => void
}

/**
 * Постраничная выдача каталога: поиск и фильтры считает сервер.
 *
 * Запрос со сменившимися условиями начинает выдачу заново, `loadMore()`
 * дописывает следующую страницу. Ответ на устаревший запрос выбрасывается:
 * при быстром наборе в поиске первый ответ приходит после второго и иначе
 * затирал бы его.
 */
export function useReportSearch(query: ReportQuery): ReportSearch {
  const { version } = useReports()
  const limit = query.limit ?? PAGE_SIZE
  const key = useMemo(
    () =>
      JSON.stringify([
        query.q?.trim() ?? '', query.group ?? '', query.author ?? '', query.tag ?? '',
        query.status ?? '', Boolean(query.favorite), query.sort ?? 'title', limit,
      ]),
    [query.q, query.group, query.author, query.tag, query.status, query.favorite, query.sort, limit],
  )

  const [reports, setReports] = useState<ReportMeta[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // условия запроса — в ref: они меняются на каждый рендер объектом, а
  // перезапускать загрузку надо только когда меняется их содержимое (key)
  const latest = useRef(query)
  latest.current = query
  const stamp = useRef(0)

  const load = useCallback(
    async (offset: number, size = limit) => {
      const mine = ++stamp.current
      setLoading(true)
      try {
        const page = await searchReports({ ...latest.current, limit: size, offset })
        if (mine !== stamp.current) return
        setReports((prev) => (offset === 0 ? page.reports : [...prev, ...page.reports]))
        setTotal(page.total)
        setError(null)
      } catch (err) {
        if (mine !== stamp.current) return
        setError(err instanceof ApiError ? err.message : 'API недоступен')
      } finally {
        if (mine === stamp.current) setLoading(false)
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key, limit],
  )

  useEffect(() => {
    setReports([])
    void load(0)
  }, [load, version])

  const shown = reports.length
  const pending = reports.some(isPending)
  useEffect(() => {
    if (!pending) return
    // перечитываем ровно то, что уже загружено, а не первую страницу:
    // иначе обновление статуса схлопывало бы список до сотни строк
    const id = setInterval(() => void load(0, Math.max(limit, shown)), PENDING_INTERVAL_MS)
    return () => clearInterval(id)
  }, [pending, load, limit, shown])

  const hasMore = shown < total
  const loadMore = useCallback(() => {
    if (!loading && hasMore) void load(shown)
  }, [loading, hasMore, load, shown])

  return { reports, total, loading, error, hasMore, loadMore }
}
