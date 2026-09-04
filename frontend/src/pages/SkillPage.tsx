import { useCallback, useEffect, useState } from 'react'
import { useLocation, Link } from 'react-router-dom'
import type { ReportMeta } from '../types/report'
import { fetchReports } from '../lib/api'
import { EmptyState, Page, PageHeader } from '../components/ui'
import { ReportGrid } from './ReportListPage'

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
    <Page>
      <nav className="mb-3.5 text-sm">
        <Link to={`/skills/${name.split('/')[0]}`} className="text-fg-muted hover:text-accent">
          ← {name.split('/')[0]}
        </Link>
      </nav>
      <PageHeader
        title={
          <>
            Скилл <span className="font-mono text-lg text-fg-muted">{name}</span>
          </>
        }
      />

      {reports.length > 0 ? (
        <ReportGrid reports={reports} />
      ) : (
        <EmptyState title="Отчётов по этому скиллу пока нет" description="Отчёт появится здесь после сборки." />
      )}
    </Page>
  )
}
