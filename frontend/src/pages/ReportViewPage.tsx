import { useEffect, useState } from 'react'
import { useParams, Navigate, Link } from 'react-router-dom'
import type { Report } from '../types/report'
import { applyFilters, fetchReport } from '../lib/api'
import { SectionRenderer } from '../components/SectionRenderer'
import { ReportFilters } from '../components/ReportFilters'

const LIVE_INTERVAL_MS = 15000

export function ReportViewPage() {
  const { slug } = useParams<{ slug: string }>()
  const [report, setReport] = useState<Report | null>(null)
  const [status, setStatus] = useState<string>('loading')
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    if (!slug) return
    let alive = true

    const load = async () => {
      // GET пересчитывает данные из БД — изменения в БД видны сразу
      let data: Report | null = null
      try {
        data = await fetchReport(slug!)
      } catch {
        data = null
      }
      if (!alive) return
      if (data?.sections) {
        setReport(data)
        setStatus('ready')
        return
      }
      const res = await fetch(`/api/reports/${slug}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('ai-reporter-token') ?? ''}` },
      }).catch(() => null)
      if (res && (res.status === 403 || res.status === 404)) {
        setStatus(res.status === 403 ? 'forbidden' : 'missing')
        return
      }
      const meta = res && res.ok ? ((await res.json()) as { report: Report }).report : null
      if (meta) setStatus(meta.status ?? 'unknown')
      else setStatus('error')
    }

    load()
    return () => {
      alive = false
    }
  }, [slug])

  useEffect(() => {
    if (!slug || !report) return
    const id = setInterval(async () => {
      const fresh = await fetchReport(slug)
      if (fresh?.sections) setReport(fresh)
    }, LIVE_INTERVAL_MS)
    return () => clearInterval(id)
  }, [slug, report])

  const onFilterChange = async (key: string, value: string) => {
    if (!slug || !report) return
    const values = { ...(report.filterValues ?? {}), [key]: value }
    setRefreshing(true)
    try {
      const fresh = await applyFilters(slug, values)
      if (fresh?.sections) setReport(fresh)
    } finally {
      setRefreshing(false)
    }
  }

  if (!slug) return <Navigate to="/reports" replace />
  if (!report && status === 'loading') return <main className="page">Загрузка…</main>

  if (!report) {
    if (status === 'building' || status === 'queued') {
      return (
        <main className="page">
          <nav className="crumbs">
            <Link to="/reports" className="crumb-link">← Отчёты</Link>
          </nav>
          <header className="page-header">
            <h1>Идёт сборка отчёта…</h1>
            <p className="muted">Статус: {status}</p>
          </header>
        </main>
      )
    }
    if (status === 'error') {
      return (
        <main className="page">
          <nav className="crumbs">
            <Link to="/reports" className="crumb-link">← Отчёты</Link>
          </nav>
          <header className="page-header">
            <h1>Ошибка сборки отчёта</h1>
            <p className="muted">Попробуйте пересобрать отчёт позже.</p>
          </header>
        </main>
      )
    }
    if (status === 'forbidden') {
      return (
        <main className="page">
          <nav className="crumbs">
            <Link to="/reports" className="crumb-link">← Отчёты</Link>
          </nav>
          <header className="page-header">
            <h1>Нет доступа</h1>
            <p className="muted">Этот отчёт не назначен вашему аккаунту.</p>
          </header>
        </main>
      )
    }
    if (status === 'missing') {
      return <Navigate to="/reports" replace />
    }
    return <Navigate to="/reports" replace />
  }

  return (
    <main className="page">
      <nav className="crumbs">
        <Link to="/reports" className="crumb-link">← Отчёты</Link>
      </nav>
      <header className="page-header">
        <h1>{report.title}</h1>
        {report.description && <p className="muted">{report.description}</p>}
        <div className="meta-line">
          {report.skill && <span className="meta-chip">Скилл: {report.skill}</span>}
          <span className="meta-chip">Обновлён: {report.updatedAt}</span>
          <span className="meta-chip meta-live" title="Данные пересчитываются при открытии страницы">live</span>
        </div>
      </header>

      {report.filters && report.filters.length > 0 && (
        <ReportFilters
          filters={report.filters}
          values={report.filterValues ?? {}}
          disabled={refreshing}
          onChange={onFilterChange}
        />
      )}

      <div className="report-body">
        {report.sections.map((section, i) => (
          <SectionRenderer key={i} section={section} />
        ))}
      </div>
    </main>
  )
}