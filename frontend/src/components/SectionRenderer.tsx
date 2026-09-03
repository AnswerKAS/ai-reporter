import type { ReportSection } from '../types/report'
import { KpiSectionView } from './KpiSectionView'
import { ChartSectionView } from './ChartSectionView'
import { TableSectionView } from './TableSectionView'
import { MarkdownSectionView } from './MarkdownSectionView'

function SectionTitle({ title }: { title?: string }) {
  if (!title) return null
  return <h3 className="section-title">{title}</h3>
}

/** Фильтр, который к этой секции не применился.

    Без такой пометки читатель уверен, что видит отфильтрованные числа, —
    а показатель, у которого такого разреза нет, остался прежним. */
function FilterNote({ note }: { note?: string }) {
  if (!note) return null
  return <p className="section-filter-note">{note}</p>
}

export function SectionRenderer({ section }: { section: ReportSection }) {
  switch (section.type) {
    case 'markdown':
      return <MarkdownSectionView content={section.content} />
    case 'kpi':
      return (
        <>
          <FilterNote note={section.filterNote} />
          <KpiSectionView items={section.items} />
        </>
      )
    case 'chart':
      return (
        <section className="report-section">
          <SectionTitle title={section.title} />
          <FilterNote note={section.filterNote} />
          <ChartSectionView section={section} />
        </section>
      )
    case 'table':
      return (
        <section className="report-section">
          <SectionTitle title={section.title} />
          <FilterNote note={section.filterNote} />
          <TableSectionView section={section} />
        </section>
      )
    default:
      return null
  }
}