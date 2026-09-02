import { useCallback, useEffect, useState } from 'react'
import { useLocation, Link } from 'react-router-dom'
import type { ReportMeta } from '../types/report'
import { fetchReports } from '../lib/api'

export function SkillPage() {
  const location = useLocation()
  const name = decodeURIComponent(location.pathname).replace(/^\/skills\//, '')
  const [reports, setReports] = useState<ReportMeta[]>([])

  const reload = useCallback(() => {
    fetchReports()
      .then((all) => setReports(all.filter((r) => r.skill === name)))
      .catch(() => undefined)
  }, [name])

  useEffect(() => {
    reload()
  }, [reload])

  return (
    <main className="page">
      <nav className="crumbs">
        <Link to={`/skills/${name.split('/')[0]}`} className="crumb-link">
          ← {name.split('/')[0]}
        </Link>
      </nav>
      <header className="page-header">
        <h1>Скилл <span className="skill-name">{name}</span></h1>
      </header>

      {reports.length > 0 ? (
        <div className="report-grid skill-page-reports">
          {reports.map((r) => (
            <Link key={r.slug} to={`/reports/${r.slug}`} className="report-card">
              <h3>{r.title}</h3>
              <p className="muted">{r.description}</p>
              <span className="report-date">
                {r.status === 'ready'
                  ? `Обновлён: ${r.updatedAt}`
                  : r.status === 'error'
                    ? `Ошибка: ${r.error}`
                    : `Сборка… (${r.status})`}
              </span>
            </Link>
          ))}
        </div>
      ) : (
        <p className="muted">Отчётов по этому скиллу пока нет.</p>
      )}
    </main>
  )
}
