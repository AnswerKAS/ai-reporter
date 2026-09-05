import type { ReportSection } from '../types/report'
import { KpiSectionView } from './KpiSectionView'
import { ChartSectionView } from './ChartSectionView'
import { TableSectionView } from './TableSectionView'
import { MarkdownSectionView } from './MarkdownSectionView'

function SectionTitle({ title }: { title?: string }) {
  if (!title) return null
  return <h2 className="mb-3.5 text-base font-semibold text-fg">{title}</h2>
}

/** Фильтр, который к этой секции не применился.

    Без такой пометки читатель уверен, что видит отфильтрованные числа, —
    а показатель, у которого такого разреза нет, остался прежним. */
function FilterNote({ note }: { note?: string }) {
  if (!note) return null
  return <p className="mb-2 text-xs text-warn">{note}</p>
}

/** Секция показала не всё: сработал потолок строк или число серий графика.

    Пометка идёт под секцией, а не над ней: читатель дошёл до конца данных
    и должен понимать, что дальше они есть, просто их не отдали. */
function RowsNote({ note }: { note?: string }) {
  if (!note) return null
  return <p className="mt-3 text-xs text-fg-muted">{note}</p>
}

const SECTION = 'rounded-card border border-line bg-surface p-5'

/** Обработчик детализации: точка (значения разрезов) и подпись для окна. */
export type DrillHandler = (point: Record<string, string | number | null>, label: string) => void

export function SectionRenderer({ section, onDrill }: { section: ReportSection; onDrill?: DrillHandler }) {
  switch (section.type) {
    case 'markdown':
      return <MarkdownSectionView content={section.content} />
    case 'kpi':
      return (
        <>
          <FilterNote note={section.filterNote} />
          <KpiSectionView items={section.items} onDrill={onDrill} />
        </>
      )
    case 'chart':
      return (
        <section className={SECTION}>
          <SectionTitle title={section.title} />
          <FilterNote note={section.filterNote} />
          <ChartSectionView section={section} onDrill={onDrill} />
          <RowsNote note={section.rowsNote} />
        </section>
      )
    case 'table':
      return (
        <section className={SECTION}>
          <SectionTitle title={section.title} />
          <FilterNote note={section.filterNote} />
          <TableSectionView section={section} onDrill={onDrill} />
          <RowsNote note={section.rowsNote} />
        </section>
      )
    default:
      return null
  }
}
