import type { PerRow, ReportSection } from '../types/report'
import { SectionRenderer, type DrillHandler } from './SectionRenderer'
import { cn } from '../lib/cn'

/** Ширина секции по умолчанию, если автор её не выбирал.

    График половинный: их сравнивают глазами, поставив рядом. Карточки и
    таблица — во всю ширину: у таблицы колонки, и половина превращает их в
    кашу из переносов. */
const DEFAULT_PER_ROW: Record<ReportSection['type'], PerRow> = {
  chart: 2,
  kpi: 1,
  table: 1,
  markdown: 1,
}

/** Сетка секций отчёта: сколько секций встаёт в ряд, выбирает автор.

    Ширина считается по контейнеру, а не по экрану (`@container`): та же
    сетка стоит в предпросмотре конструктора, где колонка узкая, и два
    графика по 300 px рядом читать было бы нечем. */
export function SectionsGrid({
  sections,
  className,
  onDrill,
}: {
  sections: ReportSection[]
  className?: string
  /** Детализация: индекс секции нужен, чтобы сервер знал, чьё сырьё показать. */
  onDrill?: (sectionIndex: number, point: Record<string, string | number | null>, label: string) => void
}) {
  return (
    <div className={cn('@container', className)}>
      <div className="grid grid-cols-1 gap-6 @4xl:grid-cols-2">
        {sections.map((section, i) => {
          const perRow = section.perRow ?? DEFAULT_PER_ROW[section.type]
          return (
            <div
              key={i}
              // min-w-0: без него график с широкой легендой распирает колонку
              // грида, и соседний уезжает за край
              className={cn('min-w-0', perRow === 1 && '@4xl:col-span-2')}
            >
              <SectionRenderer
                section={section}
                onDrill={
                  onDrill
                    ? ((point, label) => onDrill(i, point, label)) satisfies DrillHandler
                    : undefined
                }
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}
