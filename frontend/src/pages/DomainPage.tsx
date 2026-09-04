import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ReportMeta } from '../types/report'
import type { SkillInfo } from '../types/dataset'
import { ApiError, fetchReports, fetchSkills } from '../lib/api'
import { domainLabel } from '../lib/domains'
import { Alert, EmptyState, Page, PageHeader } from '../components/ui'
import { ReportGrid } from './ReportListPage'

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
    <Page>
      <PageHeader
        title={domainLabel(domain)}
        subtitle={
          <>
            Все отчёты по домену <span className="font-mono text-xs">{domain}</span>
          </>
        }
      />
      {error && <Alert className="mb-4">{error}</Alert>}

      {reports !== null && domainReports.length === 0 && skills.length === 0 && (
        <EmptyState title="Отчётов по домену пока нет" description="Соберите отчёт в конструкторе или выберите другой домен." />
      )}

      {groups.map(([skill, items]) => (
        <section key={skill} className="mb-8">
          <h2 className="mb-3 flex items-baseline gap-2 text-lg font-semibold tracking-tight">
            <Link to={`/skills/${skill}`} className="hover:text-accent">
              {skill.split('/')[1] ?? skill} <span className="font-mono text-xs font-normal text-fg-muted">{skill}</span>
            </Link>
            <span className="text-sm font-normal text-fg-muted">({items.length})</span>
          </h2>
          <ReportGrid reports={items} />
        </section>
      ))}

      {domainReports.length === 0 && skills.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-lg font-semibold tracking-tight">Скиллы домена</h2>
          <div className="flex flex-wrap gap-2">
            {skills.map((s) => (
              <Link
                key={s.name}
                to={`/skills/${s.name}`}
                className="rounded-control border border-line px-3 py-1.5 text-sm transition-colors hover:border-accent hover:text-accent"
              >
                {s.name}
              </Link>
            ))}
          </div>
        </section>
      )}
    </Page>
  )
}
