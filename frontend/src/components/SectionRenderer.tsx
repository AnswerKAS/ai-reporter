import type { ReportSection } from '../types/report'
import { KpiSectionView } from './KpiSectionView'
import { ChartSectionView } from './ChartSectionView'
import { TableSectionView } from './TableSectionView'
import { MarkdownSectionView } from './MarkdownSectionView'

function SectionTitle({ title }: { title?: string }) {
  if (!title) return null
  return <h3 className="section-title">{title}</h3>
}

export function SectionRenderer({ section }: { section: ReportSection }) {
  switch (section.type) {
    case 'markdown':
      return <MarkdownSectionView content={section.content} />
    case 'kpi':
      return <KpiSectionView items={section.items} />
    case 'chart':
      return (
        <section className="report-section">
          <SectionTitle title={section.title} />
          <ChartSectionView section={section} />
        </section>
      )
    case 'table':
      return (
        <section className="report-section">
          <SectionTitle title={section.title} />
          <TableSectionView section={section} />
        </section>
      )
    default:
      return null
  }
}