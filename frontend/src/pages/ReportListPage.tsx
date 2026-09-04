import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import type { ReportMeta } from '../types/report'
import { useAuth } from '../lib/auth'
import { useReports } from '../lib/reports'
import { BUILDER_GROUP, domainLabel, reportGroup } from '../lib/domains'
import { Alert, Badge, Card, EmptyState, Page, PageHeader, SkeletonCards } from '../components/ui'

export function ReportCard({ report }: { report: ReportMeta }) {
  return (
    <Card interactive className="p-0">
      <Link to={`/reports/${report.slug}`} className="block p-5">
        <h3 className="mb-1.5 text-[17px] font-semibold text-fg">{report.title}</h3>
        {report.description && <p className="mb-3.5 text-sm text-fg-muted">{report.description}</p>}
        {report.status === 'ready' ? (
          <span className="text-sm text-fg-muted">Обновлён: {report.updatedAt}</span>
        ) : report.status === 'error' ? (
          <Badge tone="bad">Ошибка: {report.error}</Badge>
        ) : (
          <Badge tone="warn">Сборка… ({report.status})</Badge>
        )}
      </Link>
    </Card>
  )
}

export function ReportGrid({ reports }: { reports: ReportMeta[] }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4">
      {reports.map((r) => (
        <ReportCard key={r.slug} report={r} />
      ))}
    </div>
  )
}

export function ReportListPage() {
  const { user, isAdmin } = useAuth()
  // список живёт в контексте — тот же, что и в меню слева
  const { reports, loading, error } = useReports()

  const groups = useMemo(() => {
    const map = new Map<string, ReportMeta[]>()
    for (const r of reports) {
      const key = reportGroup(r)
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(r)
    }
    return [...map.entries()].sort(([a], [b]) => domainLabel(a).localeCompare(domainLabel(b)))
  }, [reports])

  const newReport = isAdmin ? (
    <Link
      to="/builder"
      className="inline-flex items-center rounded-control border border-accent bg-accent px-3.5 py-1.5 text-sm font-semibold text-accent-fg transition-colors hover:bg-accent-hover"
    >
      Новый отчёт
    </Link>
  ) : undefined

  if (error) {
    return (
      <Page>
        <PageHeader title="Отчёты" actions={newReport} />
        <Alert>{error}</Alert>
      </Page>
    )
  }

  if (loading && reports.length === 0) {
    return (
      <Page>
        <PageHeader title="Отчёты" subtitle="Сгруппированы по скиллам" actions={newReport} />
        <SkeletonCards />
      </Page>
    )
  }

  return (
    <Page>
      <PageHeader
        title="Отчёты"
        subtitle={user ? `${user.username}: сгруппированы по скиллам` : 'Сгруппированы по скиллам'}
        actions={newReport}
      />

      {reports.length === 0 ? (
        <EmptyState
          title="Пока нет доступных отчётов"
          description="Отчёты назначает администратор — обратитесь к нему или соберите свой в конструкторе."
          action={newReport}
        />
      ) : (
        groups.map(([group, items]) => (
          <section key={group} className="mb-8">
            <h2 className="mb-3 flex items-baseline gap-2 text-lg font-semibold tracking-tight">
              {domainLabel(group)}
              {group !== BUILDER_GROUP && (
                <span className="font-mono text-xs font-normal text-fg-muted">{group}</span>
              )}
            </h2>
            <ReportGrid reports={items} />
          </section>
        ))
      )}
    </Page>
  )
}
