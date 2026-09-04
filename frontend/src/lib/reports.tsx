import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import type { ReportMeta } from '../types/report'
import { ApiError, fetchReports } from './api'
import { useAuth } from './auth'

/** Пока отчёт собирается, список сам себя обновляет — статус в меню живой. */
const PENDING_INTERVAL_MS = 15000

interface ReportsContextValue {
  reports: ReportMeta[]
  loading: boolean
  error: string | null
  /** Перечитать список: вызывать после создания, правки и удаления отчёта. */
  reload: () => Promise<void>
}

const ReportsContext = createContext<ReportsContextValue | null>(null)

function isPending(report: ReportMeta): boolean {
  return report.status !== undefined && report.status !== 'ready' && report.status !== 'error'
}

/**
 * Один список отчётов на всё приложение: им живут и меню слева, и страница
 * списка. Раньше каждая из них ходила в /reports сама, поэтому удаление или
 * создание отчёта на одном экране не было видно на другом.
 */
export function ReportsProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [reports, setReports] = useState<ReportMeta[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const reload = useCallback(async () => {
    if (!user) {
      setReports([])
      return
    }
    try {
      const data = await fetchReports()
      if (!alive.current) return
      setReports(data)
      setError(null)
    } catch (err) {
      if (!alive.current) return
      setError(err instanceof ApiError ? err.message : 'API недоступен')
    }
  }, [user])

  useEffect(() => {
    if (!user) {
      setReports([])
      setError(null)
      setLoading(false)
      return
    }
    setLoading(true)
    reload().finally(() => {
      if (alive.current) setLoading(false)
    })
  }, [user, reload])

  const pending = reports.some(isPending)
  useEffect(() => {
    if (!user || !pending) return
    const id = setInterval(() => void reload(), PENDING_INTERVAL_MS)
    return () => clearInterval(id)
  }, [user, pending, reload])

  return (
    <ReportsContext.Provider value={{ reports, loading, error, reload }}>{children}</ReportsContext.Provider>
  )
}

export function useReports(): ReportsContextValue {
  const ctx = useContext(ReportsContext)
  if (!ctx) throw new Error('useReports вне ReportsProvider')
  return ctx
}
