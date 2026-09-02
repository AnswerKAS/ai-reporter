import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ReportMeta } from '../types/report'
import type { SkillInfo } from '../types/dataset'
import { ApiError, fetchReports, fetchSkills } from '../lib/api'
import { domainLabel } from '../lib/domains'

export function DomainPage({ domain }: { domain: string }) {
  const [reports, setReports] = useState<ReportMeta[] | null>(null)
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(() => {
    fetchReports()
      .then(setReports)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'API недоступен'))
  }, [])

  useEffect(() => {
    reload()
    fetchSkills()
      .then((all) => setSkills(all.filter((s) => s.domain === domain)))
      .catch(() => undefined)
  }, [domain, reload])

  const domainReports = useMemo(
    () => (reports ?? []).filter((r) => r.skill?.startsWith(`${domain}/`)),
    [reports, domain],
  )

  const groups = useMemo(() => {
    const map = new Map<string, ReportMeta[]>()
    for (const r of domainReports) {
      const key = r.skill ?? '—'
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(r)
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [domainReports])

  return (
    <main className="page">
      <header className="page-header">
        <h1>{domainLabel(domain)}</h1>
        <p className="muted">Все отчёты по домену <span className="skill-name">{domain}</span></p>
      </header>
      {error && <p className="form-error">{error}</p>}

      {reports !== null && domainReports.length === 0 && (
        <p className="muted">Отчётов по домену пока нет.</p>
      )}

      {groups.map(([skill, items]) => (
        <section key={skill} className="skill-group">
          <h2 className="skill-title">
            <Link to={`/skills/${skill}`} className="skill-group-link">
              {skill.split('/')[1] ?? skill} <span className="skill-name">{skill}</span>
            </Link>
            <span className="muted">({items.length})</span>
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

      {domainReports.length === 0 && skills.length > 0 && (
        <section className="skill-group">
          <h2 className="skill-title">Скиллы домена</h2>
          <div className="draft-pick">
            {skills.map((s) => (
              <Link key={s.name} to={`/skills/${s.name}`} className="sidebar-skill">
                {s.name}
              </Link>
            ))}
          </div>
        </section>
      )}
    </main>
  )
}
