import { useEffect, useState } from 'react'
import { useParams, Navigate, Link, useNavigate } from 'react-router-dom'
import type { Report } from '../types/report'
import { applyFilters, deleteReport, fetchReport, fetchSkillContent, updateReport } from '../lib/api'
import { SectionRenderer } from '../components/SectionRenderer'
import { ReportFilters } from '../components/ReportFilters'
import { useAuth } from '../lib/auth'

const LIVE_INTERVAL_MS = 15000

function ReportEdit({ report, onSaved }: { report: Report; onSaved: () => void }) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState(report.title)
  const [description, setDescription] = useState(report.description ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setTitle(report.title)
      setDescription(report.description ?? '')
      setError(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, report.slug])

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await updateReport(report.slug, { title: title.trim(), description: description.trim() || undefined })
      setOpen(false)
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'не удалось сохранить')
    } finally {
      setBusy(false)
    }
  }

  // отчёт-конструктор правится там же, где собирался: состав секций,
  // поля и формулы живут в конструкторе, а не в этой форме
  if (report.kind === 'builder') {
    return (
      <Link to={`/builder/${report.slug}`} className="btn btn-ghost">
        Редактировать
      </Link>
    )
  }

  if (!open) {
    return (
      <button type="button" className="btn btn-ghost" onClick={() => setOpen(true)}>
        Редактировать
      </button>
    )
  }

  return (
    <div className="report-edit">
      <label>
        Название
        <input value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label>
        Описание
        <input value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>
      {error && <p className="form-error">{error}</p>}
      <div className="dataset-actions">
        <button type="button" className="btn btn-primary" disabled={busy || !title.trim()} onClick={save}>
          {busy ? 'Сохраняем…' : 'Сохранить'}
        </button>
        <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setOpen(false)}>
          Отмена
        </button>
      </div>
    </div>
  )
}

function SkillInline({ skill }: { skill: string }) {
  const [open, setOpen] = useState(false)
  const [content, setContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const toggle = () => {
    const next = !open
    setOpen(next)
    if (next && content === null && !loading) {
      setLoading(true)
      fetchSkillContent(skill)
        .then(setContent)
        .catch(() => setError('не удалось загрузить текст скилла'))
        .finally(() => setLoading(false))
    }
  }

  return (
    <>
      <button type="button" className={open ? 'meta-chip meta-chip-link active' : 'meta-chip meta-chip-link'} onClick={toggle}>
        Скилл: {skill}
      </button>
      {open && (
        <section className="skill-inline">
          <div className="skill-inline-head">
            <h3>Текст скилла</h3>
            <button type="button" className="btn btn-ghost" onClick={toggle}>
              Скрыть
            </button>
          </div>
          {error ? (
            <p className="form-error">{error}</p>
          ) : content === null ? (
            <p className="muted">Загрузка…</p>
          ) : (
            <pre className="skill-source">{content}</pre>
          )}
        </section>
      )}
    </>
  )
}

export function ReportViewPage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const [report, setReport] = useState<Report | null>(null)
  const [status, setStatus] = useState<string>('loading')
  const [refreshing, setRefreshing] = useState(false)
  const [deleting, setDeleting] = useState(false)

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

  const onDelete = async () => {
    if (!slug || !window.confirm('Удалить отчёт? Назначения доступа и артефакты будут удалены тоже.')) return
    setDeleting(true)
    try {
      await deleteReport(slug)
      navigate('/reports')
    } catch (err) {
      alert(err instanceof Error ? err.message : 'не удалось удалить отчёт')
      setDeleting(false)
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
        <div className="report-head-row">
          <h1>{report.title}</h1>
          <div className="dataset-actions">
            <ReportEdit report={report} onSaved={() => {
              if (!slug) return
              fetchReport(slug).then((fresh) => {
                if (fresh?.sections) setReport(fresh)
              })
            }} />
            {isAdmin && (
              <button type="button" className="btn btn-danger" disabled={deleting} onClick={onDelete}>
                Удалить отчёт
              </button>
            )}
          </div>
        </div>
        {report.description && <p className="muted">{report.description}</p>}
        <div className="meta-line">
          {report.skill && <SkillInline skill={report.skill} />}
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