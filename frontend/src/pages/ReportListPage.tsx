import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ReportMeta } from '../types/report'
import { fetchReports } from '../lib/api'
import { useAuth } from '../lib/auth'
import { ApiError } from '../lib/api'

const DOMAIN_TITLES: Record<string, string> = {
  sales: 'Продажи',
  managers: 'Менеджеры',
  support: 'Поддержка',
  finance: 'Финансы',
  reports: 'Прочие отчёты',
}

function domainOf(skill: string): string {
  return skill.includes('/') ? skill.split('/')[0] : skill
}

function domainTitle(domain: string): string {
  return DOMAIN_TITLES[domain] ?? domain
}

export function ReportListPage() {
  const { user } = useAuth()
  const [reports, setReports] = useState<ReportMeta[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    fetchReports()
      .then((data) => {
        if (alive) setReports(data)
      })
      .catch((err) => {
        if (alive) setError(err instanceof ApiError ? err.message : 'API недоступен')
      })
    return () => {
      alive = false
    }
  }, [])

  const groups = useMemo(() => {
    const map = new Map<string, ReportMeta[]>()
    for (const r of reports ?? []) {
      const key = r.skill ? domainOf(r.skill) : '—'
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(r)
    }
    return [...map.entries()].sort(([a], [b]) => domainTitle(a).localeCompare(domainTitle(b)))
  }, [reports])

  if (error) {
    return (
      <main className="page">
        <header className="page-header">
          <h1>Отчёты</h1>
          <p className="muted">{error}</p>
        </header>
      </main>
    )
  }

  if (reports === null) {
    return (
      <main className="page">
        <p className="muted">Загрузка…</p>
      </main>
    )
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>Отчёты</h1>
        <p className="muted">
          {user ? `${user.username}: сгруппированы по скиллам` : 'Сгруппированы по скиллам'}
        </p>
      </header>

      {reports.length === 0 && (
        <p className="muted">Нет доступных отчётов — обратитесь к администратору.</p>
      )}

      {groups.map(([domain, items]) => (
        <section key={domain} className="skill-group">
          <h2 className="skill-title">
            {domainTitle(domain)} <span className="skill-name">{domain}</span>
          </h2>
          <div className="report-grid">
            {items.map((r) => (
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
        </section>
      ))}
    </main>
  )
}